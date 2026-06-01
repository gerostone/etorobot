# tests/core/test_engine.py
from datetime import datetime, timezone, timedelta
from etorobot.config.settings import RiskConfig
from etorobot.core.types import Candle
from etorobot.core.engine import Engine
from etorobot.feeds.historical import HistoricalFeed
from etorobot.brokers.simulated import SimulatedBroker
from etorobot.strategies.sma import SmaCrossover
from etorobot.risk.manager import RiskManager
from etorobot.persistence.repo import Repository


class FakeNotifier:
    def __init__(self):
        self.messages = []

    async def notify(self, kind, message):
        self.messages.append((kind, message))


def _series(closes):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [Candle(100000, "BTC", base + timedelta(minutes=i),
                   p, p, p, p, 1.0) for i, p in enumerate(closes)]


async def test_engine_runs_and_records_a_trade():
    closes = [10, 9, 8, 9, 10, 11, 12, 13, 14, 15]
    feed = HistoricalFeed(_series(closes))
    broker = SimulatedBroker(starting_cash=1000.0)
    risk = RiskConfig(position_size_pct=0.10, max_open_positions=3,
                      max_positions_per_instrument=1, default_stop_loss_pct=0.02,
                      default_take_profit_pct=0.04, daily_loss_limit_pct=0.5)
    repo = Repository("sqlite:///:memory:")
    notifier = FakeNotifier()
    engine = Engine(feed=feed, strategies=[SmaCrossover(fast=2, slow=3)],
                    risk=RiskManager(risk), broker=broker, repo=repo,
                    notifier=notifier)
    await engine.run()
    assert repo.count_signals() >= 1
    assert repo.count_fills() >= 1
    assert any(k == "fill" for k, _ in notifier.messages)
