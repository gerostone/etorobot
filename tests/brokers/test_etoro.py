# tests/brokers/test_etoro.py
import pytest

from etorobot.core.types import Transaction
from etorobot.core.events import OrderEvent
from etorobot.brokers.etoro import EtoroBroker


class FakeClient:
    """Mirrors the real eToro async order flow.

    Placing/closing an order returns only an order id; the fill (rate, units,
    resolved positionID) is read later via get_order(order_id).
    """

    def __init__(self, *, open_positions=None, fill=None, order_error=None):
        self.created = None
        self.closed = None
        self.get_order_calls = 0
        # Per-poll responses for get_order; each entry is a "positions" list.
        # Defaults to an immediately-resolved single fill.
        self._fill_sequence = fill if fill is not None else [
            [{"positionID": 9001, "rate": 500.0, "units": 1.0,
              "amount": 500.0, "isOpen": True}]
        ]
        self._order_error = order_error
        self._open_positions = open_positions

    async def create_order(self, **kw):
        self.created = kw
        return {"token": "tok-open", "orderId": 13902598,
                "referenceId": "ref-open"}

    async def close_position(self, position_id):
        self.closed = position_id
        return {"orderForClose": {"positionID": 9001, "instrumentID": 100000,
                                  "unitsToDeduct": 1.0, "orderID": 13904638,
                                  "orderType": 19, "statusID": 1, "CID": 1,
                                  "openDateTime": "2026-06-01T00:00:00Z",
                                  "lastUpdate": "2026-06-01T00:00:00Z"},
                "token": "tok-close"}

    async def get_order(self, order_id):
        self.get_order_calls += 1
        if self._order_error is not None:
            return {"orderID": order_id, "errorCode": 1,
                    "errorMessage": self._order_error, "positions": []}
        idx = min(self.get_order_calls - 1, len(self._fill_sequence) - 1)
        return {"orderID": order_id, "errorCode": 0, "errorMessage": None,
                "positions": self._fill_sequence[idx]}

    async def get_portfolio(self):
        positions = self._open_positions if self._open_positions is not None else [
            {"positionID": 9001, "instrumentID": 100000, "isBuy": True,
             "units": 1.0, "amount": 500.0, "openRate": 500.0, "leverage": 1,
             "stopLossRate": 450.0, "takeProfitRate": 600.0}]
        return {"clientPortfolio": {"credit": 1000.0, "positions": positions,
                                    "mirrors": [], "orders": []}}


async def test_open_order_maps_to_fill():
    client = FakeClient()
    broker = EtoroBroker(client, poll_interval=0.0)
    fill = await broker.execute(OrderEvent("open", "BTC", 100000,
                                           transaction=Transaction.BUY,
                                           amount=500.0, leverage=1))
    assert client.created["instrument_id"] == 100000
    assert client.created["transaction"] == "buy"
    # Fill data comes from the resolved order, not the placement response.
    assert fill.position_id == "9001"
    assert fill.price == 500.0
    assert fill.units == 1.0


async def test_open_order_polls_until_position_resolves():
    # First poll: order accepted but not yet filled (empty positions).
    # Second poll: filled.
    client = FakeClient(fill=[
        [],
        [{"positionID": 9001, "rate": 505.0, "units": 2.0,
          "amount": 1010.0, "isOpen": True}],
    ])
    broker = EtoroBroker(client, poll_interval=0.0)
    fill = await broker.execute(OrderEvent("open", "BTC", 100000,
                                           transaction=Transaction.BUY,
                                           amount=1010.0, leverage=1))
    assert client.get_order_calls == 2
    assert fill.price == 505.0
    assert fill.units == 2.0


async def test_close_order_maps_to_fill():
    client = FakeClient(fill=[
        [{"positionID": 9001, "rate": 510.0, "units": 1.0,
          "amount": 510.0, "isOpen": False}]
    ])
    broker = EtoroBroker(client, poll_interval=0.0)
    fill = await broker.execute(OrderEvent("close", "BTC", 100000,
                                           position_id="9001"))
    assert client.closed == "9001"
    assert fill.action == "close"
    assert fill.transaction == Transaction.SELL
    assert fill.price == 510.0
    assert fill.units == 1.0
    assert fill.position_id == "9001"


async def test_order_error_raises():
    client = FakeClient(order_error="insufficient funds")
    broker = EtoroBroker(client, poll_interval=0.0)
    with pytest.raises(RuntimeError, match="insufficient funds"):
        await broker.execute(OrderEvent("open", "BTC", 100000,
                                        transaction=Transaction.BUY,
                                        amount=500.0, leverage=1))


async def test_unfilled_order_times_out():
    client = FakeClient(fill=[[]])  # never resolves
    broker = EtoroBroker(client, poll_interval=0.0, poll_attempts=3)
    with pytest.raises(TimeoutError):
        await broker.execute(OrderEvent("open", "BTC", 100000,
                                        transaction=Transaction.BUY,
                                        amount=500.0, leverage=1))
    assert client.get_order_calls == 3


async def test_get_portfolio_parses_nested_positions():
    broker = EtoroBroker(FakeClient())
    pf = await broker.get_portfolio()
    assert pf.cash == 1000.0
    assert len(pf.positions) == 1
    pos = pf.positions[0]
    assert pos.position_id == "9001"
    assert pos.instrument_id == 100000
    assert pos.transaction == Transaction.BUY
    assert pos.open_price == 500.0
    assert pos.stop_loss == 450.0
    assert pos.take_profit == 600.0


async def test_get_portfolio_empty():
    broker = EtoroBroker(FakeClient(open_positions=[]))
    pf = await broker.get_portfolio()
    assert pf.cash == 1000.0
    assert pf.positions == []
