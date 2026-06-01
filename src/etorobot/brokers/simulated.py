# src/etorobot/brokers/simulated.py
from __future__ import annotations

import uuid

from etorobot.brokers.base import Broker
from etorobot.core.events import FillEvent, MarketEvent, OrderEvent
from etorobot.core.types import Candle, Portfolio, Position, Transaction


class SimulatedBroker(Broker):
    def __init__(self, starting_cash: float, commission_pct: float = 0.0,
                 slippage_pct: float = 0.0, fill_price: str = "close") -> None:
        self._cash = starting_cash
        self._commission_pct = commission_pct
        self._slippage_pct = slippage_pct
        self._fill_price = fill_price
        self._positions: dict[str, Position] = {}
        self._last: dict[int, Candle] = {}

    def on_market_event(self, event: MarketEvent) -> None:
        c = event.candle
        self._last[c.instrument_id] = c
        price = getattr(c, self._fill_price)
        for pos in self._positions.values():
            if pos.instrument_id == c.instrument_id:
                pos.amount = pos.units * price

    def _price(self, instrument_id: int) -> float:
        return getattr(self._last[instrument_id], self._fill_price)

    async def execute(self, order: OrderEvent) -> FillEvent:
        c = self._last[order.instrument_id]
        if order.action == "open":
            raw = self._price(order.instrument_id)
            buy = order.transaction == Transaction.BUY
            price = round(raw * (1 + self._slippage_pct), 8) if buy else \
                round(raw * (1 - self._slippage_pct), 8)
            units = order.amount / price
            commission = order.amount * self._commission_pct
            self._cash -= order.amount + commission
            pid = str(uuid.uuid4())
            self._positions[pid] = Position(
                position_id=pid, symbol=order.symbol,
                instrument_id=order.instrument_id, transaction=order.transaction,
                units=units, amount=order.amount, open_price=price,
                leverage=order.leverage, stop_loss=order.stop_loss,
                take_profit=order.take_profit)
            return FillEvent(order.symbol, order.instrument_id, "open",
                             order.transaction, price, units, order.amount,
                             commission, pid, c.timestamp)

        pos = self._positions.pop(order.position_id)
        raw = self._price(order.instrument_id)
        closing_buy = pos.transaction == Transaction.SELL
        price = raw * (1 + self._slippage_pct) if closing_buy else \
            raw * (1 - self._slippage_pct)
        proceeds = pos.units * price
        commission = proceeds * self._commission_pct
        self._cash += proceeds - commission
        close_txn = (Transaction.SELL if pos.transaction == Transaction.BUY
                     else Transaction.BUY)
        return FillEvent(order.symbol, order.instrument_id, "close", close_txn,
                         price, pos.units, proceeds, commission,
                         order.position_id, c.timestamp)

    async def get_portfolio(self) -> Portfolio:
        return Portfolio(cash=self._cash, positions=list(self._positions.values()))
