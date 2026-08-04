# src/etorobot/dashboard/reads.py
from __future__ import annotations

from datetime import datetime, timezone

from etorobot.backtest.metrics import compute_metrics
from etorobot.feeds.live import interval_seconds
from etorobot.persistence.repo import Repository


def _as_utc(dt: datetime) -> datetime:
    # SQLite returns naive datetimes; the framework stores everything in UTC,
    # so attach UTC to keep aware/naive arithmetic from blowing up.
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _is_stale(repo: Repository, run: dict, now: datetime) -> bool:
    if run["status"] != "running" or run["mode"] != "live":
        return False
    last = repo.run_last_activity(run["id"])
    if last is None:
        return False
    last_dt = _as_utc(datetime.fromisoformat(last))
    threshold = 3 * interval_seconds(run["timeframe"])
    return (_as_utc(now) - last_dt).total_seconds() > threshold


def build_run_list(repo: Repository, now: datetime) -> list[dict]:
    out: list[dict] = []
    for run in repo.list_run_rows():
        equity = [e["equity"] for e in repo.run_equity(run["id"])]
        metrics = compute_metrics(equity, repo.run_trade_pnls(run["id"]))
        row = dict(run)
        row["num_trades"] = metrics["num_trades"]
        row["total_return"] = metrics["total_return"]
        row["stale"] = _is_stale(repo, run, now)
        out.append(row)
    return out


def build_run_report(repo: Repository, run_id: int,
                     now: datetime) -> dict | None:
    run = repo.get_run_row(run_id)
    if run is None:
        return None
    equity = repo.run_equity(run_id)
    metrics = compute_metrics([e["equity"] for e in equity],
                              repo.run_trade_pnls(run_id))
    run = dict(run)
    run["stale"] = _is_stale(repo, run, now)
    return {
        "run": run,
        "metrics": metrics,
        "equity": equity,
        "fills": repo.run_fills(run_id),
        "signals": repo.run_signals(run_id),
    }
