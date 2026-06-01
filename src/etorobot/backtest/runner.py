# src/etorobot/backtest/runner.py
from __future__ import annotations

from etorobot.backtest.metrics import compute_metrics
from etorobot.brokers.simulated import SimulatedBroker
from etorobot.config.settings import BacktestConfig, RiskConfig, StrategyConfig
from etorobot.core.engine import Engine
from etorobot.core.types import Candle
from etorobot.feeds.historical import HistoricalFeed
from etorobot.notify.base import NullNotifier
from etorobot.persistence.repo import Repository
from etorobot.risk.manager import RiskManager
from etorobot.strategies.registry import build_strategy


async def run_backtest(candles_by_instrument: dict[int, list[Candle]],
                       strategy: StrategyConfig, risk: RiskConfig,
                       backtest: BacktestConfig,
                       starting_cash: float = 1000.0) -> dict:
    all_candles: list[Candle] = []
    for candles in candles_by_instrument.values():
        all_candles.extend(candles)

    feed = HistoricalFeed(all_candles)
    broker = SimulatedBroker(starting_cash=starting_cash,
                             commission_pct=backtest.commission_pct,
                             slippage_pct=backtest.slippage_pct,
                             fill_price=backtest.fill_price)
    repo = Repository("sqlite:///:memory:")
    strategies = {iid: [build_strategy(strategy.name, strategy.params)]
                  for iid in candles_by_instrument}
    engine = Engine(feed=feed, strategies=strategies,
                    risk=RiskManager(risk), broker=broker, repo=repo,
                    notifier=NullNotifier())
    await engine.run()
    return compute_metrics(repo.equity_curve(), repo.trade_pnls())
