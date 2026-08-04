# tests/dashboard/test_sse.py
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from etorobot.core.events import FillEvent, Signal
from etorobot.core.types import Direction, Transaction
from etorobot.dashboard.app import create_app
from etorobot.persistence.repo import Repository


def _ts():
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_stream_emits_typed_events_then_closes(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'd.db'}"
    repo = Repository(db_url)
    run_id = repo.create_run(mode="backtest", env="demo", strategy="s",
                             params={}, timeframe="OneMinute",
                             instruments="BTC", starting_cash=1000.0)
    repo.record_signal(Signal("BTC", 1, Direction.BUY, _ts()),
                       accepted=True, run_id=run_id)
    repo.record_fill(FillEvent("BTC", 1, "open", Transaction.BUY, 100.0, 1.0,
                               100.0, 0.0, "p1", _ts()), run_id=run_id)
    repo.finish_run(run_id, "finished")  # already closed -> stream terminates

    client = TestClient(create_app(db_url, token=None, poll_interval=0.01))
    with client.stream("GET", f"/api/runs/{run_id}/stream") as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())
    assert "event: signal" in body
    assert "event: fill" in body
    assert "event: run_status" in body
    assert '"status": "finished"' in body
