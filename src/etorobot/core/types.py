from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Direction(str, Enum):
    BUY = "buy"
    SELL = "sell"
    CLOSE = "close"


class Transaction(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MKT = "mkt"
    LIMIT = "limit"


@dataclass(frozen=True)
class Candle:
    instrument_id: int
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Position:
    position_id: str
    symbol: str
    instrument_id: int
    transaction: Transaction
    units: float
    amount: float
    open_price: float
    leverage: int
    stop_loss: float | None
    take_profit: float | None


@dataclass
class Portfolio:
    cash: float
    positions: list[Position] = field(default_factory=list)

    @property
    def equity(self) -> float:
        return self.cash + sum(p.amount for p in self.positions)

    def count_for_instrument(self, instrument_id: int) -> int:
        return sum(1 for p in self.positions if p.instrument_id == instrument_id)
