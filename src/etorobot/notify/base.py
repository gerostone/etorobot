# src/etorobot/notify/base.py
from __future__ import annotations

from abc import ABC, abstractmethod


class Notifier(ABC):
    @abstractmethod
    async def notify(self, kind: str, message: str) -> None:
        ...


class NullNotifier(Notifier):
    async def notify(self, kind: str, message: str) -> None:
        return None
