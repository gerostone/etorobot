# tests/test_validate.py
import json

from etorobot.validate import run_validation


class FakeClient:
    def __init__(self):
        self.calls = []

    async def resolve_instrument(self, symbol):
        self.calls.append("resolve")
        return 100000

    async def get_portfolio(self):
        self.calls.append("portfolio")
        return {"clientPortfolio": {"credit": 200.0, "positions": []}}

    async def create_order(self, **kw):
        self.calls.append("open")
        self.order_kw = kw
        return {"token": "t", "orderId": 42, "referenceId": "r"}

    async def get_order(self, order_id):
        self.calls.append("get_order")
        return {"positions": [{"positionID": 7, "rate": 50000.0,
                               "units": 0.0002}]}

    async def close_position(self, position_id, instrument_id, units=None):
        self.calls.append("close")
        return {"token": "t2"}

    async def get_trade_history(self, min_date, page=1, page_size=50):
        self.calls.append("history")
        return [{"positionId": 7, "closeRate": 50100.0, "units": 0.0002,
                 "fees": 0.05}]


def _inputs(*answers):
    it = iter(answers)
    return lambda prompt: next(it)


async def test_abort_at_open_places_nothing(tmp_path):
    client = FakeClient()
    out = tmp_path / "v.json"
    result = await run_validation(client, "BTC", 10.0, str(out),
                                  input_fn=_inputs("no"), print_fn=lambda *_: None,
                                  poll_interval=0)
    assert "open" not in client.calls
    assert result["aborted"] == "before-open"
    assert json.loads(out.read_text())["aborted"] == "before-open"


async def test_full_round_trip_persists_raw_responses(tmp_path):
    client = FakeClient()
    out = tmp_path / "v.json"
    result = await run_validation(client, "BTC", 10.0, str(out),
                                  input_fn=_inputs("open", "close"),
                                  print_fn=lambda *_: None, poll_interval=0)
    assert client.calls.count("open") == 1
    assert client.calls.count("close") == 1
    saved = json.loads(out.read_text())
    assert saved["steps"]["open_response"]["orderId"] == 42
    assert saved["steps"]["order_status"]["positions"][0]["positionID"] == 7
    assert saved["steps"]["close_settle"]["closeRate"] == 50100.0
    assert result["aborted"] is None


async def test_abort_at_close_reports_open_position(tmp_path):
    client = FakeClient()
    out = tmp_path / "v.json"
    printed = []
    result = await run_validation(client, "BTC", 10.0, str(out),
                                  input_fn=_inputs("open", "nope"),
                                  print_fn=lambda *a: printed.append(" ".join(map(str, a))),
                                  poll_interval=0)
    assert "close" not in client.calls
    assert result["aborted"] == "before-close"
    assert any("7" in line and "OPEN" in line for line in printed)


class CandleClient(FakeClient):
    async def get_candles(self, instrument_id, symbol, interval, count=1):
        from types import SimpleNamespace
        return [SimpleNamespace(close=50000.0)]


class UnresolvedClient(FakeClient):
    async def get_order(self, order_id):
        self.calls.append("get_order")
        return {}


class RejectedClient(FakeClient):
    async def get_order(self, order_id):
        self.calls.append("get_order")
        return {"errorCode": 605, "errorMessage": "Insufficient funds"}


class NoSettleClient(FakeClient):
    async def get_trade_history(self, min_date, page=1, page_size=50):
        self.calls.append("history")
        return []


class ExplodingClient(FakeClient):
    async def get_order(self, order_id):
        raise RuntimeError("boom")


async def test_sl_tp_derived_from_last_candle_and_forwarded(tmp_path):
    client = CandleClient()
    await run_validation(client, "BTC", 10.0, str(tmp_path / "v.json"),
                         input_fn=_inputs("open", "close"),
                         print_fn=lambda *_: None, poll_interval=0)
    assert client.order_kw["stop_loss"] == 47500.0
    assert client.order_kw["take_profit"] == 52500.0


async def test_order_unresolved_reports_and_persists(tmp_path):
    client = UnresolvedClient()
    out = tmp_path / "v.json"
    result = await run_validation(client, "BTC", 10.0, str(out),
                                  input_fn=_inputs("open"),
                                  print_fn=lambda *_: None,
                                  poll_attempts=2, poll_interval=0)
    assert result["aborted"] == "order-unresolved"
    assert json.loads(out.read_text())["steps"]["open_response"]["orderId"] == 42


async def test_rejected_order_reports_error_message(tmp_path):
    client = RejectedClient()
    printed = []
    result = await run_validation(client, "BTC", 10.0,
                                  str(tmp_path / "v.json"),
                                  input_fn=_inputs("open"),
                                  print_fn=lambda *a: printed.append(
                                      " ".join(map(str, a))),
                                  poll_interval=0)
    assert result["aborted"] == "order-rejected"
    assert "close" not in client.calls
    assert any("Insufficient funds" in line for line in printed)
    assert not any("may still fill" in line for line in printed)


async def test_close_unsettled_reported(tmp_path):
    client = NoSettleClient()
    result = await run_validation(client, "BTC", 10.0,
                                  str(tmp_path / "v.json"),
                                  input_fn=_inputs("open", "close"),
                                  print_fn=lambda *_: None,
                                  poll_attempts=2, poll_interval=0)
    assert result["aborted"] == "close-unsettled"
    assert client.calls.count("close") == 1


async def test_exception_after_open_still_persists_and_warns(tmp_path):
    import pytest
    client = ExplodingClient()
    out = tmp_path / "v.json"
    printed = []
    with pytest.raises(RuntimeError, match="boom"):
        await run_validation(client, "BTC", 10.0, str(out),
                             input_fn=_inputs("open"),
                             print_fn=lambda *a: printed.append(
                                 " ".join(map(str, a))),
                             poll_interval=0)
    saved = json.loads(out.read_text())
    assert saved["steps"]["open_response"]["orderId"] == 42
    assert saved["error"]
    assert any("OPEN" in line and "42" in line for line in printed)
