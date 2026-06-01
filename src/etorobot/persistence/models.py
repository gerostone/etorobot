# src/etorobot/persistence/models.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SignalRow(Base):
    __tablename__ = "signals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String)
    instrument_id: Mapped[int] = mapped_column(Integer)
    direction: Mapped[str] = mapped_column(String)
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    accepted: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)


class FillRow(Base):
    __tablename__ = "fills"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
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
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
