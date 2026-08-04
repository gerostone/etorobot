# src/etorobot/data/client.py
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

import httpx

from etorobot.core.types import Candle
from etorobot.data.ratelimit import TokenBucket

BASE_URL = "https://public-api.etoro.com"


class EtoroClient:
    def __init__(self, api_key: str, user_key: str, env: str = "demo",
                 agent_token: str | None = None) -> None:
        self._api_key = api_key
        self._user_key = user_key
        self._env = env
        self._agent_token = agent_token
        self._http = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)
        self._read_bucket = TokenBucket(capacity=60, refill_per_sec=1.0)
        self._write_bucket = TokenBucket(capacity=20, refill_per_sec=20 / 60)
        self._instrument_cache: dict[str, int] = {}

    async def __aenter__(self) -> "EtoroClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._http.aclose()

    def _headers(self) -> dict[str, str]:
        # Agent Portfolio tokens are OAuth Bearer credentials and are mutually
        # exclusive with the x-api-key/x-user-key pair on the eToro API.
        if self._agent_token is not None:
            return {
                "Authorization": f"Bearer {self._agent_token}",
                "x-request-id": str(uuid.uuid4()),
                "Content-Type": "application/json",
            }
        return {
            "x-api-key": self._api_key,
            "x-user-key": self._user_key,
            "x-request-id": str(uuid.uuid4()),
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, url: str, *, write: bool,
                       _backoff_base: float = 0.5, **kw) -> httpx.Response:
        bucket = self._write_bucket if write else self._read_bucket
        for attempt in range(5):
            await bucket.acquire()
            resp = await self._http.request(method, url, headers=self._headers(),
                                            **kw)
            if resp.status_code != 429:
                # A rejected Bearer credential deserves a clearer failure
                # than a bare HTTPStatusError: name the token as the likely
                # cause so the user knows what to rotate.
                if (resp.status_code in (401, 403)
                        and self._agent_token is not None):
                    raise PermissionError(
                        f"eToro API returned {resp.status_code}: the "
                        "agent-portfolio token (ETORO_AGENT_TOKEN) was "
                        "rejected — likely expired, blocked by its IP "
                        "whitelist, or missing the required scope.")
                resp.raise_for_status()
                return resp
            await asyncio.sleep(_backoff_base * (2 ** attempt))
        resp.raise_for_status()
        return resp

    async def get_candles(self, instrument_id: int, symbol: str, interval: str,
                          count: int = 100, direction: str = "asc",
                          _backoff_base: float = 0.5) -> list[Candle]:
        url = (f"/api/v1/market-data/instruments/{instrument_id}"
               f"/history/candles/{direction}/{interval}/{count}")
        resp = await self._request("GET", url, write=False,
                                   _backoff_base=_backoff_base)
        data = resp.json()
        out: list[Candle] = []
        for group in data.get("candles", []):
            for c in group.get("candles", []):
                out.append(Candle(
                    instrument_id=int(c["instrumentID"]),
                    symbol=symbol,
                    timestamp=datetime.fromisoformat(
                        c["fromDate"].replace("Z", "+00:00")),
                    open=float(c["open"]), high=float(c["high"]),
                    low=float(c["low"]), close=float(c["close"]),
                    # The live feed returns null volume on some candles.
                    volume=float(c.get("volume") or 0.0),
                ))
        return out

    async def create_order(self, symbol: str, instrument_id: int,
                           transaction: str, amount: float, leverage: int = 1,
                           stop_loss: float | None = None,
                           take_profit: float | None = None) -> dict:
        body = {
            "action": "open",
            "transaction": transaction,
            # The API rejects requests carrying BOTH symbol and instrumentId
            # ("Exactly one of Symbol or InstrumentID must be provided"); send
            # the instrument id, falling back to symbol only if id is absent.
            **({"instrumentId": instrument_id} if instrument_id is not None
               else {"symbol": symbol}),
            "orderType": "mkt",
            "leverage": leverage,
            "amount": amount,
            "orderCurrency": "usd",
        }
        if stop_loss is not None:
            body["stopLossRate"] = stop_loss
        if take_profit is not None:
            body["takeProfitRate"] = take_profit
        # Demo orders go through the /demo/ path; the response is async and
        # carries only {token, orderId, referenceId} — the fill must be read
        # back via get_order(orderId).
        path = ("/api/v2/trading/execution/orders" if self._env == "real"
                else "/api/v2/trading/execution/demo/orders")
        resp = await self._request("POST", path, write=True, json=body)
        return resp.json()

    async def get_order(self, order_id: str | int) -> dict:
        # Order status lookup. Once the order resolves, the response carries a
        # "positions" array with the realized rate/units/positionID.
        segment = "real" if self._env == "real" else "demo"
        resp = await self._request(
            "GET", f"/api/v1/trading/info/{segment}/orders/{order_id}",
            write=False)
        return resp.json()

    async def close_position(self, position_id: str, instrument_id: int,
                             units: float | None = None) -> dict:
        # market-close-orders endpoint, with a /demo/ segment for the demo
        # environment. The body is required (omitting it returns 415);
        # InstrumentID is mandatory, UnitsToDeduct is omitted for a full close.
        prefix = ("/api/v1/trading/execution/market-close-orders"
                  if self._env == "real"
                  else "/api/v1/trading/execution/demo/market-close-orders")
        body: dict = {"InstrumentID": instrument_id}
        if units is not None:
            body["UnitsToDeduct"] = units
        resp = await self._request(
            "POST", f"{prefix}/positions/{position_id}", write=True, json=body)
        return resp.json()

    async def get_trade_history(self, min_date: str, page: int = 1,
                                page_size: int = 50) -> list[dict]:
        # Closed trades (realized closeRate/units/fees per positionId). Close
        # orders have no status endpoint, so the close fill is read from here.
        # minDate is a required YYYY-MM-DD query param; demo inserts /demo/.
        path = ("/api/v1/trading/info/trade/history" if self._env == "real"
                else "/api/v1/trading/info/trade/demo/history")
        resp = await self._request(
            "GET", path, write=False,
            params={"minDate": min_date, "page": page, "pageSize": page_size})
        return resp.json()

    async def get_portfolio(self) -> dict:
        # Verified against OpenAPI spec: trading/info/portfolio (demo variant
        # inserts /demo/). Response shape: {"clientPortfolio": {"positions":
        # [...], "credit": float, "mirrors": [...]}}.
        path = ("/api/v1/trading/info/portfolio" if self._env == "real"
                else "/api/v1/trading/info/demo/portfolio")
        resp = await self._request("GET", path, write=False)
        return resp.json()

    async def is_agent_portfolio_key(self) -> bool:
        # A key pair scoped to an Agent Portfolio (sub-portfolio) cannot list
        # agent-portfolios: eToro answers 403 "this gcid is an
        # agent-portfolio". That distinctive refusal is the fingerprint the
        # real-run guard verifies before allowing pair-auth real trading.
        # A main-account pair answers 200 here and must NOT pass.
        try:
            await self._request("GET", "/api/v1/agent-portfolios",
                                write=False)
        except httpx.HTTPStatusError as exc:
            return (exc.response.status_code == 403
                    and "agent-portfolio" in exc.response.text)
        return False

    async def resolve_instrument(self, symbol: str) -> int:
        if symbol in self._instrument_cache:
            return self._instrument_cache[symbol]
        # /api/v1/instruments/{symbol} was removed by eToro (RouteNotFound as
        # of 2026-08). The market-data search endpoint prefix-filters on
        # internalSymbolFull, so "BTC" also returns BTCAUD etc. — pick the
        # exact ticker match, never the first prefix hit.
        resp = await self._request(
            "GET", "/api/v1/market-data/search", write=False,
            params={"fields": "instrumentId,internalSymbolFull",
                    "internalSymbolFull": symbol, "pageSize": 100})
        for item in resp.json().get("items", []):
            if item.get("internalSymbolFull", "").upper() == symbol.upper():
                instrument_id = int(item["instrumentId"])
                self._instrument_cache[symbol] = instrument_id
                return instrument_id
        raise ValueError(f"no instrument found for symbol {symbol!r}")
