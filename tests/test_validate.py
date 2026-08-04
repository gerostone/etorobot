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
