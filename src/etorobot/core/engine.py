# src/etorobot/core/engine.py
from __future__ import annotations

import logging
from collections.abc import Callable

from etorobot.brokers.base import Broker
from etorobot.core.events import MarketEvent, Signal
from etorobot.feeds.base import DataFeed
from etorobot.persistence.repo import Repository
from etorobot.risk.manager import RiskManager
from etorobot.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class Engine:
    def __init__(self, feed: DataFeed,
                 strategies: dict[int, list[BaseStrategy]],
                 risk: RiskManager, broker: Broker, repo: Repository,
                 notifier) -> None:
        self._feed = feed
        self._strategies = strategies
        self._risk = risk
        self._broker = broker
        self._repo = repo
        self._notifier = notifier

    async def run(self) -> None:
        await self._notify("start", "engine started")
        try:
            async for event in self._feed.stream():
                self._broker.on_market_event(event)
                # Route each event only to strategies bound to its instrument,
                # so a strategy's price history never mixes instruments.
                for strategy in self._strategies.get(
                        event.candle.instrument_id, ()):
                    signal = self._poll(strategy, event)
                    if signal is not None:
                        await self._handle_signal(signal, event)
        except Exception:
            logger.exception("engine loop aborted")
            await self._notify("error", "engine error")
            raise
        finally:
            await self._notify("stop", "engine stopped")

    def _poll(self, strategy: BaseStrategy,
              event: MarketEvent) -> Signal | None:
        """Isolate a single strategy so one failure can't starve the rest."""
        try:
            return strategy.on_market_event(event)
        except Exception:
            logger.exception("strategy %s failed on market event",
                             type(strategy).__name__)
            return None

    async def _notify(self, kind: str, message: str) -> None:
        """Notification is an observer: failures must never abort the loop."""
        try:
            await self._notifier.notify(kind, message)
        except Exception:
            logger.exception("notifier failed for %s", kind)

    def _record(self, fn: Callable[..., None], *args) -> None:
        """Persistence is an observer: failures must never abort the loop."""
        try:
            fn(*args)
        except Exception:
            logger.exception("persistence failed in %s", fn.__name__)

    async def _handle_signal(self, signal: Signal, event: MarketEvent) -> None:
        portfolio = await self._broker.get_portfolio()
        price = event.candle.close
        decision = self._risk.evaluate(signal, portfolio, price,
                                       event.candle.timestamp)
        self._record(self._repo.record_signal, signal, decision.accepted,
                     decision.reason)
        if not decision.accepted:
            await self._notify(
                "rejected", f"{signal.symbol} {signal.direction.value} "
                            f"rejected: {decision.reason}")
            return
        fill = await self._broker.execute(decision.order)
        self._record(self._repo.record_fill, fill)
        portfolio = await self._broker.get_portfolio()
        self._record(self._repo.record_equity, event.candle.timestamp,
                     portfolio.equity, portfolio.cash)
        await self._notify(
            "fill", f"{fill.action} {fill.symbol} {fill.units:.4f} "
                    f"@ {fill.price:.2f}")
