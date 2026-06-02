# tests/core/test_engine_run_id.py
from datetime import datetime, timezone

from etorobot.core.engine import Engine
from etorobot.core.events import FillEvent, MarketEvent
from etorobot.core.types import Candle, Direction, Transaction
from etorobot.persistence.repo import Repository
from etorobot.strategies.base import BaseStrategy
from etorobot.core.events import Signal


class _AlwaysBuy(BaseStrategy):
    def on_market_event(self, event):
        c = event.candle
        return Signal(c.symbol, c.instrument_id, Direction.BUY, c.timestamp)


class _Feed:
    def __init__(self, events):
        self._events = events

    async def stream(self):
        for e in self._events:
            yield e


class _Risk:
    def evaluate(self, signal, portfolio, price, now):
        from etorobot.risk.manager import RiskDecision
        from etorobot.core.events import OrderEvent
        return RiskDecision(True, OrderEvent("open", signal.symbol,
                            signal.instrument_id, Transaction.BUY,
                            amount=100.0), None)


class _Portfolio:
    equity = 1000.0
    cash = 900.0


class _Broker:
    def on_market_event(self, event):
        pass

    async def get_portfolio(self):
        return _Portfolio()

    async def execute(self, order):
        return FillEvent("BTC", 1, "open", Transaction.BUY, 100.0, 1.0,
                         100.0, 0.0, "p1",
                         datetime(2026, 1, 1, tzinfo=timezone.utc))


class _Notifier:
    async def notify(self, kind, message):
        pass


async def test_engine_stamps_run_id():
    repo = Repository("sqlite:///:memory:")
    run_id = repo.create_run(mode="backtest", env="demo", strategy="s",
                             params={}, timeframe="OneHour",
                             instruments="BTC", starting_cash=1000.0)
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candle = Candle(1, "BTC", ts, 100.0, 100.0, 100.0, 100.0, 0.0)
    engine = Engine(feed=_Feed([MarketEvent(candle)]),
                    strategies={1: [_AlwaysBuy()]}, risk=_Risk(),
                    broker=_Broker(), repo=repo, notifier=_Notifier(),
                    run_id=run_id)
    await engine.run()
    assert len(repo.run_signals(run_id)) == 1
    assert len(repo.run_fills(run_id)) == 1
    assert len(repo.run_equity(run_id)) == 1
