# tests/feeds/test_aggregator.py
from datetime import datetime, timezone
from etorobot.feeds.live import CandleAggregator, interval_seconds


def _t(minute, second=0):
    return datetime(2026, 1, 1, 0, minute, second, tzinfo=timezone.utc)


def test_interval_seconds_mapping():
    assert interval_seconds("OneMinute") == 60
    assert interval_seconds("FiveMinutes") == 300
    assert interval_seconds("OneHour") == 3600


def test_first_tick_returns_no_candle():
    agg = CandleAggregator(60, instrument_id=100000, symbol="BTC")
    assert agg.add(price=10.0, volume=1.0, timestamp=_t(0, 5)) is None


def test_emits_completed_candle_when_bucket_rolls():
    agg = CandleAggregator(60, 100000, "BTC")
    agg.add(10.0, 1.0, _t(0, 5))     # open bucket minute 0
    agg.add(12.0, 1.0, _t(0, 30))    # high
    agg.add(9.0, 1.0, _t(0, 45))     # low
    candle = agg.add(11.0, 1.0, _t(1, 2))  # tick in minute 1 -> emit minute 0
    assert candle is not None
    assert candle.open == 10.0 and candle.high == 12.0
    assert candle.low == 9.0 and candle.close == 9.0
    assert candle.volume == 3.0
    assert candle.symbol == "BTC" and candle.instrument_id == 100000
