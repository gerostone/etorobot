# src/etorobot/feeds/historical.py
from __future__ import annotations

from collections.abc import AsyncIterator

from etorobot.core.events import MarketEvent
from etorobot.core.types import Candle
from etorobot.feeds.base import DataFeed


class HistoricalFeed(DataFeed):
    def __init__(self, candles: list[Candle]) -> None:
        self._candles = sorted(candles, key=lambda c: c.timestamp)

    async def stream(self) -> AsyncIterator[MarketEvent]:
        for candle in self._candles:
            yield MarketEvent(candle)
