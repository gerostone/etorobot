# src/etorobot/core/engine.py
from __future__ import annotations

from etorobot.brokers.base import Broker
from etorobot.core.events import MarketEvent, Signal
from etorobot.feeds.base import DataFeed
from etorobot.persistence.repo import Repository
from etorobot.risk.manager import RiskManager
from etorobot.strategies.base import BaseStrategy


class Engine:
    def __init__(self, feed: DataFeed, strategies: list[BaseStrategy],
                 risk: RiskManager, broker: Broker, repo: Repository,
                 notifier) -> None:
        self._feed = feed
        self._strategies = strategies
        self._risk = risk
        self._broker = broker
        self._repo = repo
        self._notifier = notifier

    async def run(self) -> None:
        await self._notifier.notify("start", "engine started")
        async for event in self._feed.stream():
            self._broker.on_market_event(event)
            for strategy in self._strategies:
                signal = strategy.on_market_event(event)
                if signal is not None:
                    await self._handle_signal(signal, event)
        await self._notifier.notify("stop", "engine stopped")

    async def _handle_signal(self, signal: Signal, event: MarketEvent) -> None:
        portfolio = await self._broker.get_portfolio()
        price = event.candle.close
        decision = self._risk.evaluate(signal, portfolio, price,
                                       event.candle.timestamp)
        self._repo.record_signal(signal, decision.accepted, decision.reason)
        if not decision.accepted:
            await self._notifier.notify(
                "rejected", f"{signal.symbol} {signal.direction.value} "
                            f"rejected: {decision.reason}")
            return
        fill = await self._broker.execute(decision.order)
        self._repo.record_fill(fill)
        portfolio = await self._broker.get_portfolio()
        self._repo.record_equity(event.candle.timestamp, portfolio.equity,
                                 portfolio.cash)
        await self._notifier.notify(
            "fill", f"{fill.action} {fill.symbol} {fill.units:.4f} "
                    f"@ {fill.price:.2f}")
