# src/etorobot/backtest/metrics.py
from __future__ import annotations

import statistics


def compute_metrics(equity_curve: list[float],
                    trade_pnls: list[float]) -> dict:
    if not equity_curve:
        total_return = 0.0
        max_dd = 0.0
        sharpe = 0.0
    else:
        total_return = (equity_curve[-1] - equity_curve[0]) / equity_curve[0]
        peak = equity_curve[0]
        max_dd = 0.0
        for v in equity_curve:
            peak = max(peak, v)
            max_dd = max(max_dd, (peak - v) / peak)
        rets = [(equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
                for i in range(1, len(equity_curve))]
        sharpe = (statistics.mean(rets) / statistics.pstdev(rets)
                  if len(rets) > 1 and statistics.pstdev(rets) > 0 else 0.0)

    wins = sum(1 for p in trade_pnls if p > 0)
    return {
        "total_return": total_return,
        "max_drawdown": max_dd,
        "sharpe": sharpe,
        "num_trades": len(trade_pnls),
        "win_rate": wins / len(trade_pnls) if trade_pnls else 0.0,
    }
