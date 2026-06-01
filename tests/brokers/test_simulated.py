# tests/brokers/test_simulated.py
from datetime import datetime, timezone
from etorobot.core.types import Transaction, Candle
from etorobot.core.events import MarketEvent, OrderEvent
from etorobot.brokers.simulated import SimulatedBroker


def _candle(price):
    return Candle(100000, "BTC", datetime(2026, 1, 1, tzinfo=timezone.utc),
                  price, price, price, price, 1.0)


async def test_open_reduces_cash_and_creates_position():
    b = SimulatedBroker(starting_cash=1000.0, commission_pct=0.01,
                        slippage_pct=0.0, fill_price="close")
    b.on_market_event(MarketEvent(_candle(100.0)))
    fill = await b.execute(OrderEvent("open", "BTC", 100000,
                                      transaction=Transaction.BUY,
                                      amount=500.0, leverage=1))
    pf = await b.get_portfolio()
    assert fill.price == 100.0 and fill.units == 5.0
    assert fill.commission == 5.0  # 500 * 0.01
    assert pf.cash == 495.0  # 1000 - 500 - 5
    assert len(pf.positions) == 1
    assert pf.positions[0].position_id == fill.position_id


async def test_slippage_raises_buy_fill_price():
    b = SimulatedBroker(1000.0, commission_pct=0.0, slippage_pct=0.10,
                        fill_price="close")
    b.on_market_event(MarketEvent(_candle(100.0)))
    fill = await b.execute(OrderEvent("open", "BTC", 100000,
                                      transaction=Transaction.BUY,
                                      amount=110.0))
    assert fill.price == 110.0  # 100 * 1.10


async def test_close_returns_cash_with_profit():
    b = SimulatedBroker(1000.0, commission_pct=0.0, slippage_pct=0.0,
                        fill_price="close")
    b.on_market_event(MarketEvent(_candle(100.0)))
    open_fill = await b.execute(OrderEvent("open", "BTC", 100000,
                                           transaction=Transaction.BUY,
                                           amount=500.0))
    b.on_market_event(MarketEvent(_candle(120.0)))  # price up 20%
    close_fill = await b.execute(OrderEvent("close", "BTC", 100000,
                                            position_id=open_fill.position_id))
    pf = await b.get_portfolio()
    assert close_fill.action == "close"
    assert pf.positions == []
    assert pf.cash == 1100.0  # 500 -> 600, plus untouched 500
