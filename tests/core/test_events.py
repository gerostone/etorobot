from datetime import datetime, timezone
from etorobot.core.types import Direction, Transaction, OrderType, Candle
from etorobot.core.events import MarketEvent, Signal, OrderEvent, FillEvent


def _candle():
    return Candle(100000, "BTC", datetime(2026, 1, 1, tzinfo=timezone.utc),
                  1, 2, 0.5, 1.5, 10)


def test_market_event_wraps_candle():
    e = MarketEvent(candle=_candle())
    assert e.candle.symbol == "BTC"


def test_signal_defaults():
    s = Signal(symbol="BTC", instrument_id=100000, direction=Direction.BUY,
               timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert s.strength == 1.0 and s.stop_loss is None


def test_order_event_open_and_close():
    o = OrderEvent(action="open", symbol="BTC", instrument_id=100000,
                   transaction=Transaction.BUY, order_type=OrderType.MKT,
                   amount=500.0, leverage=1)
    assert o.action == "open"
    c = OrderEvent(action="close", symbol="BTC", instrument_id=100000,
                   position_id="p1")
    assert c.action == "close" and c.position_id == "p1"


def test_fill_event_fields():
    f = FillEvent(symbol="BTC", instrument_id=100000, action="open",
                  transaction=Transaction.BUY, price=500.0, units=1.0,
                  amount=500.0, commission=0.5, position_id="p1",
                  timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert f.commission == 0.5
