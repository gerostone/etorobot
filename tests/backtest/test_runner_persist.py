# tests/backtest/test_runner_persist.py
from datetime import datetime, timedelta, timezone

from etorobot.backtest.runner import run_backtest
from etorobot.config.settings import BacktestConfig, RiskConfig, StrategyConfig
from etorobot.core.types import Candle
from etorobot.persistence.repo import Repository


def _series():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    closes = [10, 9, 8, 9, 10, 11, 12, 11, 10, 8, 7, 9, 11, 13, 15]
    return [Candle(100000, "BTC", base + timedelta(minutes=i), p, p, p, p, 1.0)
            for i, p in enumerate(closes)]


async def test_run_backtest_persists_to_given_repo():
    repo = Repository("sqlite:///:memory:")
    run_id = repo.create_run(mode="backtest", env="demo",
                             strategy="sma_crossover",
                             params={"fast": 2, "slow": 3},
                             timeframe="OneMinute", instruments="BTC",
                             starting_cash=1000.0)
    metrics = await run_backtest(
        candles_by_instrument={100000: _series()},
        strategy=StrategyConfig(name="sma_crossover",
                                params={"fast": 2, "slow": 3}),
        risk=RiskConfig(position_size_pct=0.10, max_open_positions=3,
                        max_positions_per_instrument=1,
                        default_stop_loss_pct=0.02,
                        default_take_profit_pct=0.04,
                        daily_loss_limit_pct=0.9),
        backtest=BacktestConfig(commission_pct=0.0, slippage_pct=0.0,
                                fill_price="close"),
        starting_cash=1000.0, repo=repo, run_id=run_id)
    assert metrics["num_trades"] >= 1
    assert len(repo.run_fills(run_id)) >= 1   # persisted under the run
