# src/etorobot/data/ratelimit.py
from __future__ import annotations

import asyncio


class TokenBucket:
    """Async token bucket. capacity tokens, refilled at refill_per_sec."""

    def __init__(self, capacity: int, refill_per_sec: float) -> None:
        self._capacity = capacity
        self._refill = refill_per_sec
        self._tokens = float(capacity)
        self._updated = asyncio.get_event_loop().time()
        self._lock = asyncio.Lock()

    def _replenish(self) -> None:
        now = asyncio.get_event_loop().time()
        self._tokens = min(
            self._capacity, self._tokens + (now - self._updated) * self._refill
        )
        self._updated = now

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                self._replenish()
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                deficit = 1 - self._tokens
                await asyncio.sleep(deficit / self._refill)
