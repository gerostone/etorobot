# tests/feeds/test_aggregator.py
from datetime import datetime, timezone
from etorobot.feeds.live import CandleAggregator, LiveFeed, interval_seconds

# Real frames captured from wss://ws.etoro.com/ws (instrument:100000).
_SNAPSHOT = {"messages": [{
    "topic": "instrument:100000",
    "content": ('{"InstrumentID":"100000","OfficialClosingPrice":"70846.64",'
                '"Ask":"71051.84","Bid":"71051.83","LastExecution":"71051.83",'
                '"Date":"2026-06-01T22:21:12.6164362Z"}'),
    "id": "c10aec7c", "type": "Snapshot"}]}
_RATE = {"messages": [{
    "topic": "instrument:100000",
    "content": ('{"Ask":"71055.71","Bid":"71055.7","LastExecution":"71055.7",'
                '"Date":"2026-06-01T22:21:13.8434831Z","PriceRateID":"144286591897"}'),
    "id": "d048f9be", "type": "Trading.Instrument.Rate"}]}
_PARTIAL = {"messages": [{
    "topic": "instrument:100000",
    "content": '{"Date":"2026-06-01T22:21:15.8858135Z","PriceRateID":"144286592399"}',
    "id": "8fa63e3d", "type": "Trading.Instrument.Rate"}]}


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


def test_parse_tick_snapshot_frame():
    assert LiveFeed._parse_tick(_SNAPSHOT) == [(100000, 71051.83, 0.0)]


def test_parse_tick_rate_frame_uses_topic_for_id():
    # Incremental rate frames omit InstrumentID from content; id comes from topic.
    assert LiveFeed._parse_tick(_RATE) == [(100000, 71055.7, 0.0)]


def test_parse_tick_partial_frame_yields_nothing():
    assert LiveFeed._parse_tick(_PARTIAL) == []


def test_parse_tick_non_price_envelope_yields_nothing():
    assert LiveFeed._parse_tick({"id": "x", "success": True,
                                 "operation": "Subscribe"}) == []
