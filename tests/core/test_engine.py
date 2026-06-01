# tests/core/test_engine.py
from datetime import datetime, timezone, timedelta
from etorobot.config.settings import RiskConfig
from etorobot.core.types import Candle
from etorobot.core.engine import Engine
from etorobot.feeds.historical import HistoricalFeed
from etorobot.brokers.simulated import SimulatedBroker
from etorobot.strategies.base import BaseStrategy
from etorobot.strategies.sma import SmaCrossover
from etorobot.risk.manager import RiskManager
from etorobot.persistence.repo import Repository


class FakeNotifier:
    def __init__(self):
        self.messages = []

    async def notify(self, kind, message):
        self.messages.append((kind, message))


class RaisingNotifier:
    """Records every attempted notification, then fails like a flaky HTTP call."""

    def __init__(self):
        self.calls = []

    async def notify(self, kind, message):
        self.calls.append((kind, message))
        raise RuntimeError("telegram down")


class RaisingRepo:
    """Mimics a Repository whose every write blows up (e.g. SQLite locked)."""

    def __init__(self):
        self.calls = []

    def record_signal(self, *args, **kwargs):
        self.calls.append("record_signal")
        raise RuntimeError("db locked")

    def record_fill(self, *args, **kwargs):
        self.calls.append("record_fill")
        raise RuntimeError("db locked")

    def record_equity(self, *args, **kwargs):
        self.calls.append("record_equity")
        raise RuntimeError("db locked")


class RaisingStrategy(BaseStrategy):
    def on_market_event(self, event):
        raise RuntimeError("strategy boom")


class RecordingStrategy(BaseStrategy):
    def __init__(self):
        self.seen = 0

    def on_market_event(self, event):
        self.seen += 1
        return None


def _risk_config():
    return RiskConfig(position_size_pct=0.10, max_open_positions=3,
                      max_positions_per_instrument=1, default_stop_loss_pct=0.02,
                      default_take_profit_pct=0.04, daily_loss_limit_pct=0.5)


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
    engine = Engine(feed=feed, strategies={100000: [SmaCrossover(fast=2, slow=3)]},
                    risk=RiskManager(risk), broker=broker, repo=repo,
                    notifier=notifier)
    await engine.run()
    assert repo.count_signals() >= 1
    assert repo.count_fills() >= 1
    assert any(k == "fill" for k, _ in notifier.messages)
    assert notifier.messages[0] == ("start", "engine started")
    assert notifier.messages[-1] == ("stop", "engine stopped")


async def test_failing_observers_do_not_crash_the_run():
    closes = [10, 9, 8, 9, 10, 11, 12, 13, 14, 15]
    feed = HistoricalFeed(_series(closes))
    broker = SimulatedBroker(starting_cash=1000.0)
    repo = RaisingRepo()
    notifier = RaisingNotifier()
    engine = Engine(feed=feed, strategies={100000: [SmaCrossover(fast=2, slow=3)]},
                    risk=RiskManager(_risk_config()), broker=broker,
                    repo=repo, notifier=notifier)

    # A flaky notifier and a broken repo must not abort the trading loop.
    await engine.run()

    # The engine still attempted persistence (and swallowed the failures)...
    assert "record_signal" in repo.calls
    # ...and the lifecycle notifications were still attempted, start to stop.
    assert notifier.calls[0] == ("start", "engine started")
    assert notifier.calls[-1] == ("stop", "engine stopped")


async def test_one_failing_strategy_does_not_block_others():
    closes = [10, 11, 12, 13, 14]
    feed = HistoricalFeed(_series(closes))
    broker = SimulatedBroker(starting_cash=1000.0)
    repo = Repository("sqlite:///:memory:")
    notifier = FakeNotifier()
    recording = RecordingStrategy()
    engine = Engine(feed=feed,
                    strategies={100000: [RaisingStrategy(), recording]},
                    risk=RiskManager(_risk_config()), broker=broker,
                    repo=repo, notifier=notifier)

    await engine.run()

    # The second strategy saw every event despite the first one raising.
    assert recording.seen == len(closes)
    assert notifier.messages[-1] == ("stop", "engine stopped")


async def test_strategies_are_isolated_per_instrument():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = []
    for i in range(5):
        candles.append(Candle(100000, "BTC", base + timedelta(minutes=i),
                              1.0, 1.0, 1.0, 1.0, 1.0))
        candles.append(Candle(200000, "ETH", base + timedelta(minutes=i),
                              2.0, 2.0, 2.0, 2.0, 1.0))
    feed = HistoricalFeed(candles)
    broker = SimulatedBroker(starting_cash=1000.0)
    repo = Repository("sqlite:///:memory:")
    notifier = FakeNotifier()
    btc, eth = RecordingStrategy(), RecordingStrategy()
    engine = Engine(feed=feed, strategies={100000: [btc], 200000: [eth]},
                    risk=RiskManager(_risk_config()), broker=broker,
                    repo=repo, notifier=notifier)

    await engine.run()

    # Each strategy saw only its own instrument's candles — no cross-feed.
    assert btc.seen == 5 and eth.seen == 5
