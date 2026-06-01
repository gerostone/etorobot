# src/etorobot/strategies/sma.py
from __future__ import annotations

from collections import deque

from etorobot.core.types import Direction
from etorobot.core.events import MarketEvent, Signal
from etorobot.strategies.base import BaseStrategy


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
            return None
        diff = self._sma(self._fast) - self._sma(self._slow)
        prev = self._prev_diff
        self._prev_diff = diff
        if prev is None:
            return None
        if prev <= 0 < diff and not self._in_position:
            self._in_position = True
            return Signal(c.symbol, c.instrument_id, Direction.BUY, c.timestamp)
        if prev >= 0 > diff:
            if self._in_position:
                self._in_position = False
            return Signal(c.symbol, c.instrument_id, Direction.CLOSE,
                          c.timestamp)
        return None
