# src/etorobot/brokers/base.py
from __future__ import annotations

from abc import ABC, abstractmethod

from etorobot.core.events import FillEvent, MarketEvent, OrderEvent
from etorobot.core.types import Portfolio


class Broker(ABC):
    @abstractmethod
    async def execute(self, order: OrderEvent) -> FillEvent:
        ...

    @abstractmethod
    async def get_portfolio(self) -> Portfolio:
        ...

    def on_market_event(self, event: MarketEvent) -> None:
        """Optional: update internal mark prices. No-op by default."""
