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


_SEARCH_URL = f"{BASE}/api/v1/market-data/search"
_SEARCH_JSON = {"page": 1, "pageSize": 100, "totalItems": 2,
                "items": [{"internalSymbolFull": "BTCAUD",
                           "instrumentId": 100154},
                          {"internalSymbolFull": "BTC",
                           "instrumentId": 100000}]}


@respx.mock
async def test_resolve_instrument_uses_search_and_exact_match():
    route = respx.get(_SEARCH_URL).mock(return_value=httpx.Response(
        200, json=_SEARCH_JSON))
    async with _client() as c:
        instrument_id = await c.resolve_instrument("BTC")
        # Second lookup must be served from cache, not a new request.
        cached = await c.resolve_instrument("BTC")
    assert instrument_id == 100000
    assert cached == 100000
    assert route.call_count == 1
    params = dict(route.calls[0].request.url.params)
    # The search endpoint prefix-filters on internalSymbolFull; the client
    # must ask for it and pick the exact match, not the first prefix hit.
    assert params["internalSymbolFull"] == "BTC"
    assert "instrumentId" in params["fields"]


@respx.mock
async def test_resolve_instrument_raises_when_no_exact_match():
    respx.get(_SEARCH_URL).mock(return_value=httpx.Response(
        200, json={"page": 1, "pageSize": 100, "totalItems": 1,
                   "items": [{"internalSymbolFull": "BTCAUD",
                              "instrumentId": 100154}]}))
    async with _client() as c:
        with pytest.raises(ValueError, match="BTC"):
            await c.resolve_instrument("BTC")


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
    route = respx.get(_SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_SEARCH_JSON))
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
    route = respx.get(_SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_SEARCH_JSON))
    async with EtoroClient(api_key="ak", user_key="uk", env="demo") as c:
        await c.resolve_instrument("BTC")
    sent = route.calls[0].request
    assert sent.headers["x-api-key"] == "ak"
    assert sent.headers["x-user-key"] == "uk"
    assert "Authorization" not in sent.headers


@respx.mock
async def test_bearer_401_names_the_agent_token():
    respx.get(_SEARCH_URL).mock(
        return_value=httpx.Response(401, json={"message": "unauthorized"}))
    async with EtoroClient(api_key="ak", user_key="uk", env="demo",
                           agent_token="agtok") as c:
        with pytest.raises(PermissionError, match="ETORO_AGENT_TOKEN"):
            await c.resolve_instrument("BTC")


@respx.mock
async def test_pair_401_keeps_generic_http_error():
    respx.get(_SEARCH_URL).mock(
        return_value=httpx.Response(401, json={"message": "unauthorized"}))
    async with EtoroClient(api_key="ak", user_key="uk", env="demo") as c:
        with pytest.raises(httpx.HTTPStatusError):
            await c.resolve_instrument("BTC")


_AP_URL = f"{BASE}/api/v1/agent-portfolios"


@respx.mock
async def test_is_agent_portfolio_key_true_on_fingerprint_403():
    respx.get(_AP_URL).mock(return_value=httpx.Response(
        403, json={"errorCode": "Forbidden",
                   "errorMessage": "Operation not allowed: this gcid is "
                                   "an agent-portfolio"}))
    async with _client() as c:
        assert await c.is_agent_portfolio_key() is True


@respx.mock
async def test_is_agent_portfolio_key_false_for_main_account_200():
    respx.get(_AP_URL).mock(return_value=httpx.Response(
        200, json={"agentPortfolios": []}))
    async with _client() as c:
        assert await c.is_agent_portfolio_key() is False


@respx.mock
async def test_is_agent_portfolio_key_false_on_other_403():
    respx.get(_AP_URL).mock(return_value=httpx.Response(
        403, json={"errorCode": "InsufficientPermissions",
                   "errorMessage": "UserToken does not have permission"}))
    async with _client() as c:
        assert await c.is_agent_portfolio_key() is False


_LOOKUP_URL = f"{BASE}/api/v2/trading/info/orders:lookup"


@respx.mock
async def test_get_order_real_uses_v2_lookup_and_normalizes():
    # Real order status lives on the v2 lookup endpoint; the response must
    # be normalized into the legacy shape the broker parses.
    route = respx.get(_LOOKUP_URL).mock(return_value=httpx.Response(
        200, json={
            "orderId": 1548059643,
            "status": {"id": 3, "name": "Filled", "errorCode": 0},
            "positionExecutions": [{
                "positionId": 3533695059,
                "state": "open",
                "openingData": {"units": 0.000155, "avgPrice": 64256.0,
                                "fees": 0.1},
            }],
        }))
    c = EtoroClient(api_key="ak", user_key="uk", env="real")
    async with c:
        info = await c.get_order(1548059643)
    params = dict(route.calls[0].request.url.params)
    assert params["orderId"] == "1548059643"
    assert info["positions"] == [{"positionID": 3533695059,
                                  "rate": 64256.0, "units": 0.000155}]
    assert "errorCode" not in info


@respx.mock
async def test_get_order_real_normalizes_error_status():
    respx.get(_LOOKUP_URL).mock(return_value=httpx.Response(
        200, json={"orderId": 1, "positionExecutions": [],
                   "status": {"id": 9, "name": "Rejected",
                              "errorCode": 605,
                              "errorMessage": "Insufficient funds"}}))
    c = EtoroClient(api_key="ak", user_key="uk", env="real")
    async with c:
        info = await c.get_order(1)
    assert info["errorCode"] == 605
    assert info["errorMessage"] == "Insufficient funds"
    assert info["positions"] == []


@respx.mock
async def test_get_order_real_pending_has_empty_positions():
    respx.get(_LOOKUP_URL).mock(return_value=httpx.Response(
        200, json={"orderId": 1, "positionExecutions": [],
                   "status": {"id": 1, "name": "Pending", "errorCode": 0}}))
    c = EtoroClient(api_key="ak", user_key="uk", env="real")
    async with c:
        info = await c.get_order(1)
    assert info.get("positions") == []
    assert "errorCode" not in info


@respx.mock
async def test_get_order_demo_path_unchanged():
    url = f"{BASE}/api/v1/trading/info/demo/orders/42"
    respx.get(url).mock(return_value=httpx.Response(
        200, json={"positions": [{"positionID": 7, "rate": 50000.0,
                                  "units": 0.0002}]}))
    async with _client() as c:
        info = await c.get_order(42)
    assert info["positions"][0]["positionID"] == 7
