# src/etorobot/strategies/base.py
from __future__ import annotations

from abc import ABC, abstractmethod

from etorobot.core.events import MarketEvent, Signal


class BaseStrategy(ABC):
    @abstractmethod
    def on_market_event(self, event: MarketEvent) -> Signal | None:
        """Return a Signal to act, or None to do nothing."""
