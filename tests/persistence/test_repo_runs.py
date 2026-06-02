# tests/persistence/test_repo_runs.py
from sqlalchemy import create_engine, text

from etorobot.persistence.repo import Repository


def test_create_run_starts_running():
    repo = Repository("sqlite:///:memory:")
    run_id = repo.create_run(mode="backtest", env="demo",
                             strategy="sma_crossover", params={"fast": 2},
                             timeframe="FiveMinutes", instruments="BTC",
                             starting_cash=1000.0)
    row = repo.get_run_row(run_id)
    assert row["status"] == "running"
    assert row["started_at"] is not None
    assert row["ended_at"] is None
    assert row["params"] == {"fast": 2}


def test_finish_run_sets_status_and_is_idempotent():
    repo = Repository("sqlite:///:memory:")
    run_id = repo.create_run(mode="live", env="demo", strategy="s",
                             params={}, timeframe="OneHour",
                             instruments="ETH", starting_cash=0.0)
    repo.finish_run(run_id, status="finished")
    row = repo.get_run_row(run_id)
    assert row["status"] == "finished"
    assert row["ended_at"] is not None
    repo.finish_run(run_id, status="finished")  # second call must not raise
    assert repo.get_run_row(run_id)["status"] == "finished"


def test_wal_enabled_on_file_db(tmp_path):
    db = tmp_path / "t.db"
    repo = Repository(f"sqlite:///{db}")
    with repo._engine.connect() as c:
        mode = c.execute(text("PRAGMA journal_mode")).scalar()
    assert mode.lower() == "wal"


from datetime import datetime as _dt, timezone as _tz

from etorobot.core.events import FillEvent, Signal
from etorobot.core.types import Direction, Transaction


def _ts():
    return _dt(2026, 1, 1, tzinfo=_tz.utc)


def test_record_methods_stamp_run_id():
    repo = Repository("sqlite:///:memory:")
    run_id = repo.create_run(mode="backtest", env="demo", strategy="s",
                             params={}, timeframe="OneHour",
                             instruments="BTC", starting_cash=1000.0)
    repo.record_signal(Signal("BTC", 100000, Direction.BUY, _ts()),
                       accepted=True, run_id=run_id)
    repo.record_fill(FillEvent("BTC", 100000, "open", Transaction.BUY,
                               500.0, 1.0, 500.0, 0.5, "p1", _ts()),
                     run_id=run_id)
    repo.record_equity(_ts(), 1000.0, 500.0, run_id=run_id)
    assert [s["id"] for s in repo.run_signals(run_id)]  # non-empty
