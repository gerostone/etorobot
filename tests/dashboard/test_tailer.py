# tests/dashboard/test_tailer.py
from datetime import datetime, timedelta, timezone

from etorobot.core.events import FillEvent, Signal
from etorobot.core.types import Direction, Transaction
from etorobot.dashboard.tailer import DbTailer
from etorobot.persistence.repo import Repository


def _ts(i=0):
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=i)


def test_first_poll_returns_all_then_only_new():
    repo = Repository("sqlite:///:memory:")
    run_id = repo.create_run(mode="live", env="demo", strategy="s",
                             params={}, timeframe="OneMinute",
                             instruments="BTC", starting_cash=0.0)
    repo.record_signal(Signal("BTC", 1, Direction.BUY, _ts(0)),
                       accepted=True, run_id=run_id)
    repo.record_fill(FillEvent("BTC", 1, "open", Transaction.BUY, 100.0, 1.0,
                               100.0, 0.0, "p1", _ts(1)), run_id=run_id)
    tailer = DbTailer(repo, run_id)
    first = tailer.poll()
    types = sorted(e["type"] for e in first)
    assert types == ["fill", "signal"]
    assert tailer.poll() == []                      # cursor advanced
    repo.record_equity(_ts(2), 1000.0, 1000.0, run_id=run_id)
    nxt = tailer.poll()
    assert len(nxt) == 1 and nxt[0]["type"] == "equity"


def test_closed_reflects_run_status():
    repo = Repository("sqlite:///:memory:")
    run_id = repo.create_run(mode="live", env="demo", strategy="s",
                             params={}, timeframe="OneMinute",
                             instruments="BTC", starting_cash=0.0)
    tailer = DbTailer(repo, run_id)
    assert tailer.closed() is False
    repo.finish_run(run_id, "finished")
    assert tailer.closed() is True
    assert tailer.run_status() == "finished"
