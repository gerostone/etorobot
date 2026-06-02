# Architecture

How etorobot is put together, why, and where the seams are. Read this if you want to extend the framework or understand the live/backtest equivalence.

## The core idea: one engine, two modes

The whole design exists to make **one** piece of trading logic run identically in backtest and live. The strategy, the risk manager, the engine, and the persistence layer never know which mode they're in. Only two components are swapped at the edges:

| Edge | Backtest | Live |
|------|----------|------|
| `DataFeed` | `HistoricalFeed` — replays a list of candles | `LiveFeed` — WebSocket ticks aggregated into candles |
| `Broker` | `SimulatedBroker` — fills locally with commission + slippage | `EtoroBroker` — places real demo/real orders over REST |

Both implement the same ABC (`feeds/base.py`, `brokers/base.py`), so the `Engine` is constructed the same way in both paths. Compare `backtest/runner.py` and `cli.py::do_run` — the wiring is nearly identical; only the two edge objects differ.

## Event flow

```
DataFeed ──MarketEvent──▶ Engine ──▶ Strategy ──Signal──▶ RiskManager ──OrderEvent──▶ Broker ──FillEvent──▶
                            │                                                                      │
                            └───────────────── Repository (SQLite) + Notifier observe ◀────────────┘
```

1. A **`DataFeed`** yields `MarketEvent`s (each wraps one `Candle`) from an async generator.
2. The **`Engine`** receives each event and:
   - feeds it to the broker (`broker.on_market_event`) so the simulated broker can mark positions to market;
   - routes it **only** to strategies bound to that event's `instrument_id` (see below).
3. A **`Strategy`** returns a `Signal` (BUY / SELL / CLOSE) or `None`.
4. The **`RiskManager`** turns an accepted `Signal` into an `OrderEvent`, or rejects it with a reason.
5. The **`Broker`** executes the order and returns a `FillEvent`.
6. The **`Repository`** records the signal, the fill, and an equity snapshot. The **`Notifier`** emits a lifecycle/fill/rejection message.

All of this lives in `core/engine.py::Engine.run` — it is small enough to read in one sitting, and that's deliberate.

## Components

### `core/` — the spine
- **`types.py`** — the value objects: `Candle`, `Position`, `Portfolio` (with `equity` and `count_for_instrument`), and the `Direction` / `Transaction` / `OrderType` enums. `Candle`, `Signal`, `MarketEvent`, `OrderEvent`, `FillEvent` are all frozen dataclasses — events are immutable.
- **`events.py`** — `MarketEvent`, `Signal`, `OrderEvent`, `FillEvent`. These are the messages that flow through the pipeline.
- **`engine.py`** — the async event loop. Owns the routing, the signal→order→fill handoff, and the observer dispatch.
- **`bus.py`** — a lightweight pub/sub primitive (infrastructure).

### `feeds/` — where candles come from
- **`base.py`** — `DataFeed` ABC: a single `stream()` async iterator of `MarketEvent`.
- **`historical.py`** — `HistoricalFeed`: sorts candles by timestamp and replays them. That's the entire backtest feed.
- **`live.py`** — `LiveFeed` + `CandleAggregator`. Connects to eToro's WebSocket, authenticates, subscribes to `instrument:<id>` topics, and folds the raw price ticks into OHLCV candles on the configured timeframe. The aggregator emits a candle only when a tick crosses into a new time bucket. The live feed carries no traded volume, so volume is `0.0`.

### `brokers/` — where orders go
- **`base.py`** — `Broker` ABC: `on_market_event`, `execute`, `get_portfolio`.
- **`simulated.py`** — `SimulatedBroker`. Tracks cash and positions in memory, applies `commission_pct` and `slippage_pct`, fills at the candle's `open` or `close` per config, and marks open positions to the latest price on each market event.
- **`etoro.py`** — `EtoroBroker`. Wraps the REST client and bridges eToro's **asynchronous** order model into the synchronous `execute → FillEvent` contract the engine expects (see "The eToro async order model" below).

### `strategies/` — the pluggable logic
- **`base.py`** — `BaseStrategy` ABC with the one method that matters: `on_market_event(event) -> Signal | None`.
- **`sma.py`** — `SmaCrossover`, the bundled example.
- **`registry.py`** — `STRATEGIES` name→class map and `build_strategy(name, params)`. Config selects a strategy by name; this is the only place that needs editing to register a new one.

### `risk/manager.py` — the gatekeeper
`RiskManager.evaluate(signal, portfolio, price, now)` returns a `RiskDecision(accepted, order, reason)`. It is the **only** component that creates `OrderEvent`s, and it enforces every limit in one place:
- **CLOSE** signals resolve to a close order against the matching open position (or reject: "no open position to close").
- **SELL** signals are rejected outright — long-only in v1.
- A **daily-loss kill-switch**: once equity drops below `day_baseline * (1 - daily_loss_limit_pct)`, new opens are refused for the rest of the day. The baseline resets when the calendar date (UTC) changes.
- **Max open positions** (global) and **max positions per instrument**.
- **Position sizing** as `equity * position_size_pct`, refused if it exceeds available cash.
- **Default SL/TP** filled in from `default_stop_loss_pct` / `default_take_profit_pct` when the signal doesn't specify them.

### `data/` — the eToro REST surface
- **`client.py`** — `EtoroClient`: candles, order placement, order status, position close, trade history, portfolio, instrument resolution. Demo vs. real is chosen purely by endpoint path keyed off `ETORO_ENV` — the same API/user keys are used either way.
- **`ratelimit.py`** — `TokenBucket`. The client throttles reads and writes through separate buckets and retries 429s with exponential backoff.

### `persistence/` — the audit trail
- **`models.py`** — three SQLAlchemy tables: `signals`, `fills`, `equity_snapshots`.
- **`repo.py`** — `Repository`. Writes signals/fills/equity, and derives `equity_curve()` and `trade_pnls()` (by matching close fills back to their opens by `position_id`) for the metrics layer.

### `notify/` — optional side-channel
- **`base.py`** — `Notifier` ABC and `NullNotifier` (the no-op default).
- **`telegram.py`** — `TelegramNotifier`, which swallows its own HTTP errors so a flaky Telegram never touches the loop.

### `backtest/` — offline harness
- **`runner.py`** — `run_backtest`: wires `HistoricalFeed` + `SimulatedBroker` + in-memory SQLite into the same `Engine`, runs it, and returns metrics.
- **`metrics.py`** — `compute_metrics`: `total_return`, `max_drawdown`, `sharpe`, `num_trades`, `win_rate`.

## Per-instrument routing

Strategies are registered as `dict[int, list[BaseStrategy]]` keyed by `instrument_id`. The engine routes each `MarketEvent` **only** to the strategies bound to its instrument:

```python
for strategy in self._strategies.get(event.candle.instrument_id, ()):
    ...
```

This guarantees a strategy's internal price history (e.g. the SMA windows) never mixes candles from different instruments. Each configured instrument gets its own strategy instance.

## Resilience: observers can't kill the loop

Persistence and notifications are **observers**. Their failures are logged and swallowed so a flaky DB or a down Telegram can never abort trading:

- `Engine._record(fn, *args)` wraps every repository write in a try/except.
- `Engine._notify(kind, message)` wraps every notifier call.
- `Engine._poll(strategy, event)` isolates each strategy call — one strategy raising never starves the others.

The one thing that *does* propagate is a failure in the feed or broker loop itself: that re-raises after emitting an `error` notification and a `stop`, because if the data feed or the broker is broken there is nothing safe to keep doing.

## The eToro async order model

eToro order placement is asynchronous, and the open and close paths resolve through **different** endpoints. `EtoroBroker` hides this behind a synchronous-looking `execute`:

- **Open.** `create_order` returns only `{token, orderId, referenceId}` — no fill. The broker polls `get_order(orderId)` until a `positions` array appears, then reads the realized `rate` / `units` / `positionID` from it. Budget: `poll_attempts` (default 20).
- **Close.** `close_position` has **no status-lookup endpoint**. The realized `closeRate` / `units` / `fees` only surface in the **trade history**, which lags placement noticeably more than open fills resolve (observed ~10s live). The broker polls `get_trade_history`, matching on `positionId`, with a deliberately larger budget — `close_poll_attempts` (default 40) — so a slow-but-successful settle doesn't raise `TimeoutError` on an order that actually executed (which would desync the bot's position state).

Both paths raise `TimeoutError` if the order never resolves within budget, and the open path raises `RuntimeError` if the order comes back with an error code.

## Design decisions worth knowing

- **Frozen events.** Every event is an immutable dataclass. Messages flowing through the pipeline can't be mutated by a downstream consumer.
- **One order factory.** Only the `RiskManager` builds `OrderEvent`s. Sizing, limits, and SL/TP defaults live in exactly one place, so you can audit "why did/didn't we trade" by reading one file.
- **Long-only in v1.** The risk manager rejects SELL signals. Strategies may still *emit* them; the guard is centralized rather than pushed onto every strategy.
- **Demo/real is a one-word switch with real consequences.** The client selects the endpoint segment off `ETORO_ENV`. v1 is validated against demo only; the real path is implemented but unvalidated.

## Where to look next

- [Configuration reference](configuration.md) — every `.env` and `config.yaml` field.
- [Writing strategies](strategies.md) — implement and register a custom strategy.
- [Design spec](superpowers/specs/2026-06-01-etoro-bot-design.md) — the original design rationale.
