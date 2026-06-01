# tests/backtest/test_runner.py
from datetime import datetime, timezone, timedelta
from etorobot.config.settings import RiskConfig, BacktestConfig, StrategyConfig
from etorobot.core.types import Candle
from etorobot.backtest.runner import run_backtest


def _series():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    closes = [10, 9, 8, 9, 10, 11, 12, 11, 10, 8, 7, 9, 11, 13, 15]
    return [Candle(100000, "BTC", base + timedelta(minutes=i), p, p, p, p, 1.0)
            for i, p in enumerate(closes)]


async def test_run_backtest_returns_metrics():
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
        starting_cash=1000.0)
    assert "total_return" in metrics
    assert metrics["num_trades"] >= 1
