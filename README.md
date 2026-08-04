# etorobot

An event-driven, **pluggable strategy framework** for the [eToro public API](https://public-api.etoro.com). Asset-agnostic, async, and built so the *same* strategy/risk/engine code runs identically in **backtest** and **live** mode — only the data feed and broker are swapped.

> [!WARNING]
> **Demo/paper trading only.** v1 is validated end-to-end against the eToro **Demo** environment. The `real` switch exists but is **not validated** — running against a real account trades real money. The framework is **long-only** in v1 (short/`SELL` signals are rejected by the risk manager). This software is provided as-is, with no warranty; trading carries risk of loss. You are responsible for any orders it places.

---

## Features

- **One engine, two modes.** A single async `Engine` drives both backtesting and live trading. Swap `HistoricalFeed`↔`LiveFeed` and `SimulatedBroker`↔`EtoroBroker`; everything else is unchanged.
- **Pluggable strategies** behind a one-method interface, selected by name from config.
- **Risk management:** position sizing by equity %, max open positions (global and per-instrument), default stop-loss/take-profit, a daily-loss kill-switch, and a long-only guard.
- **Live market data** via eToro's WebSocket, aggregated into OHLCV candles on any supported timeframe.
- **Backtesting** with a simulated broker (commission + slippage) and performance metrics.
- **SQLite persistence** of every signal, fill, and equity snapshot.
- **Telegram notifications** (optional) for lifecycle, fills, and rejections.
- **Resilient by design:** strategy, persistence, and notifier failures are isolated and never abort the trading loop.

## Requirements

- Python **3.11+**
- eToro public API credentials (API key + user key). A **demo** account is enough for everything in v1.

## Quick start

```bash
# 1. Create a virtualenv and install (editable, with dev deps)
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 2. Configure credentials and strategy
cp .env.example .env                 # fill in ETORO_API_KEY / ETORO_USER_KEY
cp config.example.yaml config.yaml   # tweak instruments / strategy / risk

# 3. Run a backtest (offline-friendly: fetches candles, simulates locally)
etorobot --config config.yaml backtest --candles 500

# 4. Run live against the DEMO account
etorobot --config config.yaml run
```

`etorobot` is installed as a console script (see `[project.scripts]`). You can also invoke it as `python -m etorobot.cli`.

## Configuration

Two files, separated by concern:

- **`.env`** — secrets (git-ignored). Prefix `ETORO_` / `TELEGRAM_`.
- **`config.yaml`** — non-secret runtime config (instruments, strategy, risk, backtest).

Minimal `.env`:

```dotenv
ETORO_API_KEY=your_public_api_key
ETORO_USER_KEY=your_user_key
ETORO_ENV=demo            # demo | real  (default: demo)
# Optional Telegram notifications:
# TELEGRAM_TOKEN=...
# TELEGRAM_CHAT_ID=...
```

Minimal `config.yaml`:

```yaml
timeframe: FiveMinutes
instruments:
  - symbol: BTC
strategy:
  name: sma_crossover
  params: { fast: 10, slow: 30 }
risk:
  position_size_pct: 0.05          # 5% of equity per position
  max_open_positions: 3
  max_positions_per_instrument: 1
  default_stop_loss_pct: 0.02
  default_take_profit_pct: 0.04
  daily_loss_limit_pct: 0.05       # halt new orders after a 5% daily drawdown
backtest:
  commission_pct: 0.001
  slippage_pct: 0.0005
  fill_price: close                # open | close
```

See **[docs/configuration.md](docs/configuration.md)** for the full reference of every field and accepted value.

## CLI

```
etorobot [--config PATH] <command>

  --config PATH        Path to config.yaml (default: config.yaml)

Commands:
  run [--real-money]   Run the engine live against the configured eToro env.
                       --real-money is required (with an Agent Portfolio
                       token) when ETORO_ENV=real.
  validate-real --amount N [--symbol S]
                       Supervised order round-trip: every money-moving step
                       requires a typed confirmation; raw responses are saved
                       for parser-shape diffing.
  backtest [--candles N]
                       Fetch N candles per instrument (default 500) and
                       backtest the configured strategy, printing metrics.
  dashboard [--host H] [--port P] [--db PATH]
                       Serve the read-only web dashboard (default
                       127.0.0.1:8000) over the bot's SQLite database.
```

Example backtest output:

```
total_return: -0.0027
max_drawdown: 0.0027
sharpe: -1.14
num_trades: 9
win_rate: 0.0
```

(Negative numbers here reflect *strategy* performance on the sampled data, not a framework error.)

### Dashboard

A read-only web dashboard follows live runs and backtests in real time — run list, metrics, equity curve, trades, and signals, with live updates over SSE.

```bash
echo 'DASHBOARD_TOKEN=choose-a-long-random-string' >> .env   # required for remote exposure
etorobot --config config.yaml dashboard --host 127.0.0.1 --port 8000
```

Then open <http://127.0.0.1:8000/>. For TLS/remote access, auth, and endpoint details see **[docs/dashboard.md](docs/dashboard.md)**.

## How it works

```
DataFeed ──MarketEvent──▶ Engine ──▶ Strategy ──Signal──▶ RiskManager ──OrderEvent──▶ Broker ──FillEvent──▶
                            │                                                                      │
                            └───────────────── Repository (SQLite) + Notifier observe ◀────────────┘
```

The `Engine` consumes `MarketEvent`s from a `DataFeed`, routes each event **only** to the strategies bound to its instrument, turns strategy `Signal`s into `OrderEvent`s via the `RiskManager`, executes accepted orders through a `Broker`, and records everything. Persistence and notifications are observers: their failures are logged and swallowed so a flaky DB or notifier can never abort trading.

Backtest and live differ only in the two pluggable edges:

| Edge | Backtest | Live |
|------|----------|------|
| `DataFeed` | `HistoricalFeed` (REST candle history) | `LiveFeed` (WebSocket → aggregated candles) |
| `Broker` | `SimulatedBroker` (commission + slippage) | `EtoroBroker` (real demo/real orders) |

Full details in **[docs/architecture.md](docs/architecture.md)**.

## Strategies

A strategy implements one method:

```python
class BaseStrategy(ABC):
    @abstractmethod
    def on_market_event(self, event: MarketEvent) -> Signal | None:
        """Return a Signal to act, or None to do nothing."""
```

The bundled example is `sma_crossover` (`SmaCrossover`, fast/slow SMA). To add your own, implement `BaseStrategy` and register it by name. See **[docs/strategies.md](docs/strategies.md)** for a step-by-step guide.

## Project structure

```
src/etorobot/
  cli.py              # argparse entry point: run / backtest / dashboard
  config/settings.py  # pydantic config + secrets loading (.env + yaml)
  core/
    types.py          # Candle, Position, Portfolio, enums
    events.py         # MarketEvent, Signal, OrderEvent, FillEvent
    engine.py         # the async event loop
    bus.py            # lightweight pub/sub (infrastructure)
  feeds/
    base.py           # DataFeed ABC
    historical.py     # HistoricalFeed (backtest)
    live.py           # LiveFeed + CandleAggregator (WebSocket)
  brokers/
    base.py           # Broker ABC
    simulated.py      # SimulatedBroker (backtest)
    etoro.py          # EtoroBroker (live)
  strategies/
    base.py           # BaseStrategy ABC
    sma.py            # SmaCrossover example
    registry.py       # name -> strategy class
  risk/manager.py     # RiskManager (sizing, limits, SL/TP, kill-switch)
  data/
    client.py         # EtoroClient (REST: candles, orders, portfolio)
    ratelimit.py      # token-bucket rate limiter
  persistence/
    models.py         # SQLAlchemy tables: signals, fills, equity_snapshots
    repo.py           # Repository
  notify/
    base.py           # Notifier ABC + NullNotifier
    telegram.py       # TelegramNotifier
  backtest/
    runner.py         # wires Engine for a backtest
    metrics.py        # total_return, max_drawdown, sharpe, win_rate, ...
tests/                # pytest suite mirroring the package layout
docs/                 # architecture, configuration, strategies + design spec
```

## Persistence

Both live runs and CLI backtests write to `bot_<env>.db` (e.g. `bot_demo.db`) so the dashboard can report on them; a `runs` table groups each session, and signals/fills/equity snapshots carry a `run_id`. Four tables:

- **`signals`** — every signal with `accepted` + `reason` (so you can see *why* a trade was/wasn't taken).
- **`fills`** — every executed open/close with price, units, amount, commission.
- **`equity_snapshots`** — equity + cash after each fill (drives the equity curve).

`*.db` files are git-ignored.

## Testing

```bash
pytest            # full suite
ruff check        # lint
```

`pytest` is configured (`pyproject.toml`) with `asyncio_mode = "auto"` and `pythonpath = ["src"]`, so no manual setup is needed. The eToro REST client is tested with [`respx`](https://lundberg.github.io/respx/) — tests are fully offline.

## Going to a real account (Agent Portfolios)

Real trading is supported **only** through an eToro **Agent Portfolio** — a real-money sub-portfolio with its own scoped Bearer token and a capped allocation (min $200). `ETORO_ENV=real` without `ETORO_AGENT_TOKEN` is refused at startup, and every real session additionally requires the explicit `run --real-money` flag. Before going live, run the supervised `etorobot validate-real` round-trip yourself — it confirms the real response shapes match the demo ones the parsers were built against. Full setup and runbook: **[docs/going-real.md](docs/going-real.md)**.

## Documentation

- [Architecture](docs/architecture.md) — event flow, components, design decisions
- [Configuration reference](docs/configuration.md) — every `.env` and `config.yaml` field
- [Dashboard](docs/dashboard.md) — read-only web view of runs (live + backtests)
- [Going real: Agent Portfolios](docs/going-real.md) — scoped-token setup and the supervised validation runbook
- [Writing strategies](docs/strategies.md) — implement and register a custom strategy
- [Design spec](docs/superpowers/specs/2026-06-01-etoro-bot-design.md) — original design
- [Implementation plan](docs/superpowers/plans/2026-06-01-etoro-bot.md) — task-by-task build log
