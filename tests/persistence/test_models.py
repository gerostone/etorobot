# tests/persistence/test_models.py
from sqlalchemy import create_engine, inspect

from etorobot.persistence.models import Base


def test_schema_has_runs_table_and_run_id_columns():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert "runs" in tables
    for table in ("signals", "fills", "equity_snapshots"):
        cols = {c["name"] for c in insp.get_columns(table)}
        assert "run_id" in cols, f"{table} missing run_id"
    run_cols = {c["name"] for c in insp.get_columns("runs")}
    assert {"id", "mode", "env", "strategy", "params", "timeframe",
            "instruments", "started_at", "ended_at", "status",
            "starting_cash"} <= run_cols
