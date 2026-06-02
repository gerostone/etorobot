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

    def run_signals(self, run_id: int, after_id: int = 0) -> list[dict]:
        with Session(self._engine) as s:
            rows = s.scalars(
                select(SignalRow)
                .where(SignalRow.run_id == run_id, SignalRow.id > after_id)
                .order_by(SignalRow.id.asc())).all()
            return [{
                "id": r.id, "symbol": r.symbol,
                "instrument_id": r.instrument_id, "direction": r.direction.upper() if r.direction else None,
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
