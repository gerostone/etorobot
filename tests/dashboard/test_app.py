# tests/dashboard/test_app.py
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from etorobot.core.events import FillEvent, Signal
from etorobot.core.types import Direction, Transaction
from etorobot.dashboard.app import create_app
from etorobot.persistence.repo import Repository


def _ts():
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _seed_db(db_url):
    repo = Repository(db_url)
    run_id = repo.create_run(mode="backtest", env="demo", strategy="s",
                             params={}, timeframe="OneHour",
                             instruments="BTC", starting_cash=1000.0)
    repo.finish_run(run_id, "finished")
    repo.record_signal(Signal("BTC", 1, Direction.BUY, _ts()),
                       accepted=True, run_id=run_id)
    repo.record_fill(FillEvent("BTC", 1, "open", Transaction.BUY, 100.0, 1.0,
                               100.0, 0.0, "p1", _ts()), run_id=run_id)
    repo.record_equity(_ts(), 1000.0, 900.0, run_id=run_id)
    return run_id


def test_list_and_report_endpoints(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'd.db'}"
    run_id = _seed_db(db_url)
    client = TestClient(create_app(db_url, token=None))

    runs = client.get("/api/runs")
    assert runs.status_code == 200
    body = runs.json()
    assert body[0]["id"] == run_id and "num_trades" in body[0]

    report = client.get(f"/api/runs/{run_id}")
    assert report.status_code == 200
    rep = report.json()
    assert rep["run"]["id"] == run_id
    assert rep["metrics"]["num_trades"] == 0  # open with no close yet
    assert len(rep["signals"]) == 1


def test_missing_run_is_404(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'd.db'}"
    _seed_db(db_url)
    client = TestClient(create_app(db_url, token=None))
    assert client.get("/api/runs/9999").status_code == 404


def test_auth_enforced_on_api(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'd.db'}"
    _seed_db(db_url)
    client = TestClient(create_app(db_url, token="s3cret"))
    assert client.get("/api/runs").status_code == 401
    assert client.get("/api/runs?token=s3cret").status_code == 200
