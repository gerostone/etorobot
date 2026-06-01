# tests/data/test_resolve.py
import httpx
import respx
from etorobot.data.client import EtoroClient

BASE = "https://public-api.etoro.com"


@respx.mock
async def test_resolve_instrument_caches():
    route = respx.get(url__regex=rf"{BASE}/api/v1/market-data/instruments/by-symbol/BTC").mock(
        return_value=httpx.Response(200, json={"instrumentId": 100000}))
    async with EtoroClient("ak", "uk", "demo") as c:
        first = await c.resolve_instrument("BTC")
        second = await c.resolve_instrument("BTC")
    assert first == 100000 and second == 100000
    assert route.call_count == 1  # cached on second call
