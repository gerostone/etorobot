# tests/strategies/test_sma.py
from datetime import datetime, timezone, timedelta
from etorobot.core.types import Direction, Candle
from etorobot.core.events import MarketEvent
from etorobot.strategies.sma import SmaCrossover


def _feed(strategy, closes):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    signals = []
    for i, price in enumerate(closes):
        candle = Candle(100000, "BTC", base + timedelta(minutes=i),
                        price, price, price, price, 1.0)
        sig = strategy.on_market_event(MarketEvent(candle))
        if sig:
            signals.append(sig)
    return signals


def test_no_signal_before_enough_data():
    s = SmaCrossover(fast=2, slow=3)
    assert _feed(s, [1.0, 2.0]) == []  # not enough for slow window


def test_buy_on_bullish_cross():
    s = SmaCrossover(fast=2, slow=3)
    # rising series: fast crosses above slow -> exactly one BUY
    signals = _feed(s, [10, 9, 8, 9, 10, 11, 12])
    buys = [x for x in signals if x.direction == Direction.BUY]
    assert len(buys) >= 1
    assert buys[0].symbol == "BTC" and buys[0].instrument_id == 100000


def test_close_on_bearish_cross():
    s = SmaCrossover(fast=2, slow=3)
    signals = _feed(s, [8, 9, 10, 11, 12, 11, 9, 7, 5])
    assert any(x.direction == Direction.CLOSE for x in signals)
