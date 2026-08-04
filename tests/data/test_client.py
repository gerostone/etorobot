# tests/data/test_client.py
import json

import pytest

import httpx
import respx
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
    route = respx.post(f"{BASE}/api/v2/trading/execution/demo/orders").mock(
        return_value=httpx.Response(200, json={"token": "tok",
                                               "orderId": 13902598,
                                               "referenceId": "ref"}))
    async with _client() as c:
        resp = await c.create_order(symbol="BTC", instrument_id=100000,
                                    transaction="buy", amount=500.0,
                                    leverage=1)
    body = json.loads(route.calls[0].request.content)
    assert body["action"] == "open"
    assert body["transaction"] == "buy"
    assert body["instrumentId"] == 100000
    # The API rejects requests that supply BOTH symbol and instrumentId
    # ("Exactly one of Symbol or InstrumentID must be provided").
    assert "symbol" not in body
    assert body["orderType"] == "mkt"
    assert body["amount"] == 500.0
    assert resp["orderId"] == 13902598


@respx.mock
async def test_close_position_sends_instrument_body():
    # The close endpoint returns 415 without a JSON body and requires
    # InstrumentID; UnitsToDeduct is omitted for a full close.
    url = (f"{BASE}/api/v1/trading/execution/demo/market-close-orders"
           f"/positions/9001")
    route = respx.post(url).mock(return_value=httpx.Response(
        200, json={"orderForClose": {"orderID": 555}, "token": "t"}))
    async with _client() as c:
        resp = await c.close_position("9001", instrument_id=100000)
    body = json.loads(route.calls[0].request.content)
    assert body["InstrumentID"] == 100000
    assert "UnitsToDeduct" not in body
    assert resp["orderForClose"]["orderID"] == 555


@respx.mock
async def test_get_trade_history_sends_min_date():
    url = f"{BASE}/api/v1/trading/info/trade/demo/history"
    route = respx.get(url).mock(return_value=httpx.Response(
        200, json=[{"positionId": 9001, "closeRate": 510.0, "units": 1.0,
                    "fees": 0.0}]))
    async with _client() as c:
        trades = await c.get_trade_history("2026-06-01")
    assert route.called
    sent = route.calls[0].request
    assert dict(sent.url.params)["minDate"] == "2026-06-01"
    assert trades[0]["positionId"] == 9001
    assert trades[0]["closeRate"] == 510.0


@respx.mock
async def test_resolve_instrument_hits_by_symbol_endpoint():
    url = f"{BASE}/api/v1/instruments/BTC"
    route = respx.get(url).mock(return_value=httpx.Response(
        200, json={"instrumentId": 100000, "symbol": "BTC"}))
    async with _client() as c:
        instrument_id = await c.resolve_instrument("BTC")
        # Second lookup must be served from cache, not a new request.
        cached = await c.resolve_instrument("BTC")
    assert instrument_id == 100000
    assert cached == 100000
    assert route.call_count == 1


@respx.mock
async def test_retries_on_429_then_succeeds():
    route = respx.get(url__regex=rf"{BASE}/api/v1/market-data/.*").mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(200, json={"candles": [{"candles": []}]}),
        ])
    async with _client() as c:
        candles = await c.get_candles(100000, "BTC", "OneHour", count=1,
                                      _backoff_base=0.001)
    assert candles == []
    assert route.call_count == 2


@respx.mock
async def test_agent_token_switches_to_bearer_auth():
    route = respx.get(f"{BASE}/api/v1/instruments/BTC").mock(
        return_value=httpx.Response(200, json={"instrumentId": 100000}))
    async with EtoroClient(api_key="ak", user_key="uk", env="demo",
                           agent_token="agtok") as c:
        await c.resolve_instrument("BTC")
    sent = route.calls[0].request
    assert sent.headers["Authorization"] == "Bearer agtok"
    # Bearer and the key pair are mutually exclusive on the eToro API.
    assert "x-api-key" not in sent.headers
    assert "x-user-key" not in sent.headers
    assert sent.headers["x-request-id"]


@respx.mock
async def test_no_agent_token_keeps_pair_auth():
    route = respx.get(f"{BASE}/api/v1/instruments/BTC").mock(
        return_value=httpx.Response(200, json={"instrumentId": 100000}))
    async with EtoroClient(api_key="ak", user_key="uk", env="demo") as c:
        await c.resolve_instrument("BTC")
    sent = route.calls[0].request
    assert sent.headers["x-api-key"] == "ak"
    assert sent.headers["x-user-key"] == "uk"
    assert "Authorization" not in sent.headers


@respx.mock
async def test_bearer_401_names_the_agent_token():
    respx.get(f"{BASE}/api/v1/instruments/BTC").mock(
        return_value=httpx.Response(401, json={"message": "unauthorized"}))
    async with EtoroClient(api_key="ak", user_key="uk", env="demo",
                           agent_token="agtok") as c:
        with pytest.raises(PermissionError, match="ETORO_AGENT_TOKEN"):
            await c.resolve_instrument("BTC")


@respx.mock
async def test_pair_401_keeps_generic_http_error():
    respx.get(f"{BASE}/api/v1/instruments/BTC").mock(
        return_value=httpx.Response(401, json={"message": "unauthorized"}))
    async with EtoroClient(api_key="ak", user_key="uk", env="demo") as c:
        with pytest.raises(httpx.HTTPStatusError):
            await c.resolve_instrument("BTC")
