# src/etorobot/notify/telegram.py
from __future__ import annotations

import httpx

from etorobot.notify.base import Notifier


class TelegramNotifier(Notifier):
    def __init__(self, token: str, chat_id: str) -> None:
        self._url = f"https://api.telegram.org/bot{token}/sendMessage"
        self._chat_id = chat_id
        self._http = httpx.AsyncClient(timeout=10.0)

    async def notify(self, kind: str, message: str) -> None:
        try:
            await self._http.post(self._url, json={
                "chat_id": self._chat_id, "text": f"[{kind}] {message}"})
        except httpx.HTTPError:
            pass  # notifications must never crash the engine

    async def aclose(self) -> None:
        await self._http.aclose()
