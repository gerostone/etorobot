# Writing strategies

A strategy is the one piece of code you'll most often want to write yourself. The interface is deliberately tiny: one method, in, one optional signal out. This guide covers the contract, walks through the bundled example, and shows how to add and register your own.

## The contract

Every strategy subclasses `BaseStrategy` (`strategies/base.py`) and implements a single method:

```python
from etorobot.core.events import MarketEvent, Signal
from etorobot.strategies.base import BaseStrategy


class BaseStrategy(ABC):
    @abstractmethod
    def on_market_event(self, event: MarketEvent) -> Signal | None:
        """Return a Signal to act, or None to do nothing."""
```

Things to know about the contract:

- **One event at a time.** The engine calls `on_market_event` once per completed candle, in chronological order, for the instrument this strategy is bound to. You will never receive candles for another instrument, so it's safe to keep per-instrument state (rolling windows, flags) on `self`.
- **It's synchronous.** No `async`. Keep it fast and side-effect-free; the engine handles I/O.
- **Return `None` to abstain.** Most calls should return `None`. Return a `Signal` only when you actually want to act.
- **Failures are isolated.** If `on_market_event` raises, the engine logs it and treats it as `None` — one strategy blowing up never starves the others or aborts the loop. Don't rely on this for control flow, but know your bug won't take the bot down.

### What's in a `MarketEvent`

`event.candle` is a frozen `Candle`:

```python
@dataclass(frozen=True)
class Candle:
    instrument_id: int
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float   # 0.0 on the live feed — eToro's tick stream carries no volume
```

### What's in a `Signal`

```python
@dataclass(frozen=True)
class Signal:
    symbol: str
    instrument_id: int
    direction: Direction          # Direction.BUY | Direction.SELL | Direction.CLOSE
    timestamp: datetime
    strength: float = 1.0
    stop_loss: float | None = None    # absolute price; None → risk manager fills a default
    take_profit: float | None = None  # absolute price; None → risk manager fills a default
    meta: dict = ...
```

Direction semantics, as enforced by the `RiskManager`:

- **`Direction.BUY`** — open a long. Subject to all risk limits (sizing, max positions, daily-loss kill-switch, cash check).
- **`Direction.CLOSE`** — close the open position on this instrument. If there's no open position, the signal is rejected with "no open position to close".
- **`Direction.SELL`** — **rejected in v1** (long-only). You may emit it, but the risk manager refuses it with "short selling disabled (long-only v1)".

You don't size orders or pick instruments to close — you express intent, and the risk manager turns it into a concrete `OrderEvent` (or rejects it). Setting `stop_loss` / `take_profit` lets you override the config defaults for a specific signal; leave them `None` to inherit the configured `default_stop_loss_pct` / `default_take_profit_pct`.

## Walkthrough: the bundled `SmaCrossover`

`strategies/sma.py` is a complete, idiomatic example — fast/slow simple-moving-average crossover:

```python
class SmaCrossover(BaseStrategy):
    def __init__(self, fast: int = 10, slow: int = 30) -> None:
        if fast >= slow:
            raise ValueError("fast must be < slow")
        self._fast = fast
        self._slow = slow
        self._closes: deque[float] = deque(maxlen=slow)
        self._prev_diff: float | None = None
        self._in_position = False

    def _sma(self, n: int) -> float:
        window = list(self._closes)[-n:]
        return sum(window) / n

    def on_market_event(self, event: MarketEvent) -> Signal | None:
        c = event.candle
        self._closes.append(c.close)
        if len(self._closes) < self._slow:
            return None                      # not enough history yet
        diff = self._sma(self._fast) - self._sma(self._slow)
        prev = self._prev_diff
        self._prev_diff = diff
        if prev is None:
            return None
        if prev <= 0 < diff and not self._in_position:   # upward cross → enter
            self._in_position = True
            return Signal(c.symbol, c.instrument_id, Direction.BUY, c.timestamp)
        if prev >= 0 > diff:                              # downward cross → exit
            if self._in_position:
                self._in_position = False
            return Signal(c.symbol, c.instrument_id, Direction.CLOSE, c.timestamp)
        return None
```

What this demonstrates, and what to copy:

1. **Validate params in `__init__`.** `fast >= slow` raises immediately, so a bad config fails loudly at startup rather than silently misbehaving.
2. **Warm-up guard.** Return `None` until you have enough candles (`len(self._closes) < self._slow`).
3. **Edge detection, not level.** It signals on the *crossing* (sign change of `diff`), tracking `_prev_diff`, instead of firing every candle the fast SMA is above the slow.
4. **Track your own position intent.** `_in_position` avoids emitting a second BUY while already long. (The risk manager would also block it via the per-instrument cap, but tracking it keeps the strategy's signals honest.)
5. **A bounded `deque(maxlen=slow)`** keeps memory flat over a long run.

## Adding your own strategy

Three steps.

### 1. Write the class

Create `src/etorobot/strategies/my_strategy.py`:

```python
# src/etorobot/strategies/my_strategy.py
from __future__ import annotations

from collections import deque

from etorobot.core.types import Direction
from etorobot.core.events import MarketEvent, Signal
from etorobot.strategies.base import BaseStrategy


class Momentum(BaseStrategy):
    """Go long when price rises N candles in a row; close on the first down candle."""

    def __init__(self, lookback: int = 3) -> None:
        if lookback < 1:
            raise ValueError("lookback must be >= 1")
        self._lookback = lookback
        self._closes: deque[float] = deque(maxlen=lookback + 1)
        self._in_position = False

    def on_market_event(self, event: MarketEvent) -> Signal | None:
        c = event.candle
        self._closes.append(c.close)
        if len(self._closes) <= self._lookback:
            return None
        window = list(self._closes)
        rising = all(window[i] < window[i + 1] for i in range(len(window) - 1))
        if rising and not self._in_position:
            self._in_position = True
            return Signal(c.symbol, c.instrument_id, Direction.BUY, c.timestamp)
        if not rising and self._in_position:
            self._in_position = False
            return Signal(c.symbol, c.instrument_id, Direction.CLOSE, c.timestamp)
        return None
```

### 2. Register it by name

Add it to the registry in `strategies/registry.py` — the only file you have to touch to wire a strategy in:

```python
from etorobot.strategies.momentum import Momentum  # or wherever you put it
from etorobot.strategies.sma import SmaCrossover

STRATEGIES: dict[str, type[BaseStrategy]] = {
    "sma_crossover": SmaCrossover,
    "momentum": Momentum,
}
```

`build_strategy(name, params)` looks the name up here and calls `cls(**params)`; an unknown name raises `ValueError: unknown strategy: <name>`.

### 3. Select it in config

```yaml
strategy:
  name: momentum
  params: { lookback: 3 }
```

`params` is passed straight through as keyword arguments, so the keys must match your `__init__` signature.

## Testing your strategy

The bundled tests under `tests/strategies/` are the template. A strategy is pure and synchronous, so testing is just: feed it `MarketEvent`s, assert on the `Signal`s. No network, no async fixtures needed.

```python
from datetime import datetime, timezone

from etorobot.core.events import MarketEvent
from etorobot.core.types import Candle, Direction
from etorobot.strategies.momentum import Momentum


def _candle(close: float) -> MarketEvent:
    ts = datetime.now(timezone.utc)
    return MarketEvent(Candle(100000, "BTC", ts, close, close, close, close, 0.0))


def test_momentum_enters_on_rising_run():
    strat = Momentum(lookback=2)
    assert strat.on_market_event(_candle(10)) is None   # warm-up
    assert strat.on_market_event(_candle(11)) is None    # warm-up
    sig = strat.on_market_event(_candle(12))             # 10<11<12 → enter
    assert sig is not None
    assert sig.direction == Direction.BUY
```

Run it:

```bash
pytest tests/strategies/ -v
```

Then prove it end-to-end with a backtest:

```bash
etorobot --config config.yaml backtest --candles 500
```

## Tips and gotchas

- **State is per-instrument and per-run.** Each configured instrument gets its own instance, so `self` state is safe to use — but it does not persist across process restarts.
- **Don't do I/O.** No HTTP calls, no DB reads. The engine owns I/O; a blocking call here stalls the whole loop.
- **Mind warm-up on the live feed.** Live candles only start arriving after you connect, so an indicator needing `N` candles won't fire for the first `N` intervals of a live run. Backtests get full history up front.
- **`volume` is `0.0` live.** Don't build a live strategy around volume — eToro's tick stream doesn't carry it. It's populated in backtests from REST candle history (where available).
- **You can't short in v1.** A `Direction.SELL` will always be rejected. Design entries as BUY and exits as CLOSE.

See [Architecture](architecture.md) for how signals flow through the risk manager and broker, and [Configuration](configuration.md) for the full `strategy` and `risk` field reference.
