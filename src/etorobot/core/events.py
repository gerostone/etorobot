from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from etorobot.core.types import Candle, Direction, OrderType, Transaction


@dataclass(frozen=True)
class MarketEvent:
    candle: Candle


@dataclass(frozen=True)
class Signal:
    symbol: str
    instrument_id: int
    direction: Direction
    timestamp: datetime
    strength: float = 1.0
    stop_loss: float | None = None
    take_profit: float | None = None
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True)
class OrderEvent:
    action: Literal["open", "close"]
    symbol: str
    instrument_id: int
    transaction: Transaction | None = None
    order_type: OrderType = OrderType.MKT
    amount: float | None = None
    leverage: int = 1
    stop_loss: float | None = None
    take_profit: float | None = None
    position_id: str | None = None
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True)
class FillEvent:
    symbol: str
    instrument_id: int
    action: Literal["open", "close"]
    transaction: Transaction
    price: float
    units: float
    amount: float
    commission: float
    position_id: str
    timestamp: datetime
