# tests/brokers/test_etoro.py
from etorobot.core.types import Transaction
from etorobot.core.events import OrderEvent
from etorobot.brokers.etoro import EtoroBroker


class FakeClient:
    def __init__(self):
        self.created = None
        self.closed = None

    async def create_order(self, **kw):
        self.created = kw
        return {"positionId": "p1", "executionRate": 500.0, "units": 1.0}

    async def close_position(self, position_id):
        self.closed = position_id
        return {"positionId": position_id, "executionRate": 510.0,
                "units": 1.0}

    async def get_portfolio(self):
        return {"credit": 1000.0, "positions": [
            {"positionId": "p1", "instrumentId": 100000, "isBuy": True,
             "units": 1.0, "amount": 500.0, "openRate": 500.0, "leverage": 1}]}


async def test_open_order_maps_to_fill():
    client = FakeClient()
    broker = EtoroBroker(client)
    fill = await broker.execute(OrderEvent("open", "BTC", 100000,
                                           transaction=Transaction.BUY,
                                           amount=500.0, leverage=1))
    assert client.created["instrument_id"] == 100000
    assert client.created["transaction"] == "buy"
    assert fill.position_id == "p1" and fill.price == 500.0


async def test_close_order_calls_client():
    client = FakeClient()
    broker = EtoroBroker(client)
    fill = await broker.execute(OrderEvent("close", "BTC", 100000,
                                           position_id="p1"))
    assert client.closed == "p1" and fill.action == "close"


async def test_get_portfolio_parses_positions():
    broker = EtoroBroker(FakeClient())
    pf = await broker.get_portfolio()
    assert pf.cash == 1000.0
    assert len(pf.positions) == 1
    assert pf.positions[0].instrument_id == 100000
