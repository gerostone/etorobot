# tests/persistence/test_repo_reads.py
from datetime import datetime, timedelta, timezone

from etorobot.core.events import FillEvent, Signal
from etorobot.core.types import Direction, Transaction
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


def test_reads_filter_by_run_and_isolate():
    repo = Repository("sqlite:///:memory:")
    a = repo.create_run(mode="backtest", env="demo", strategy="s", params={},
                        timeframe="OneHour", instruments="BTC",
                        starting_cash=1000.0)
    b = repo.create_run(mode="backtest", env="demo", strategy="s", params={},
                        timeframe="OneHour", instruments="ETH",
                        starting_cash=1000.0)
    _seed(repo, a)
    assert len(repo.run_signals(a)) == 1
    assert len(repo.run_fills(a)) == 2
    assert len(repo.run_equity(a)) == 2
    assert repo.run_trade_pnls(a) == [20.0]
    assert repo.run_signals(b) == []          # isolated
    assert repo.run_fills(b) == []


def test_run_signals_after_id_is_incremental():
    repo = Repository("sqlite:///:memory:")
    a = repo.create_run(mode="live", env="demo", strategy="s", params={},
                        timeframe="OneHour", instruments="BTC",
                        starting_cash=0.0)
    repo.record_signal(Signal("BTC", 1, Direction.BUY, _ts(0)),
                       accepted=True, run_id=a)
    first = repo.run_signals(a)
    assert len(first) == 1
    last_id = first[0]["id"]
    repo.record_signal(Signal("BTC", 1, Direction.CLOSE, _ts(1)),
                       accepted=True, run_id=a)
    nxt = repo.run_signals(a, after_id=last_id)
    assert len(nxt) == 1 and nxt[0]["direction"] == "CLOSE"


def test_list_run_rows_newest_first_and_last_activity():
    repo = Repository("sqlite:///:memory:")
    a = repo.create_run(mode="live", env="demo", strategy="s", params={},
                        timeframe="OneHour", instruments="BTC",
                        starting_cash=0.0)
    _seed(repo, a)
    rows = repo.list_run_rows()
    assert rows[0]["id"] == a
    assert repo.run_last_activity(a) is not None
    assert repo.run_last_activity(99999) is None
