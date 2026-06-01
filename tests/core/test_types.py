from datetime import datetime, timezone
from etorobot.core.types import (
    Direction, Transaction, OrderType, Candle, Position, Portfolio,
)


def test_candle_holds_ohlcv():
    c = Candle(
        instrument_id=100000, symbol="BTC",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0,
    )
    assert c.close == 1.5 and c.symbol == "BTC"


def test_portfolio_equity_includes_cash():
    p = Portfolio(cash=1000.0, positions=[])
    assert p.equity == 1000.0


def test_portfolio_open_amount_for_instrument():
    pos = Position(
        position_id="1", symbol="BTC", instrument_id=100000,
        transaction=Transaction.BUY, units=1.0, amount=500.0,
        open_price=500.0, leverage=1, stop_loss=None, take_profit=None,
    )
    p = Portfolio(cash=500.0, positions=[pos])
    assert p.count_for_instrument(100000) == 1
    assert p.count_for_instrument(999) == 0
    assert Direction.BUY and OrderType.MKT
