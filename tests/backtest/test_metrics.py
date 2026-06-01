# tests/backtest/test_metrics.py
import math
from etorobot.backtest.metrics import compute_metrics


def test_total_return_and_drawdown():
    m = compute_metrics(equity_curve=[100, 110, 90, 120], trade_pnls=[])
    assert m["total_return"] == 0.20  # (120-100)/100
    assert m["max_drawdown"] == (110 - 90) / 110  # peak 110 -> trough 90


def test_win_rate_and_trades():
    m = compute_metrics(equity_curve=[100, 120], trade_pnls=[10, -5, 20])
    assert m["num_trades"] == 3
    assert m["win_rate"] == 2 / 3


def test_empty_curve_is_safe():
    m = compute_metrics(equity_curve=[], trade_pnls=[])
    assert m["total_return"] == 0.0 and m["num_trades"] == 0
