# src/etorobot/feeds/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from etorobot.core.events import MarketEvent


class DataFeed(ABC):
    @abstractmethod
    def stream(self) -> AsyncIterator[MarketEvent]:
        ...
