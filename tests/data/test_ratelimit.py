# tests/data/test_ratelimit.py
import asyncio
from etorobot.data.ratelimit import TokenBucket


async def test_allows_up_to_capacity_without_waiting():
    bucket = TokenBucket(capacity=3, refill_per_sec=1000)
    start = asyncio.get_event_loop().time()
    for _ in range(3):
        await bucket.acquire()
    assert asyncio.get_event_loop().time() - start < 0.05


async def test_blocks_when_empty_until_refill():
    bucket = TokenBucket(capacity=1, refill_per_sec=50)  # 1 token / 20ms
    await bucket.acquire()
    start = asyncio.get_event_loop().time()
    await bucket.acquire()
    elapsed = asyncio.get_event_loop().time() - start
    assert elapsed >= 0.015
