# src/etorobot/feeds/live.py
from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import websockets

from etorobot.core.events import MarketEvent
from etorobot.core.types import Candle
from etorobot.feeds.base import DataFeed

WS_URL = "wss://ws.etoro.com/ws"

_INTERVALS = {
    "OneMinute": 60, "FiveMinutes": 300, "TenMinutes": 600,
    "FifteenMinutes": 900, "ThirtyMinutes": 1800, "OneHour": 3600,
    "FourHours": 14400, "OneDay": 86400, "OneWeek": 604800,
}


def interval_seconds(name: str) -> int:
    return _INTERVALS[name]


class CandleAggregator:
    def __init__(self, interval: int, instrument_id: int, symbol: str) -> None:
        self._interval = interval
        self._instrument_id = instrument_id
        self._symbol = symbol
        self._bucket: int | None = None
        self._o = self._h = self._l = self._c = 0.0
        self._v = 0.0

    def _bucket_of(self, ts: datetime) -> int:
        return int(ts.timestamp()) // self._interval

    def add(self, price: float, volume: float,
            timestamp: datetime) -> Candle | None:
        bucket = self._bucket_of(timestamp)
        if self._bucket is None:
            self._start(bucket, price, volume)
            return None
        if bucket == self._bucket:
            self._h = max(self._h, price)
            self._l = min(self._l, price)
            self._c = price
            self._v += volume
            return None
        completed = Candle(
            self._instrument_id, self._symbol,
            datetime.fromtimestamp(self._bucket * self._interval, timezone.utc),
            self._o, self._h, self._l, self._c, self._v)
        self._start(bucket, price, volume)
        return completed

    def _start(self, bucket: int, price: float, volume: float) -> None:
        self._bucket = bucket
        self._o = self._h = self._l = self._c = price
        self._v = volume


class LiveFeed(DataFeed):
    def __init__(self, api_key: str, user_key: str,
                 instruments: dict[int, str], interval: str) -> None:
        self._api_key = api_key
        self._user_key = user_key
        self._instruments = instruments  # {instrument_id: symbol}
        self._interval = interval_seconds(interval)

    @staticmethod
    def _parse_tick(msg: dict) -> list[tuple[int, float, float]]:
        """Extract (instrument_id, price, volume) tuples from a price frame.

        Verified against the live eToro feed: a frame is
        {"messages": [{"topic": "instrument:<id>", "content": "<json-string>",
        "type": "Snapshot" | "Trading.Instrument.Rate", ...}, ...]}. The
        instrument id lives in `topic` because incremental rate updates omit it
        from the payload; `content` is a doubly-encoded JSON string whose
        `LastExecution` field is the price. Partial frames (heartbeat-style
        updates carrying only Date/PriceRateID) have no price and are skipped.
        The feed carries no traded volume, so volume is 0.0."""
        out: list[tuple[int, float, float]] = []
        for entry in msg.get("messages", []):
            topic = entry.get("topic", "")
            if not topic.startswith("instrument:"):
                continue
            try:
                content = json.loads(entry["content"])
            except (KeyError, TypeError, json.JSONDecodeError):
                continue
            if "LastExecution" not in content:
                continue
            out.append((int(topic.split(":", 1)[1]),
                        float(content["LastExecution"]), 0.0))
        return out

    @staticmethod
    async def _await_ack(ws, operation: str) -> None:
        """Wait for the JSON ack of `operation`, skipping the binary keepalive
        frames the server interleaves. Raises on a non-success ack."""
        async for raw in ws:
            if isinstance(raw, (bytes, bytearray)):
                continue  # application-level keepalive precedes the JSON ack
            ack = json.loads(raw)
            if ack.get("operation") != operation:
                continue
            if not ack.get("success"):
                raise RuntimeError(
                    f"{operation} failed: {ack.get('errorMessage', ack)}")
            return
        raise RuntimeError(f"connection closed before {operation} ack")

    async def stream(self) -> AsyncIterator[MarketEvent]:
        aggs = {iid: CandleAggregator(self._interval, iid, sym)
                for iid, sym in self._instruments.items()}
        async with websockets.connect(WS_URL) as ws:
            await ws.send(json.dumps({
                "id": str(uuid.uuid4()), "operation": "Authenticate",
                "data": {"userKey": self._user_key, "apiKey": self._api_key}}))
            await self._await_ack(ws, "Authenticate")
            await ws.send(json.dumps({
                "id": str(uuid.uuid4()), "operation": "Subscribe",
                "data": {"topics": [f"instrument:{i}" for i in self._instruments],
                         "snapshot": False}}))
            await self._await_ack(ws, "Subscribe")
            async for raw in ws:
                if isinstance(raw, (bytes, bytearray)):
                    continue  # application-level keepalive
                for iid, price, volume in self._parse_tick(json.loads(raw)):
                    agg = aggs.get(iid)
                    if agg is None:
                        continue
                    candle = agg.add(price, volume, datetime.now(timezone.utc))
                    if candle is not None:
                        yield MarketEvent(candle)
