# src/etorobot/dashboard/sse.py
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import Request

from etorobot.dashboard.tailer import DbTailer


def _format(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


async def event_stream(tailer: DbTailer, poll_interval: float,
                       request: Request) -> AsyncIterator[str]:
    """Yield SSE frames for new rows until the run closes or client leaves."""
    while True:
        if await request.is_disconnected():
            break
        for ev in tailer.poll():
            yield _format(ev["type"], ev["data"])
        if tailer.closed():
            yield _format("run_status", {"status": tailer.run_status()})
            break
        await asyncio.sleep(poll_interval)
