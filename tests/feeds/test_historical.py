# tests/feeds/test_historical.py
from datetime import datetime, timezone, timedelta
from etorobot.core.types import Candle
from etorobot.feeds.historical import HistoricalFeed


def _candles(n):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # deliberately out of order to test sorting
    raw = [Candle(100000, "BTC", base + timedelta(minutes=i),
                  i, i, i, i, 1.0) for i in range(n)]
    return list(reversed(raw))


async def test_streams_candles_in_chronological_order():
    feed = HistoricalFeed(_candles(3))
    out = [e.candle.close async for e in feed.stream()]
    assert out == [0, 1, 2]
