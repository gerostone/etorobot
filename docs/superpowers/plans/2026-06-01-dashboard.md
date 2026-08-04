# Dashboard de Ejecuciones — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only web dashboard that follows bot runs (live and backtest) in real time and serves a per-run report (metrics, equity curve, trades, signals).

**Architecture:** A separate FastAPI/uvicorn process on the same host reads the bot's SQLite DB (opened in WAL mode for concurrent reads), tails it on a ~1.5s poll, and pushes new rows to browsers via Server-Sent Events. The bot is changed only to register a `run` row at start/finish and stamp `run_id` on every persisted signal/fill/equity snapshot; backtests are now persisted durably instead of to an in-memory DB. Auth is a single shared token; TLS is terminated by a reverse proxy in front.

**Tech Stack:** Python 3.11+, FastAPI + uvicorn, Starlette `TestClient` (via httpx) for tests, SQLAlchemy 2.0, pytest (`asyncio_mode="auto"`), Chart.js (CDN) for the equity curve.

**Spec:** `docs/superpowers/specs/2026-06-01-dashboard-design.md`

**Conventions for this plan:**
- Run tests with `.venv/bin/pytest` and Python with `.venv/bin/python` (project virtualenv).
- Do not commit `*.db` or `.env` (already git-ignored).

---

### Task 1: Add FastAPI + uvicorn dependencies

**Files:**
- Modify: `pyproject.toml:6-18`

- [ ] **Step 1: Add runtime deps**

In `pyproject.toml`, change the `dependencies` list to add FastAPI and uvicorn:

```toml
dependencies = [
    "httpx>=0.27",
    "websockets>=12.0",
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "pyyaml>=6.0",
    "pandas>=2.2",
    "pandas-ta>=0.3.14b0",
    "sqlalchemy>=2.0",
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
]
```

(The dev extra already includes `respx`; `httpx` is a runtime dep, so Starlette's `TestClient` works without further changes.)

- [ ] **Step 2: Install**

Run: `.venv/bin/pip install -e ".[dev]"`
Expected: installs `fastapi`, `starlette`, `uvicorn` (and deps) with no errors.

- [ ] **Step 3: Verify imports**

Run: `.venv/bin/python -c "import fastapi, uvicorn, starlette.testclient; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build: add fastapi + uvicorn for the dashboard"
```

---

### Task 2: Add RunRow model and run_id columns

**Files:**
- Modify: `src/etorobot/persistence/models.py`
- Test: `tests/persistence/test_models.py` (create)

> **Migration note:** `create_all` does NOT add columns to tables that already exist. After this task, delete any pre-existing `bot_*.db` files (git-ignored demo data) so the new schema is created fresh: `rm -f bot_demo.db bot_real.db`.

- [ ] **Step 1: Write the failing test**

Create `tests/persistence/test_models.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/persistence/test_models.py -v`
Expected: FAIL — `AssertionError` (no `runs` table / missing `run_id`).

- [ ] **Step 3: Implement the model changes**

Replace the contents of `src/etorobot/persistence/models.py` with:

```python
# src/etorobot/persistence/models.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RunRow(Base):
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String)            # "live" | "backtest"
    env: Mapped[str] = mapped_column(String)             # "demo" | "real"
    strategy: Mapped[str] = mapped_column(String)
    params: Mapped[str] = mapped_column(String)          # JSON-encoded dict
    timeframe: Mapped[str] = mapped_column(String)
    instruments: Mapped[str] = mapped_column(String)     # comma-joined symbols
    started_at: Mapped[datetime] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String)          # running|finished|error
    starting_cash: Mapped[float] = mapped_column(Float)


class SignalRow(Base):
    __tablename__ = "signals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    symbol: Mapped[str] = mapped_column(String)
    instrument_id: Mapped[int] = mapped_column(Integer)
    direction: Mapped[str] = mapped_column(String)
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    accepted: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)


class FillRow(Base):
    __tablename__ = "fills"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    symbol: Mapped[str] = mapped_column(String)
    instrument_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String)
    transaction: Mapped[str] = mapped_column(String)
    price: Mapped[float] = mapped_column(Float)
    units: Mapped[float] = mapped_column(Float)
    amount: Mapped[float] = mapped_column(Float)
    commission: Mapped[float] = mapped_column(Float)
    position_id: Mapped[str] = mapped_column(String)
    timestamp: Mapped[datetime] = mapped_column(DateTime)


class EquityRow(Base):
    __tablename__ = "equity_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/persistence/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/etorobot/persistence/models.py tests/persistence/test_models.py
git commit -m "feat(persistence): add runs table and run_id columns"
```

---

### Task 3: WAL mode + create_run / finish_run

**Files:**
- Modify: `src/etorobot/persistence/repo.py`
- Test: `tests/persistence/test_repo_runs.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/persistence/test_repo_runs.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/persistence/test_repo_runs.py -v`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'create_run'`.

- [ ] **Step 3: Implement WAL + run lifecycle**

Edit `src/etorobot/persistence/repo.py`. Replace the imports block and `__init__`, and add the new methods + a module-level helper.

Replace lines 1-16 (imports through `__init__`) with:

```python
# src/etorobot/persistence/repo.py
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from etorobot.core.events import FillEvent, Signal
from etorobot.persistence.models import (
    Base, EquityRow, FillRow, RunRow, SignalRow)


def _run_dict(r: RunRow) -> dict:
    return {
        "id": r.id, "mode": r.mode, "env": r.env, "strategy": r.strategy,
        "params": json.loads(r.params) if r.params else {},
        "timeframe": r.timeframe, "instruments": r.instruments,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "ended_at": r.ended_at.isoformat() if r.ended_at else None,
        "status": r.status, "starting_cash": r.starting_cash,
    }


class Repository:
    def __init__(self, url: str = "sqlite:///bot_demo.db") -> None:
        self._engine = create_engine(url)

        @event.listens_for(self._engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

        Base.metadata.create_all(self._engine)

    def create_run(self, *, mode: str, env: str, strategy: str,
                   params: dict, timeframe: str, instruments: str,
                   starting_cash: float) -> int:
        with Session(self._engine) as s:
            row = RunRow(
                mode=mode, env=env, strategy=strategy,
                params=json.dumps(params), timeframe=timeframe,
                instruments=instruments,
                started_at=datetime.now(timezone.utc), ended_at=None,
                status="running", starting_cash=starting_cash)
            s.add(row)
            s.commit()
            return row.id

    def finish_run(self, run_id: int, status: str) -> None:
        with Session(self._engine) as s:
            row = s.get(RunRow, run_id)
            if row is None:
                return
            row.status = status
            row.ended_at = datetime.now(timezone.utc)
            s.commit()

    def get_run_row(self, run_id: int) -> dict | None:
        with Session(self._engine) as s:
            row = s.get(RunRow, run_id)
            return _run_dict(row) if row is not None else None
```

(Note: `:memory:` reports `journal_mode` as `memory`, not `wal` — that is expected and why the WAL test uses a file DB.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/persistence/test_repo_runs.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the existing repo test to confirm no regression**

Run: `.venv/bin/pytest tests/persistence/ -v`
Expected: PASS (existing `test_repo.py` still green).

- [ ] **Step 6: Commit**

```bash
git add src/etorobot/persistence/repo.py tests/persistence/test_repo_runs.py
git commit -m "feat(persistence): WAL mode + create_run/finish_run/get_run_row"
```

---

### Task 4: Stamp run_id on record_signal / record_fill / record_equity

**Files:**
- Modify: `src/etorobot/persistence/repo.py`
- Test: `tests/persistence/test_repo_runs.py` (extend)

- [ ] **Step 1: Add the failing test**

Append to `tests/persistence/test_repo_runs.py`:

```python
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
```

(`run_signals` is implemented in Task 5; this test will pass once both Task 4 and Task 5 land. Run it at the end of Task 5.)

- [ ] **Step 2: Implement run_id params**

In `src/etorobot/persistence/repo.py`, update the three `record_*` methods to accept and store `run_id`:

```python
    def record_signal(self, signal: Signal, accepted: bool,
                      reason: str | None = None,
                      run_id: int | None = None) -> None:
        with Session(self._engine) as s:
            s.add(SignalRow(
                run_id=run_id,
                symbol=signal.symbol, instrument_id=signal.instrument_id,
                direction=signal.direction.value, timestamp=signal.timestamp,
                accepted=accepted, reason=reason))
            s.commit()

    def record_fill(self, fill: FillEvent, run_id: int | None = None) -> None:
        with Session(self._engine) as s:
            s.add(FillRow(
                run_id=run_id,
                symbol=fill.symbol, instrument_id=fill.instrument_id,
                action=fill.action, transaction=fill.transaction.value,
                price=fill.price, units=fill.units, amount=fill.amount,
                commission=fill.commission, position_id=fill.position_id,
                timestamp=fill.timestamp))
            s.commit()

    def record_equity(self, timestamp: datetime, equity: float,
                      cash: float, run_id: int | None = None) -> None:
        with Session(self._engine) as s:
            s.add(EquityRow(run_id=run_id, timestamp=timestamp,
                            equity=equity, cash=cash))
            s.commit()
```

- [ ] **Step 3: Confirm existing repo test still passes**

Run: `.venv/bin/pytest tests/persistence/test_repo.py -v`
Expected: PASS (the `run_id` params default to `None`, preserving old behavior).

- [ ] **Step 4: Commit**

```bash
git add src/etorobot/persistence/repo.py tests/persistence/test_repo_runs.py
git commit -m "feat(persistence): record_* accept and stamp run_id"
```

---

### Task 5: Run-filtered read methods

**Files:**
- Modify: `src/etorobot/persistence/repo.py`
- Test: `tests/persistence/test_repo_reads.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/persistence/test_repo_reads.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/persistence/test_repo_reads.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'run_signals'`.

- [ ] **Step 3: Implement the read methods**

Append these methods to the `Repository` class in `src/etorobot/persistence/repo.py`:

```python
    def run_signals(self, run_id: int, after_id: int = 0) -> list[dict]:
        with Session(self._engine) as s:
            rows = s.scalars(
                select(SignalRow)
                .where(SignalRow.run_id == run_id, SignalRow.id > after_id)
                .order_by(SignalRow.id.asc())).all()
            return [{
                "id": r.id, "symbol": r.symbol,
                "instrument_id": r.instrument_id, "direction": r.direction,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "accepted": r.accepted, "reason": r.reason,
            } for r in rows]

    def run_fills(self, run_id: int, after_id: int = 0) -> list[dict]:
        with Session(self._engine) as s:
            rows = s.scalars(
                select(FillRow)
                .where(FillRow.run_id == run_id, FillRow.id > after_id)
                .order_by(FillRow.id.asc())).all()
            return [{
                "id": r.id, "symbol": r.symbol,
                "instrument_id": r.instrument_id, "action": r.action,
                "transaction": r.transaction, "price": r.price,
                "units": r.units, "amount": r.amount,
                "commission": r.commission, "position_id": r.position_id,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            } for r in rows]

    def run_equity(self, run_id: int, after_id: int = 0) -> list[dict]:
        with Session(self._engine) as s:
            rows = s.scalars(
                select(EquityRow)
                .where(EquityRow.run_id == run_id, EquityRow.id > after_id)
                .order_by(EquityRow.id.asc())).all()
            return [{
                "id": r.id,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "equity": r.equity, "cash": r.cash,
            } for r in rows]

    def run_trade_pnls(self, run_id: int) -> list[float]:
        with Session(self._engine) as s:
            fills = s.scalars(
                select(FillRow).where(FillRow.run_id == run_id)
                .order_by(FillRow.id.asc())).all()
        opens: dict[str, float] = {}
        pnls: list[float] = []
        for f in fills:
            if f.action == "open":
                opens[f.position_id] = f.amount
            elif f.action == "close" and f.position_id in opens:
                pnls.append(f.amount - opens.pop(f.position_id))
        return pnls

    def list_run_rows(self) -> list[dict]:
        with Session(self._engine) as s:
            rows = s.scalars(
                select(RunRow).order_by(RunRow.id.desc())).all()
            return [_run_dict(r) for r in rows]

    def run_last_activity(self, run_id: int) -> str | None:
        with Session(self._engine) as s:
            times = []
            for model in (SignalRow, FillRow, EquityRow):
                t = s.scalar(select(func.max(model.timestamp))
                             .where(model.run_id == run_id))
                if t is not None:
                    times.append(t)
        return max(times).isoformat() if times else None
```

- [ ] **Step 4: Run the read + run_id tests to verify they pass**

Run: `.venv/bin/pytest tests/persistence/ -v`
Expected: PASS (all persistence tests, including `test_record_methods_stamp_run_id` from Task 4).

- [ ] **Step 5: Commit**

```bash
git add src/etorobot/persistence/repo.py tests/persistence/test_repo_reads.py
git commit -m "feat(persistence): run-filtered read methods + last activity"
```

---

### Task 6: Thread run_id through the Engine

**Files:**
- Modify: `src/etorobot/core/engine.py:17-27`, `:72-91`
- Test: `tests/core/test_engine_run_id.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_engine_run_id.py`:

```python
# tests/core/test_engine_run_id.py
from datetime import datetime, timezone

from etorobot.core.engine import Engine
from etorobot.core.events import FillEvent, MarketEvent
from etorobot.core.types import Candle, Direction, Transaction
from etorobot.persistence.repo import Repository
from etorobot.strategies.base import BaseStrategy
from etorobot.core.events import Signal


class _AlwaysBuy(BaseStrategy):
    def on_market_event(self, event):
        c = event.candle
        return Signal(c.symbol, c.instrument_id, Direction.BUY, c.timestamp)


class _Feed:
    def __init__(self, events):
        self._events = events

    async def stream(self):
        for e in self._events:
            yield e


class _Risk:
    def evaluate(self, signal, portfolio, price, now):
        from etorobot.risk.manager import RiskDecision
        from etorobot.core.events import OrderEvent
        return RiskDecision(True, OrderEvent("open", signal.symbol,
                            signal.instrument_id, Transaction.BUY,
                            amount=100.0), None)


class _Portfolio:
    equity = 1000.0
    cash = 900.0


class _Broker:
    def on_market_event(self, event):
        pass

    async def get_portfolio(self):
        return _Portfolio()

    async def execute(self, order):
        return FillEvent("BTC", 1, "open", Transaction.BUY, 100.0, 1.0,
                         100.0, 0.0, "p1",
                         datetime(2026, 1, 1, tzinfo=timezone.utc))


class _Notifier:
    async def notify(self, kind, message):
        pass


async def test_engine_stamps_run_id():
    repo = Repository("sqlite:///:memory:")
    run_id = repo.create_run(mode="backtest", env="demo", strategy="s",
                             params={}, timeframe="OneHour",
                             instruments="BTC", starting_cash=1000.0)
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candle = Candle(1, "BTC", ts, 100.0, 100.0, 100.0, 100.0, 0.0)
    engine = Engine(feed=_Feed([MarketEvent(candle)]),
                    strategies={1: [_AlwaysBuy()]}, risk=_Risk(),
                    broker=_Broker(), repo=repo, notifier=_Notifier(),
                    run_id=run_id)
    await engine.run()
    assert len(repo.run_signals(run_id)) == 1
    assert len(repo.run_fills(run_id)) == 1
    assert len(repo.run_equity(run_id)) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/core/test_engine_run_id.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'run_id'`.

- [ ] **Step 3: Implement run_id on the Engine**

In `src/etorobot/core/engine.py`, update `__init__` to accept `run_id`:

```python
    def __init__(self, feed: DataFeed,
                 strategies: dict[int, list[BaseStrategy]],
                 risk: RiskManager, broker: Broker, repo: Repository,
                 notifier, run_id: int | None = None) -> None:
        self._feed = feed
        self._strategies = strategies
        self._risk = risk
        self._broker = broker
        self._repo = repo
        self._notifier = notifier
        self._run_id = run_id
```

Then in `_handle_signal`, pass `self._run_id` into each record call:

```python
        self._record(self._repo.record_signal, signal, decision.accepted,
                     decision.reason, self._run_id)
        if not decision.accepted:
            await self._notify(
                "rejected", f"{signal.symbol} {signal.direction.value} "
                            f"rejected: {decision.reason}")
            return
        fill = await self._broker.execute(decision.order)
        self._record(self._repo.record_fill, fill, self._run_id)
        portfolio = await self._broker.get_portfolio()
        self._record(self._repo.record_equity, event.candle.timestamp,
                     portfolio.equity, portfolio.cash, self._run_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/core/test_engine_run_id.py -v`
Expected: PASS.

- [ ] **Step 5: Confirm existing engine tests still pass**

Run: `.venv/bin/pytest tests/core/ -v`
Expected: PASS (no regressions; `run_id` defaults to `None`).

- [ ] **Step 6: Commit**

```bash
git add src/etorobot/core/engine.py tests/core/test_engine_run_id.py
git commit -m "feat(engine): thread run_id into persistence records"
```

---

### Task 7: Persist backtests durably (runner.py)

**Files:**
- Modify: `src/etorobot/backtest/runner.py`
- Test: `tests/backtest/test_runner_persist.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/backtest/test_runner_persist.py`:

```python
# tests/backtest/test_runner_persist.py
from datetime import datetime, timedelta, timezone

from etorobot.backtest.runner import run_backtest
from etorobot.config.settings import BacktestConfig, RiskConfig, StrategyConfig
from etorobot.core.types import Candle
from etorobot.persistence.repo import Repository


def _series():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    closes = [10, 9, 8, 9, 10, 11, 12, 11, 10, 8, 7, 9, 11, 13, 15]
    return [Candle(100000, "BTC", base + timedelta(minutes=i), p, p, p, p, 1.0)
            for i, p in enumerate(closes)]


async def test_run_backtest_persists_to_given_repo():
    repo = Repository("sqlite:///:memory:")
    run_id = repo.create_run(mode="backtest", env="demo",
                             strategy="sma_crossover",
                             params={"fast": 2, "slow": 3},
                             timeframe="OneMinute", instruments="BTC",
                             starting_cash=1000.0)
    metrics = await run_backtest(
        candles_by_instrument={100000: _series()},
        strategy=StrategyConfig(name="sma_crossover",
                                params={"fast": 2, "slow": 3}),
        risk=RiskConfig(position_size_pct=0.10, max_open_positions=3,
                        max_positions_per_instrument=1,
                        default_stop_loss_pct=0.02,
                        default_take_profit_pct=0.04,
                        daily_loss_limit_pct=0.9),
        backtest=BacktestConfig(commission_pct=0.0, slippage_pct=0.0,
                                fill_price="close"),
        starting_cash=1000.0, repo=repo, run_id=run_id)
    assert metrics["num_trades"] >= 1
    assert len(repo.run_fills(run_id)) >= 1   # persisted under the run
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/backtest/test_runner_persist.py -v`
Expected: FAIL — `TypeError: run_backtest() got an unexpected keyword argument 'repo'`.

- [ ] **Step 3: Implement optional repo/run_id**

Replace `src/etorobot/backtest/runner.py` with:

```python
# src/etorobot/backtest/runner.py
from __future__ import annotations

from etorobot.backtest.metrics import compute_metrics
from etorobot.brokers.simulated import SimulatedBroker
from etorobot.config.settings import BacktestConfig, RiskConfig, StrategyConfig
from etorobot.core.engine import Engine
from etorobot.core.types import Candle
from etorobot.feeds.historical import HistoricalFeed
from etorobot.notify.base import NullNotifier
from etorobot.persistence.repo import Repository
from etorobot.risk.manager import RiskManager
from etorobot.strategies.registry import build_strategy


async def run_backtest(candles_by_instrument: dict[int, list[Candle]],
                       strategy: StrategyConfig, risk: RiskConfig,
                       backtest: BacktestConfig,
                       starting_cash: float = 1000.0,
                       repo: Repository | None = None,
                       run_id: int | None = None) -> dict:
    all_candles: list[Candle] = []
    for candles in candles_by_instrument.values():
        all_candles.extend(candles)

    feed = HistoricalFeed(all_candles)
    broker = SimulatedBroker(starting_cash=starting_cash,
                             commission_pct=backtest.commission_pct,
                             slippage_pct=backtest.slippage_pct,
                             fill_price=backtest.fill_price)
    if repo is None:
        repo = Repository("sqlite:///:memory:")
    strategies = {iid: [build_strategy(strategy.name, strategy.params)]
                  for iid in candles_by_instrument}
    engine = Engine(feed=feed, strategies=strategies,
                    risk=RiskManager(risk), broker=broker, repo=repo,
                    notifier=NullNotifier(), run_id=run_id)
    await engine.run()
    if run_id is not None:
        equity = [e["equity"] for e in repo.run_equity(run_id)]
        return compute_metrics(equity, repo.run_trade_pnls(run_id))
    return compute_metrics(repo.equity_curve(), repo.trade_pnls())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/backtest/ -v`
Expected: PASS (new persist test + existing `test_runner.py` still green via the in-memory default).

- [ ] **Step 5: Commit**

```bash
git add src/etorobot/backtest/runner.py tests/backtest/test_runner_persist.py
git commit -m "feat(backtest): persist runs to a durable repo when given"
```

---

### Task 8: Wire run lifecycle into the CLI commands

**Files:**
- Modify: `src/etorobot/cli.py`
- Test: `tests/test_cli.py` (extend + adjust existing test)

- [ ] **Step 1: Update the existing test to use a temp DB and add a run-persistence test**

Replace `tests/test_cli.py` with:

```python
# tests/test_cli.py
from datetime import datetime, timezone, timedelta

from etorobot.config.settings import (
    AppConfig, Secrets, TelegramSecrets, InstrumentConfig, StrategyConfig,
    RiskConfig, BacktestConfig)
from etorobot.core.types import Candle
from etorobot.cli import do_backtest
from etorobot.persistence.repo import Repository


class FakeClient:
    async def resolve_instrument(self, symbol):
        return 100000

    async def get_candles(self, instrument_id, symbol, interval, count):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        closes = [10, 9, 8, 9, 10, 11, 12, 13, 14, 15]
        return [Candle(instrument_id, symbol, base + timedelta(minutes=i),
                       p, p, p, p, 1.0) for i, p in enumerate(closes)]

    async def __aenter__(self): return self
    async def __aexit__(self, *a): return None


def _config():
    return AppConfig(
        timeframe="FiveMinutes",
        instruments=[InstrumentConfig(symbol="BTC")],
        strategy=StrategyConfig(name="sma_crossover",
                                params={"fast": 2, "slow": 3}),
        risk=RiskConfig(position_size_pct=0.10, max_open_positions=3,
                        max_positions_per_instrument=1,
                        default_stop_loss_pct=0.02, default_take_profit_pct=0.04,
                        daily_loss_limit_pct=0.9),
        backtest=BacktestConfig(),
        secrets=Secrets(api_key="ak", user_key="uk", env="demo"),
        telegram=TelegramSecrets())


async def test_do_backtest_returns_metrics(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'bt.db'}"
    metrics = await do_backtest(_config(), client=FakeClient(),
                                candles_count=10, db_url=db_url)
    assert "total_return" in metrics and "num_trades" in metrics


async def test_do_backtest_records_a_finished_run(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'bt.db'}"
    await do_backtest(_config(), client=FakeClient(), candles_count=10,
                      db_url=db_url)
    repo = Repository(db_url)
    runs = repo.list_run_rows()
    assert len(runs) == 1
    assert runs[0]["mode"] == "backtest"
    assert runs[0]["status"] == "finished"
    assert runs[0]["ended_at"] is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL — `TypeError: do_backtest() got an unexpected keyword argument 'db_url'`.

- [ ] **Step 3: Implement the run lifecycle in `do_run` and `do_backtest`**

In `src/etorobot/cli.py`, replace `do_backtest` and `do_run` with:

```python
async def do_backtest(config: AppConfig, client, candles_count: int = 500,
                      db_url: str | None = None) -> dict:
    candles_by_instrument = {}
    symbols: dict[int, str] = {}
    async with client:
        for inst in config.instruments:
            iid = await client.resolve_instrument(inst.symbol)
            symbols[iid] = inst.symbol
            candles_by_instrument[iid] = await client.get_candles(
                iid, inst.symbol, config.timeframe, count=candles_count)
    db_url = db_url or f"sqlite:///bot_{config.secrets.env}.db"
    repo = Repository(db_url)
    run_id = repo.create_run(
        mode="backtest", env=config.secrets.env,
        strategy=config.strategy.name, params=config.strategy.params,
        timeframe=config.timeframe,
        instruments=",".join(symbols.values()), starting_cash=1000.0)
    status = "finished"
    try:
        return await run_backtest(candles_by_instrument, config.strategy,
                                  config.risk, config.backtest,
                                  repo=repo, run_id=run_id)
    except Exception:
        status = "error"
        raise
    finally:
        repo.finish_run(run_id, status)


async def do_run(config: AppConfig, client) -> None:
    instruments: dict[int, str] = {}
    async with client:
        for inst in config.instruments:
            instruments[await client.resolve_instrument(inst.symbol)] = inst.symbol
    feed = LiveFeed(config.secrets.api_key, config.secrets.user_key,
                    instruments, config.timeframe)
    broker = EtoroBroker(_make_client(config))
    repo = Repository(f"sqlite:///bot_{config.secrets.env}.db")
    run_id = repo.create_run(
        mode="live", env=config.secrets.env,
        strategy=config.strategy.name, params=config.strategy.params,
        timeframe=config.timeframe,
        instruments=",".join(instruments.values()), starting_cash=0.0)
    strategies = {iid: [build_strategy(config.strategy.name,
                                       config.strategy.params)]
                  for iid in instruments}
    engine = Engine(feed=feed, strategies=strategies,
                    risk=RiskManager(config.risk), broker=broker, repo=repo,
                    notifier=_make_notifier(config), run_id=run_id)
    status = "finished"
    try:
        await engine.run()
    except Exception:
        status = "error"
        raise
    finally:
        repo.finish_run(run_id, status)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/etorobot/cli.py tests/test_cli.py
git commit -m "feat(cli): register run lifecycle for run/backtest, durable backtest db"
```

---

### Task 9: DashboardSecrets config

**Files:**
- Modify: `src/etorobot/config/settings.py`
- Test: `tests/config/test_dashboard_secrets.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/config/test_dashboard_secrets.py`:

```python
# tests/config/test_dashboard_secrets.py
from etorobot.config.settings import DashboardSecrets


def test_token_defaults_to_none(monkeypatch):
    monkeypatch.delenv("DASHBOARD_TOKEN", raising=False)
    assert DashboardSecrets(_env_file=None).token is None


def test_token_read_from_env(monkeypatch):
    monkeypatch.setenv("DASHBOARD_TOKEN", "s3cret")
    assert DashboardSecrets(_env_file=None).token == "s3cret"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/config/test_dashboard_secrets.py -v`
Expected: FAIL — `ImportError: cannot import name 'DashboardSecrets'`.

- [ ] **Step 3: Implement `DashboardSecrets`**

In `src/etorobot/config/settings.py`, add after the `TelegramSecrets` class (around line 25):

```python
class DashboardSecrets(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DASHBOARD_", env_file=".env",
                                      extra="ignore")
    token: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/config/test_dashboard_secrets.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/etorobot/config/settings.py tests/config/test_dashboard_secrets.py
git commit -m "feat(config): DashboardSecrets (DASHBOARD_TOKEN)"
```

---

### Task 10: Dashboard package + read/report layer (`reads.py`)

**Files:**
- Create: `src/etorobot/dashboard/__init__.py`
- Create: `src/etorobot/dashboard/reads.py`
- Create: `tests/dashboard/__init__.py`
- Test: `tests/dashboard/test_reads.py` (create)

- [ ] **Step 1: Create empty package markers**

Create `src/etorobot/dashboard/__init__.py` (empty file).
Create `tests/dashboard/__init__.py` (empty file).

- [ ] **Step 2: Write the failing test**

Create `tests/dashboard/test_reads.py`:

```python
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
```

- [ ] **Step 3: Implement `reads.py`**

Create `src/etorobot/dashboard/reads.py`:

```python
# src/etorobot/dashboard/reads.py
from __future__ import annotations

from datetime import datetime

from etorobot.backtest.metrics import compute_metrics
from etorobot.feeds.live import interval_seconds
from etorobot.persistence.repo import Repository


def _is_stale(repo: Repository, run: dict, now: datetime) -> bool:
    if run["status"] != "running" or run["mode"] != "live":
        return False
    last = repo.run_last_activity(run["id"])
    if last is None:
        return False
    last_dt = datetime.fromisoformat(last)
    threshold = 3 * interval_seconds(run["timeframe"])
    return (now - last_dt).total_seconds() > threshold


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/dashboard/test_reads.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/etorobot/dashboard/__init__.py src/etorobot/dashboard/reads.py \
        tests/dashboard/__init__.py tests/dashboard/test_reads.py
git commit -m "feat(dashboard): read/report layer (build_run_list/report)"
```

---

### Task 11: Incremental DB tailer (`tailer.py`)

**Files:**
- Create: `src/etorobot/dashboard/tailer.py`
- Test: `tests/dashboard/test_tailer.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/dashboard/test_tailer.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/dashboard/test_tailer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'etorobot.dashboard.tailer'`.

- [ ] **Step 3: Implement `tailer.py`**

Create `src/etorobot/dashboard/tailer.py`:

```python
# src/etorobot/dashboard/tailer.py
from __future__ import annotations

from etorobot.persistence.repo import Repository


class DbTailer:
    """Polls one run's signals/fills/equity, emitting only new rows by id."""

    def __init__(self, repo: Repository, run_id: int) -> None:
        self._repo = repo
        self._run_id = run_id
        self._cursor = {"signal": 0, "fill": 0, "equity": 0}

    def poll(self) -> list[dict]:
        events: list[dict] = []
        for sig in self._repo.run_signals(self._run_id,
                                          after_id=self._cursor["signal"]):
            self._cursor["signal"] = sig["id"]
            events.append({"type": "signal", "data": sig})
        for fill in self._repo.run_fills(self._run_id,
                                         after_id=self._cursor["fill"]):
            self._cursor["fill"] = fill["id"]
            events.append({"type": "fill", "data": fill})
        for eq in self._repo.run_equity(self._run_id,
                                        after_id=self._cursor["equity"]):
            self._cursor["equity"] = eq["id"]
            events.append({"type": "equity", "data": eq})
        return events

    def run_status(self) -> str | None:
        run = self._repo.get_run_row(self._run_id)
        return run["status"] if run is not None else None

    def closed(self) -> bool:
        return self.run_status() != "running"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/dashboard/test_tailer.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/etorobot/dashboard/tailer.py tests/dashboard/test_tailer.py
git commit -m "feat(dashboard): incremental DbTailer"
```

---

### Task 12: Token auth dependency (`auth.py`)

**Files:**
- Create: `src/etorobot/dashboard/auth.py`
- Test: `tests/dashboard/test_auth.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/dashboard/test_auth.py`:

```python
# tests/dashboard/test_auth.py
import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from etorobot.dashboard.auth import make_auth


def _app(token):
    app = FastAPI()
    auth = make_auth(token)

    @app.get("/ping")
    async def ping(_=Depends(auth)):
        return {"ok": True}

    return TestClient(app, raise_server_exceptions=True)


def test_no_token_configured_allows_all():
    client = _app(None)
    assert client.get("/ping").status_code == 200


def test_missing_token_is_401():
    client = _app("s3cret")
    assert client.get("/ping").status_code == 401


def test_bearer_header_accepted():
    client = _app("s3cret")
    r = client.get("/ping", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200


def test_query_param_accepted():
    client = _app("s3cret")
    assert client.get("/ping?token=s3cret").status_code == 200


def test_cookie_accepted():
    client = _app("s3cret")
    client.cookies.set("dashboard_token", "s3cret")
    assert client.get("/ping").status_code == 200


def test_wrong_token_is_401():
    client = _app("s3cret")
    assert client.get("/ping?token=nope").status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/dashboard/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'etorobot.dashboard.auth'`.

- [ ] **Step 3: Implement `auth.py`**

Create `src/etorobot/dashboard/auth.py`:

```python
# src/etorobot/dashboard/auth.py
from __future__ import annotations

import secrets as _secrets
from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:]
    q = request.query_params.get("token")
    if q:
        return q
    return request.cookies.get("dashboard_token")


def make_auth(token: str | None) -> Callable[[Request], Awaitable[None]]:
    """Build a FastAPI dependency enforcing a single shared token.

    If ``token`` is None (not configured), auth is disabled — intended only
    for local development. Production deployments MUST set DASHBOARD_TOKEN.
    """

    async def require_token(request: Request) -> None:
        if token is None:
            return
        provided = _extract_token(request)
        if provided is None or not _secrets.compare_digest(provided, token):
            raise HTTPException(status_code=401, detail="unauthorized")

    return require_token
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/dashboard/test_auth.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add src/etorobot/dashboard/auth.py tests/dashboard/test_auth.py
git commit -m "feat(dashboard): single-token auth (header/query/cookie)"
```

---

### Task 13: FastAPI app — JSON endpoints + static mount (`app.py`)

**Files:**
- Create: `src/etorobot/dashboard/app.py`
- Create: `src/etorobot/dashboard/static/.gitkeep` (placeholder so the mount dir exists; replaced in Task 15)
- Test: `tests/dashboard/test_app.py` (create)

- [ ] **Step 1: Create the static dir placeholder**

Create `src/etorobot/dashboard/static/.gitkeep` (empty file).

- [ ] **Step 2: Write the failing test**

Create `tests/dashboard/test_app.py`:

```python
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
```

- [ ] **Step 3: Implement `app.py`**

Create `src/etorobot/dashboard/app.py`:

```python
# src/etorobot/dashboard/app.py
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from etorobot.dashboard.auth import make_auth
from etorobot.dashboard.reads import build_run_list, build_run_report
from etorobot.dashboard.sse import event_stream
from etorobot.dashboard.tailer import DbTailer
from etorobot.persistence.repo import Repository

_STATIC_DIR = Path(__file__).parent / "static"


def create_app(db_url: str, token: str | None = None,
               poll_interval: float = 1.5) -> FastAPI:
    app = FastAPI(title="etorobot dashboard")
    repo = Repository(db_url)
    auth = make_auth(token)

    @app.exception_handler(Exception)
    async def _on_error(request: Request, exc: Exception):  # noqa: ANN001
        if isinstance(exc, HTTPException):
            return JSONResponse({"detail": exc.detail},
                                status_code=exc.status_code)
        return JSONResponse({"detail": "internal error"}, status_code=500)

    @app.get("/api/runs")
    async def list_runs(_=Depends(auth)):
        return build_run_list(repo, now=datetime.now(timezone.utc))

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: int, _=Depends(auth)):
        report = build_run_report(repo, run_id,
                                  now=datetime.now(timezone.utc))
        if report is None:
            raise HTTPException(status_code=404, detail="run not found")
        return report

    @app.get("/api/runs/{run_id}/stream")
    async def stream_run(run_id: int, request: Request, _=Depends(auth)):
        if repo.get_run_row(run_id) is None:
            raise HTTPException(status_code=404, detail="run not found")
        tailer = DbTailer(repo, run_id)
        return StreamingResponse(
            event_stream(tailer, poll_interval, request),
            media_type="text/event-stream")

    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True),
              name="static")
    return app
```

(Note: `app.py` imports `event_stream` from `sse.py`, built in Task 14. Run this task's tests only after Task 14 lands, OR create `sse.py` first — they are split for review clarity but `app.py` will not import-resolve until `sse.py` exists. Recommended: implement Task 14 immediately after Task 13's code, then run both test files.)

- [ ] **Step 4: Commit (after Task 14 makes imports resolve)**

```bash
git add src/etorobot/dashboard/app.py src/etorobot/dashboard/static/.gitkeep \
        tests/dashboard/test_app.py
git commit -m "feat(dashboard): FastAPI app with runs list/report endpoints"
```

---

### Task 14: SSE stream (`sse.py`)

**Files:**
- Create: `src/etorobot/dashboard/sse.py`
- Test: `tests/dashboard/test_sse.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/dashboard/test_sse.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/dashboard/test_sse.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'etorobot.dashboard.sse'`.

- [ ] **Step 3: Implement `sse.py`**

Create `src/etorobot/dashboard/sse.py`:

```python
# src/etorobot/dashboard/sse.py
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import Request

from etorobot.dashboard.tailer import DbTailer


def _format(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


async def event_stream(tailer: DbTailer, poll_interval: float,
                       request: Request) -> AsyncIterator[str]:
    """Yield SSE frames for new rows until the run closes or client leaves."""
    while True:
        if await request.is_disconnected():
            break
        for ev in tailer.poll():
            yield _format(ev["type"], ev["data"])
        if tailer.closed():
            yield _format("run_status", {"status": tailer.run_status()})
            break
        await asyncio.sleep(poll_interval)
```

- [ ] **Step 4: Run the SSE + app tests to verify they pass**

Run: `.venv/bin/pytest tests/dashboard/test_sse.py tests/dashboard/test_app.py -v`
Expected: PASS (both files; `app.py` imports now resolve).

- [ ] **Step 5: Commit**

```bash
git add src/etorobot/dashboard/sse.py tests/dashboard/test_sse.py
git commit -m "feat(dashboard): SSE event stream for live runs"
```

(If Task 13's `app.py` was not yet committed, include it and `test_app.py` in this commit.)

---

### Task 15: Frontend (static HTML/JS/CSS)

**Files:**
- Create: `src/etorobot/dashboard/static/index.html`
- Create: `src/etorobot/dashboard/static/run.html`
- Create: `src/etorobot/dashboard/static/app.js`
- Create: `src/etorobot/dashboard/static/styles.css`
- Delete: `src/etorobot/dashboard/static/.gitkeep` (no longer needed)

> No automated JS tests in v1 (per spec — frontend validated manually; business logic is in the backend, which is covered). Verification is a manual smoke check at the end of this task.

- [ ] **Step 1: Create `styles.css`**

Create `src/etorobot/dashboard/static/styles.css`:

```css
:root { font-family: system-ui, sans-serif; }
body { margin: 0; padding: 1.5rem; background: #0f1115; color: #e6e6e6; }
h1, h2 { font-weight: 600; }
a { color: #5aa9ff; }
table { border-collapse: collapse; width: 100%; margin: 0.5rem 0 1.5rem; }
th, td { border: 1px solid #2a2f3a; padding: 0.35rem 0.6rem; text-align: left;
         font-size: 0.85rem; }
th { background: #1a1e26; }
.badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 0.5rem;
         font-size: 0.75rem; }
.badge.running { background: #1f6f43; }
.badge.finished { background: #334; }
.badge.error { background: #7a2030; }
.badge.stale { background: #8a6d1a; }
.metrics { display: flex; gap: 1.5rem; flex-wrap: wrap; margin: 1rem 0; }
.metric { background: #1a1e26; padding: 0.75rem 1rem; border-radius: 0.5rem; }
.metric .value { font-size: 1.3rem; font-weight: 600; }
#equityChart { max-height: 320px; background: #1a1e26; border-radius: 0.5rem;
               padding: 0.5rem; }
```

- [ ] **Step 2: Create `index.html` (runs list)**

Create `src/etorobot/dashboard/static/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>etorobot — runs</title>
  <link rel="stylesheet" href="/styles.css">
</head>
<body>
  <h1>Ejecuciones</h1>
  <table id="runs">
    <thead><tr>
      <th>ID</th><th>Modo</th><th>Estrategia</th><th>Instrumentos</th>
      <th>Estado</th><th>Trades</th><th>Return</th><th>Inicio</th>
    </tr></thead>
    <tbody></tbody>
  </table>
  <script>window.VIEW = "list";</script>
  <script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Create `run.html` (report + live)**

Create `src/etorobot/dashboard/static/run.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>etorobot — run</title>
  <link rel="stylesheet" href="/styles.css">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
</head>
<body>
  <p><a href="/">← volver</a></p>
  <h1>Run <span id="runId"></span> <span id="statusBadge"></span></h1>
  <div class="metrics" id="metrics"></div>
  <h2>Equity</h2>
  <canvas id="equityChart"></canvas>
  <h2>Trades</h2>
  <table id="fills"><thead><tr>
    <th>ID</th><th>Acción</th><th>Símbolo</th><th>Precio</th><th>Units</th>
    <th>Monto</th><th>Comisión</th><th>Pos</th><th>Timestamp</th>
  </tr></thead><tbody></tbody></table>
  <h2>Señales</h2>
  <table id="signals"><thead><tr>
    <th>ID</th><th>Dirección</th><th>Símbolo</th><th>Aceptada</th>
    <th>Motivo</th><th>Timestamp</th>
  </tr></thead><tbody></tbody></table>
  <script>window.VIEW = "run";</script>
  <script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 4: Create `app.js`**

Create `src/etorobot/dashboard/static/app.js`:

```javascript
// Minimal dashboard client: token handling, fetch, SSE live updates.
function getToken() {
  let t = localStorage.getItem("dashboard_token");
  if (t === null) {
    t = window.prompt("Dashboard token (dejar vacío si no hay):") || "";
    localStorage.setItem("dashboard_token", t);
  }
  return t;
}
const TOKEN = getToken();
const authHeaders = TOKEN ? { Authorization: "Bearer " + TOKEN } : {};
const tokenQuery = TOKEN ? "?token=" + encodeURIComponent(TOKEN) : "";

async function apiGet(path) {
  const r = await fetch(path, { headers: authHeaders });
  if (r.status === 401) {
    localStorage.removeItem("dashboard_token");
    throw new Error("unauthorized");
  }
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}

function td(v) { const c = document.createElement("td"); c.textContent = v; return c; }

function badge(status, stale) {
  const span = document.createElement("span");
  const kind = stale ? "stale" : status;
  span.className = "badge " + kind;
  span.textContent = stale ? "stale" : status;
  return span;
}

async function renderList() {
  const runs = await apiGet("/api/runs");
  const tbody = document.querySelector("#runs tbody");
  tbody.innerHTML = "";
  for (const r of runs) {
    const tr = document.createElement("tr");
    const idCell = document.createElement("td");
    const link = document.createElement("a");
    link.href = "/run.html?id=" + r.id; link.textContent = r.id;
    idCell.appendChild(link); tr.appendChild(idCell);
    tr.appendChild(td(r.mode));
    tr.appendChild(td(r.strategy));
    tr.appendChild(td(r.instruments));
    const st = document.createElement("td");
    st.appendChild(badge(r.status, r.stale)); tr.appendChild(st);
    tr.appendChild(td(r.num_trades));
    tr.appendChild(td((r.total_return * 100).toFixed(2) + "%"));
    tr.appendChild(td(r.started_at || ""));
    tbody.appendChild(tr);
  }
}

let chart = null;
function ensureChart() {
  if (chart) return chart;
  const ctx = document.getElementById("equityChart").getContext("2d");
  chart = new Chart(ctx, {
    type: "line",
    data: { labels: [], datasets: [{ label: "Equity", data: [],
            borderColor: "#5aa9ff", tension: 0.1 }] },
    options: { animation: false, scales: { x: { display: false } } },
  });
  return chart;
}
function pushEquity(rows) {
  const c = ensureChart();
  for (const e of rows) { c.data.labels.push(e.timestamp); c.data.datasets[0].data.push(e.equity); }
  c.update();
}

function renderMetrics(m) {
  const wrap = document.getElementById("metrics");
  wrap.innerHTML = "";
  const items = [
    ["Total return", (m.total_return * 100).toFixed(2) + "%"],
    ["Max drawdown", (m.max_drawdown * 100).toFixed(2) + "%"],
    ["Sharpe", m.sharpe.toFixed(2)],
    ["Trades", m.num_trades],
    ["Win rate", (m.win_rate * 100).toFixed(1) + "%"],
  ];
  for (const [label, value] of items) {
    const d = document.createElement("div"); d.className = "metric";
    d.innerHTML = '<div>' + label + '</div><div class="value">' + value + '</div>';
    wrap.appendChild(d);
  }
}

function appendFill(f) {
  const tbody = document.querySelector("#fills tbody");
  const tr = document.createElement("tr");
  [f.id, f.action, f.symbol, f.price, f.units, f.amount, f.commission,
   f.position_id, f.timestamp].forEach((v) => tr.appendChild(td(v)));
  tbody.appendChild(tr);
}
function appendSignal(s) {
  const tbody = document.querySelector("#signals tbody");
  const tr = document.createElement("tr");
  [s.id, s.direction, s.symbol, s.accepted, s.reason || "",
   s.timestamp].forEach((v) => tr.appendChild(td(v)));
  tbody.appendChild(tr);
}

async function renderRun() {
  const id = new URLSearchParams(location.search).get("id");
  document.getElementById("runId").textContent = id;
  const rep = await apiGet("/api/runs/" + id);
  document.getElementById("statusBadge").appendChild(
    badge(rep.run.status, rep.run.stale));
  renderMetrics(rep.metrics);
  pushEquity(rep.equity);
  rep.fills.forEach(appendFill);
  rep.signals.forEach(appendSignal);
  if (rep.run.status === "running") openStream(id);
}

function openStream(id) {
  const es = new EventSource("/api/runs/" + id + "/stream" + tokenQuery);
  es.addEventListener("fill", (e) => appendFill(JSON.parse(e.data)));
  es.addEventListener("signal", (e) => appendSignal(JSON.parse(e.data)));
  es.addEventListener("equity", (e) => pushEquity([JSON.parse(e.data)]));
  es.addEventListener("run_status", (e) => {
    es.close();
    const s = JSON.parse(e.data).status;
    const badgeEl = document.getElementById("statusBadge");
    badgeEl.innerHTML = ""; badgeEl.appendChild(badge(s, false));
  });
}

if (window.VIEW === "list") renderList().catch((e) => alert(e.message));
else if (window.VIEW === "run") renderRun().catch((e) => alert(e.message));
```

- [ ] **Step 5: Remove the placeholder**

Run: `git rm src/etorobot/dashboard/static/.gitkeep`

- [ ] **Step 6: Manual smoke check**

Run a backtest to populate a DB, then start the dashboard and open it:

```bash
.venv/bin/etorobot --config config.yaml backtest --candles 200
.venv/bin/etorobot --config config.yaml dashboard --port 8000
```

(The `dashboard` subcommand is added in Task 16 — do this smoke check after Task 16.) Open `http://127.0.0.1:8000/`, confirm the run appears in the list, click it, and confirm metrics + equity chart + trades + signals render.

- [ ] **Step 7: Commit**

```bash
git add src/etorobot/dashboard/static/
git commit -m "feat(dashboard): static frontend (runs list + report + live SSE)"
```

---

### Task 16: `dashboard` CLI subcommand + end-to-end integration test

**Files:**
- Modify: `src/etorobot/cli.py`
- Test: `tests/dashboard/test_integration.py` (create)

- [ ] **Step 1: Write the failing integration test**

Create `tests/dashboard/test_integration.py`:

```python
# tests/dashboard/test_integration.py
from datetime import datetime, timezone, timedelta

from fastapi.testclient import TestClient

from etorobot.cli import do_backtest
from etorobot.config.settings import (
    AppConfig, Secrets, TelegramSecrets, InstrumentConfig, StrategyConfig,
    RiskConfig, BacktestConfig)
from etorobot.core.types import Candle
from etorobot.dashboard.app import create_app


class FakeClient:
    async def resolve_instrument(self, symbol):
        return 100000

    async def get_candles(self, instrument_id, symbol, interval, count):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        closes = [10, 9, 8, 9, 10, 11, 12, 11, 10, 8, 7, 9, 11, 13, 15]
        return [Candle(instrument_id, symbol, base + timedelta(minutes=i),
                       p, p, p, p, 1.0) for i, p in enumerate(closes)]

    async def __aenter__(self): return self
    async def __aexit__(self, *a): return None


def _config():
    return AppConfig(
        timeframe="OneMinute",
        instruments=[InstrumentConfig(symbol="BTC")],
        strategy=StrategyConfig(name="sma_crossover",
                                params={"fast": 2, "slow": 3}),
        risk=RiskConfig(position_size_pct=0.10, max_open_positions=3,
                        max_positions_per_instrument=1,
                        default_stop_loss_pct=0.02, default_take_profit_pct=0.04,
                        daily_loss_limit_pct=0.9),
        backtest=BacktestConfig(),
        secrets=Secrets(api_key="ak", user_key="uk", env="demo"),
        telegram=TelegramSecrets())


async def test_backtest_then_dashboard_report(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'e2e.db'}"
    await do_backtest(_config(), client=FakeClient(), candles_count=15,
                      db_url=db_url)

    client = TestClient(create_app(db_url, token=None))
    runs = client.get("/api/runs").json()
    assert len(runs) == 1
    run_id = runs[0]["id"]
    assert runs[0]["status"] == "finished"

    report = client.get(f"/api/runs/{run_id}").json()
    assert report["metrics"]["num_trades"] >= 1
    assert len(report["equity"]) >= 1
    assert len(report["signals"]) >= 1
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `.venv/bin/pytest tests/dashboard/test_integration.py -v`
Expected: PASS already (it uses code from earlier tasks). This test is the producer↔consumer guarantee; keep it. If it fails, the failure pinpoints a wiring gap to fix before proceeding.

- [ ] **Step 3: Add the `dashboard` subcommand to the CLI**

In `src/etorobot/cli.py`, add a `do_dashboard` function (after `do_run`):

```python
def do_dashboard(host: str, port: int, db_url: str) -> None:
    import uvicorn

    from etorobot.config.settings import DashboardSecrets
    from etorobot.dashboard.app import create_app

    token = DashboardSecrets().token
    uvicorn.run(create_app(db_url, token=token), host=host, port=port)
```

Then update `main()` to register and dispatch the subcommand:

```python
def main() -> None:
    parser = argparse.ArgumentParser(prog="etorobot")
    parser.add_argument("--config", default="config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    bt = sub.add_parser("backtest")
    bt.add_argument("--candles", type=int, default=500)
    dash = sub.add_parser("dashboard")
    dash.add_argument("--host", default="127.0.0.1")
    dash.add_argument("--port", type=int, default=8000)
    dash.add_argument("--db", default=None)
    args = parser.parse_args()
    config = load_config(args.config)

    if args.command == "run":
        asyncio.run(do_run(config, _make_client(config)))
    elif args.command == "backtest":
        metrics = asyncio.run(
            do_backtest(config, _make_client(config), args.candles))
        for k, v in metrics.items():
            print(f"{k}: {v}")
    elif args.command == "dashboard":
        db = args.db or f"bot_{config.secrets.env}.db"
        do_dashboard(args.host, args.port, f"sqlite:///{db}")
```

- [ ] **Step 4: Verify the CLI parses the new subcommand**

Run: `.venv/bin/python -c "import etorobot.cli as c; c.do_dashboard"`
Expected: no error (attribute resolves). Then confirm help works:
Run: `.venv/bin/etorobot --config config.yaml dashboard --help`
Expected: usage text listing `--host`, `--port`, `--db`.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/etorobot/cli.py tests/dashboard/test_integration.py
git commit -m "feat(cli): dashboard subcommand + e2e producer/consumer test"
```

---

### Task 17: Documentation

**Files:**
- Create: `docs/dashboard.md`
- Modify: `README.md` (add a Dashboard section + link)
- Modify: `docs/configuration.md` (document `DASHBOARD_TOKEN`)

- [ ] **Step 1: Write `docs/dashboard.md`**

Create `docs/dashboard.md` covering:
- What it is: a read-only web view of runs (live + backtests), real-time via SSE.
- Architecture recap (one paragraph + the ASCII diagram from the spec): separate FastAPI process, same host, reads the bot's SQLite in WAL mode, tails it ~1.5s, pushes new rows over SSE. Read-only (SELECT only).
- Run it:
  ```bash
  # set the shared token (required for any non-local exposure)
  echo 'DASHBOARD_TOKEN=choose-a-long-random-string' >> .env
  etorobot --config config.yaml dashboard --host 127.0.0.1 --port 8000
  ```
- **TLS / remote access:** the app binds to `127.0.0.1` by default and serves plain HTTP. To expose it remotely, put a TLS-terminating reverse proxy (nginx/Caddy) in front and forward to `127.0.0.1:8000`. Give a minimal Caddy example:
  ```
  dash.example.com {
      reverse_proxy 127.0.0.1:8000
  }
  ```
  Note SSE needs proxy buffering disabled (Caddy handles it; for nginx set `proxy_buffering off;` on the `/api/runs/*/stream` location).
- **Auth:** single shared token via `DASHBOARD_TOKEN`. Sent as `Authorization: Bearer <token>` for API calls and `?token=<token>` for the SSE stream (EventSource can't set headers). If `DASHBOARD_TOKEN` is unset, auth is disabled — only safe bound to localhost.
- **What "real-time" means:** event-paced (per closed candle / fill / signal), not sub-second; no live price ticks between candles.
- Endpoints: `GET /api/runs`, `GET /api/runs/{id}`, `GET /api/runs/{id}/stream` (SSE), static UI at `/`.

- [ ] **Step 2: Add a Dashboard section to `README.md`**

Under the CLI section, add a short "Dashboard" subsection with the run command and a link to `docs/dashboard.md`. Add `- [Dashboard](docs/dashboard.md)` to the Documentation list near the bottom of the README.

- [ ] **Step 3: Document `DASHBOARD_TOKEN` in `docs/configuration.md`**

Add a `### Dashboard (`DASHBOARD_` prefix) — `DashboardSecrets`` subsection in the `.env` part of `docs/configuration.md`:

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `DASHBOARD_TOKEN` | no | `None` | Shared token for the dashboard. If unset, the dashboard runs without auth (only safe on localhost). Required for remote exposure. |

- [ ] **Step 4: Verify doc links resolve**

Run: `grep -o "docs/dashboard.md" README.md` and confirm `docs/dashboard.md` exists.
Expected: the path prints and the file is present.

- [ ] **Step 5: Commit**

```bash
git add docs/dashboard.md README.md docs/configuration.md
git commit -m "docs: dashboard usage, TLS/reverse-proxy deploy, DASHBOARD_TOKEN"
```

---

## Final verification

- [ ] Run the full suite: `.venv/bin/pytest -q` — all green.
- [ ] Lint: `.venv/bin/ruff check` — clean (fix any new findings in the dashboard package).
- [ ] Manual smoke: run a backtest, launch `etorobot dashboard`, open `http://127.0.0.1:8000/`, click into the run, confirm metrics + equity chart + trades + signals render.
- [ ] After all tasks: use **superpowers:finishing-a-development-branch** to complete the work.

---

## Self-review notes (author)

**Spec coverage check (against `2026-06-01-dashboard-design.md`):**
- Runs concept + `run_id` on signals/fills/equity → Tasks 2, 4.
- Backtests persisted durably (not `:memory:`) → Tasks 7, 8.
- WAL for concurrent reads → Task 3.
- create_run/finish_run with status running/finished/error → Tasks 3, 8.
- Read/report DTO reusing `compute_metrics` → Task 10.
- Stale/orphan detection (running + live + > 3×timeframe idle) → Task 10.
- Tailer incremental by id → Task 11.
- Single-token auth (header + query for SSE + cookie), constant-time compare, 401 → Task 12.
- JSON endpoints (`/api/runs`, `/api/runs/{id}` with 404), global 500 handler, static mount → Task 13.
- SSE typed events + clean disconnect/close → Task 14.
- Frontend list + report + live updates + equity chart (Chart.js CDN) → Task 15.
- `dashboard` CLI subcommand (host/port/db) → Task 16.
- End-to-end producer↔consumer integration test → Task 16.
- TLS via reverse proxy documented → Task 17.
- Out-of-scope items (bot control, per-user accounts, sub-second ticks, report cache, JS tests) → not implemented, by design.

**Type consistency check:**
- `create_run(*, mode, env, strategy, params, timeframe, instruments, starting_cash)` is identical in Tasks 3, 7, 8 and all tests.
- Repo read methods return dicts with `id` + isoformat timestamps; the tailer and reads consume `["id"]`, `["timestamp"]`, `["equity"]`, `["status"]` consistently.
- `Engine(..., run_id=None)` keyword matches runner.py and cli.py call sites.
- `event_stream(tailer, poll_interval, request)` signature matches the `app.py` call site.
- `make_auth(token)` returns the dependency used as `Depends(auth)` in every endpoint.

**Placeholder scan:** none — every code step contains complete code; every test step has full test bodies and exact `pytest`/CLI commands with expected output.
