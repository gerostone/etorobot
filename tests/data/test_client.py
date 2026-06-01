# tests/data/test_client.py
import httpx
import respx
import pytest
from datetime import datetime
from etorobot.data.client import EtoroClient

BASE = "https://public-api.etoro.com"


def _client():
    return EtoroClient(api_key="ak", user_key="uk", env="demo")


@respx.mock
async def test_get_candles_parses_ohlcv():
    route = respx.get(url__regex=rf"{BASE}/api/v1/market-data/.*").mock(
        return_value=httpx.Response(200, json={
            "interval": "OneHour",
            "candles": [{"candles": [
                {"instrumentID": 100000, "fromDate": "2026-01-01T00:00:00Z",
                 "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5,
                 "volume": 10.0}
            ]}],
        }))
    async with _client() as c:
        candles = await c.get_candles(100000, "BTC", "OneHour", count=1)
    assert route.called
    sent = route.calls[0].request
    assert sent.headers["x-api-key"] == "ak"
    assert sent.headers["x-user-key"] == "uk"
    assert sent.headers["x-request-id"]
    assert len(candles) == 1
    assert candles[0].close == 1.5
    assert candles[0].symbol == "BTC"
    assert isinstance(candles[0].timestamp, datetime)


@respx.mock
async def test_create_order_builds_body():
    route = respx.post(f"{BASE}/api/v2/trading/execution/orders").mock(
        return_value=httpx.Response(200, json={"positionId": "p1",
                                               "executionRate": 500.0,
                                               "units": 1.0}))
    async with _client() as c:
        resp = await c.create_order(symbol="BTC", instrument_id=100000,
                                    transaction="buy", amount=500.0,
                                    leverage=1)
    import json
    body = json.loads(route.calls[0].request.content)
    assert body["action"] == "open"
    assert body["transaction"] == "buy"
    assert body["instrumentId"] == 100000
    assert body["orderType"] == "mkt"
    assert body["amount"] == 500.0
    assert resp["positionId"] == "p1"


@respx.mock
async def test_retries_on_429_then_succeeds():
    respx.get(url__regex=rf"{BASE}/api/v1/market-data/.*").mock(side_effect=[
        httpx.Response(429),
        httpx.Response(200, json={"candles": [{"candles": []}]}),
    ])
    async with _client() as c:
        candles = await c.get_candles(100000, "BTC", "OneHour", count=1,
                                      _backoff_base=0.001)
    assert candles == []
