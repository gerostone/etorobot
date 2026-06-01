# src/etorobot/persistence/repo.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from etorobot.core.events import FillEvent, Signal
from etorobot.persistence.models import Base, EquityRow, FillRow, SignalRow


class Repository:
    def __init__(self, url: str = "sqlite:///bot_demo.db") -> None:
        self._engine = create_engine(url)
        Base.metadata.create_all(self._engine)

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
