# tests/dashboard/test_reads.py
from datetime import datetime, timedelta, timezone

from etorobot.core.events import FillEvent, Signal
from etorobot.core.types import Direction, Transaction
from etorobot.dashboard.reads import build_run_list, build_run_report
from etorobot.persistence.repo import Repository


def _ts(i=0):
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=i)


def _seed(repo, run_id):
    repo.record_signal(Signal("BTC", 1, Direction.BUY, _ts(0)),
                       accepted=True, run_id=run_id)
    repo.record_fill(FillEvent("BTC", 1, "open", Transaction.BUY,
                               100.0, 1.0, 100.0, 0.0, "p1", _ts(1)),
                     run_id=run_id)
    repo.record_fill(FillEvent("BTC", 1, "close", Transaction.SELL,
                               120.0, 1.0, 120.0, 0.0, "p1", _ts(2)),
                     run_id=run_id)
    repo.record_equity(_ts(1), 1000.0, 900.0, run_id=run_id)
    repo.record_equity(_ts(2), 1020.0, 1020.0, run_id=run_id)


def test_build_run_report_has_metrics_and_sections():
    repo = Repository("sqlite:///:memory:")
    run_id = repo.create_run(mode="backtest", env="demo", strategy="s",
                             params={}, timeframe="OneHour",
                             instruments="BTC", starting_cash=1000.0)
    repo.finish_run(run_id, "finished")
    _seed(repo, run_id)
    report = build_run_report(repo, run_id, now=_ts(3))
    assert report["run"]["id"] == run_id
    assert report["metrics"]["num_trades"] == 1
    assert report["metrics"]["win_rate"] == 1.0
    assert len(report["equity"]) == 2
    assert len(report["fills"]) == 2
    assert len(report["signals"]) == 1
    assert report["run"]["stale"] is False


def test_build_run_report_missing_returns_none():
    repo = Repository("sqlite:///:memory:")
    assert build_run_report(repo, 999, now=_ts(0)) is None


def test_build_run_list_marks_stale_live_run():
    repo = Repository("sqlite:///:memory:")
    run_id = repo.create_run(mode="live", env="demo", strategy="s",
                             params={}, timeframe="OneMinute",
                             instruments="BTC", starting_cash=0.0)
    _seed(repo, run_id)   # last activity at _ts(2)
    # now is far beyond 3 * 60s after last activity -> stale
    rows = build_run_list(repo, now=_ts(60))
    assert rows[0]["stale"] is True
    assert rows[0]["num_trades"] == 1
