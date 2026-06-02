# Configuration reference

etorobot is configured by two files, split by concern:

- **`.env`** — secrets (git-ignored). Loaded by pydantic-settings from environment variables prefixed `ETORO_` / `TELEGRAM_`.
- **`config.yaml`** — non-secret runtime config (instruments, strategy, risk, backtest).

`load_config(path)` reads the YAML and merges in `Secrets()` and `TelegramSecrets()` (both read from the environment / `.env`) to build a single `AppConfig`. Every field below maps directly to a model in `config/settings.py`.

---

## `.env` — secrets

### eToro credentials (`ETORO_` prefix) — `Secrets`

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `ETORO_API_KEY` | yes | — | Your eToro public API key. |
| `ETORO_USER_KEY` | yes | — | Your eToro user key (the long `eyJ…` token). Sent as the `x-user-key` header. |
| `ETORO_ENV` | no | `demo` | `demo` or `real`. Selects which endpoint segment the REST client uses. **The same keys are used for both** — only the URL path changes. |

```dotenv
ETORO_API_KEY=your_public_api_key
ETORO_USER_KEY=your_user_key
ETORO_ENV=demo
```

> `ETORO_ENV=real` trades real money and is **not validated** in v1. See the README's "Going to a real account" section before flipping it.

### Telegram notifications (`TELEGRAM_` prefix) — `TelegramSecrets`

Both optional. If **either** is missing, the bot uses `NullNotifier` (no notifications). Set **both** to enable Telegram.

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `TELEGRAM_TOKEN` | no | `None` | Bot token from `@BotFather`. |
| `TELEGRAM_CHAT_ID` | no | `None` | Target chat id. |

```dotenv
# TELEGRAM_TOKEN=123456:ABC-DEF...
# TELEGRAM_CHAT_ID=987654321
```

Unknown `ETORO_*` / `TELEGRAM_*` variables are ignored (`extra="ignore"`), so it's safe to keep other env vars in the same `.env`.

---

## `config.yaml` — runtime config

Top-level shape (`AppConfig`):

```yaml
timeframe: FiveMinutes
instruments: [...]
strategy: {...}
risk: {...}
backtest: {...}
```

All five keys are required. `secrets` and `telegram` are **not** set here — they come from `.env`.

### `timeframe` (string)

The candle interval. Used live to bucket WebSocket ticks (`CandleAggregator`) and in backtest as the candle granularity requested from the REST API. Accepted values (`feeds/live.py::_INTERVALS`):

| Value | Length |
|-------|--------|
| `OneMinute` | 60s |
| `FiveMinutes` | 5m |
| `TenMinutes` | 10m |
| `FifteenMinutes` | 15m |
| `ThirtyMinutes` | 30m |
| `OneHour` | 1h |
| `FourHours` | 4h |
| `OneDay` | 1d |
| `OneWeek` | 1w |

### `instruments` (list) — `InstrumentConfig`

A list of objects, each with a `symbol`. Symbols are resolved to numeric eToro instrument ids at startup via `resolve_instrument`.

```yaml
instruments:
  - symbol: BTC
  - symbol: ETH
```

| Field | Type | Notes |
|-------|------|-------|
| `symbol` | string | eToro ticker, e.g. `BTC`. Each instrument gets its own strategy instance. |

### `strategy` (object) — `StrategyConfig`

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `name` | string | — | Key into the strategy registry (`strategies/registry.py`). Bundled: `sma_crossover`. |
| `params` | object | `{}` | Passed as keyword arguments to the strategy constructor. |

```yaml
strategy:
  name: sma_crossover
  params: { fast: 10, slow: 30 }
```

`sma_crossover` (`SmaCrossover`) params:

| Param | Type | Default | Notes |
|-------|------|---------|-------|
| `fast` | int | `10` | Fast SMA window. |
| `slow` | int | `30` | Slow SMA window. Must be `> fast` (the constructor raises `ValueError` otherwise). |

### `risk` (object) — `RiskConfig`

**All six fields are required** — `RiskConfig` defines no defaults.

| Field | Type | Notes |
|-------|------|-------|
| `position_size_pct` | float | Fraction of **equity** per new position, e.g. `0.05` = 5%. Rejected if the sized amount exceeds available cash. |
| `max_open_positions` | int | Global cap on simultaneously open positions. |
| `max_positions_per_instrument` | int | Per-instrument cap. |
| `default_stop_loss_pct` | float | Default stop-loss distance, used when a signal doesn't specify one. For a long: `price * (1 - pct)`. |
| `default_take_profit_pct` | float | Default take-profit distance. For a long: `price * (1 + pct)`. |
| `daily_loss_limit_pct` | float | Kill-switch threshold. New opens are refused once equity falls to `day_baseline * (1 - pct)`. Baseline resets each UTC day. |

```yaml
risk:
  position_size_pct: 0.05
  max_open_positions: 3
  max_positions_per_instrument: 1
  default_stop_loss_pct: 0.02
  default_take_profit_pct: 0.04
  daily_loss_limit_pct: 0.05
```

### `backtest` (object) — `BacktestConfig`

Only consulted by the `backtest` command (the `SimulatedBroker`). All fields have defaults.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `commission_pct` | float | `0.0` | Commission as a fraction of trade amount, charged on both open and close. |
| `slippage_pct` | float | `0.0` | Price slippage. Buys fill higher, sells fill lower, by this fraction. |
| `fill_price` | `open` \| `close` | `close` | Which candle price fills are struck at. |

```yaml
backtest:
  commission_pct: 0.001
  slippage_pct: 0.0005
  fill_price: close
```

---

## Full example

`.env`:

```dotenv
ETORO_API_KEY=your_public_api_key
ETORO_USER_KEY=your_user_key
ETORO_ENV=demo
# TELEGRAM_TOKEN=...
# TELEGRAM_CHAT_ID=...
```

`config.yaml`:

```yaml
timeframe: FiveMinutes
instruments:
  - symbol: BTC
strategy:
  name: sma_crossover
  params: { fast: 10, slow: 30 }
risk:
  position_size_pct: 0.05
  max_open_positions: 3
  max_positions_per_instrument: 1
  default_stop_loss_pct: 0.02
  default_take_profit_pct: 0.04
  daily_loss_limit_pct: 0.05
backtest:
  commission_pct: 0.001
  slippage_pct: 0.0005
  fill_price: close
```

## Persistence side effects

Config doesn't set the database path directly, but it determines it: live runs write to `bot_<ETORO_ENV>.db` (e.g. `bot_demo.db`); backtests use an in-memory SQLite DB. `*.db` files are git-ignored. See the README's Persistence section for the table layout.
