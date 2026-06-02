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

    def record_signal(self, signal: Signal, accepted: bool,
                      reason: str | None = None) -> None:
        with Session(self._engine) as s:
            s.add(SignalRow(
                symbol=signal.symbol, instrument_id=signal.instrument_id,
                direction=signal.direction.value, timestamp=signal.timestamp,
                accepted=accepted, reason=reason))
            s.commit()

    def record_fill(self, fill: FillEvent) -> None:
        with Session(self._engine) as s:
            s.add(FillRow(
                symbol=fill.symbol, instrument_id=fill.instrument_id,
                action=fill.action, transaction=fill.transaction.value,
                price=fill.price, units=fill.units, amount=fill.amount,
                commission=fill.commission, position_id=fill.position_id,
                timestamp=fill.timestamp))
            s.commit()

    def record_equity(self, timestamp: datetime, equity: float,
                      cash: float) -> None:
        with Session(self._engine) as s:
            s.add(EquityRow(timestamp=timestamp, equity=equity, cash=cash))
            s.commit()

    def count_signals(self) -> int:
        with Session(self._engine) as s:
            return s.scalar(select(func.count()).select_from(SignalRow))

    def count_fills(self) -> int:
        with Session(self._engine) as s:
            return s.scalar(select(func.count()).select_from(FillRow))

    def last_signal(self) -> SignalRow | None:
        with Session(self._engine) as s:
            return s.scalars(
                select(SignalRow).order_by(SignalRow.id.desc()).limit(1)
            ).first()

    def equity_curve(self) -> list[float]:
        with Session(self._engine) as s:
            rows = s.scalars(
                select(EquityRow).order_by(EquityRow.id.asc())).all()
            return [r.equity for r in rows]

    def trade_pnls(self) -> list[float]:
        with Session(self._engine) as s:
            fills = s.scalars(
                select(FillRow).order_by(FillRow.id.asc())).all()
        opens: dict[str, float] = {}
        pnls: list[float] = []
        for f in fills:
            if f.action == "open":
                opens[f.position_id] = f.amount
            elif f.action == "close" and f.position_id in opens:
                pnls.append(f.amount - opens.pop(f.position_id))
        return pnls
