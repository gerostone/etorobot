# src/etorobot/brokers/etoro.py
from __future__ import annotations

from datetime import datetime, timezone

from etorobot.brokers.base import Broker
from etorobot.core.events import FillEvent, OrderEvent
from etorobot.core.types import Portfolio, Position, Transaction


class EtoroBroker(Broker):
    def __init__(self, client) -> None:
        self._client = client

    async def execute(self, order: OrderEvent) -> FillEvent:
        now = datetime.now(timezone.utc)
        if order.action == "open":
            resp = await self._client.create_order(
                symbol=order.symbol, instrument_id=order.instrument_id,
                transaction=order.transaction.value, amount=order.amount,
                leverage=order.leverage, stop_loss=order.stop_loss,
                take_profit=order.take_profit)
            return FillEvent(
                order.symbol, order.instrument_id, "open", order.transaction,
                price=float(resp["executionRate"]),
                units=float(resp["units"]), amount=order.amount,
                commission=0.0, position_id=str(resp["positionId"]),
                timestamp=now)

        resp = await self._client.close_position(order.position_id)
        return FillEvent(
            order.symbol, order.instrument_id, "close", Transaction.SELL,
            price=float(resp["executionRate"]), units=float(resp["units"]),
            amount=float(resp["executionRate"]) * float(resp["units"]),
            commission=0.0, position_id=order.position_id, timestamp=now)

    async def get_portfolio(self) -> Portfolio:
        data = await self._client.get_portfolio()
        return self._parse_portfolio(data)

    @staticmethod
    def _parse_portfolio(data: dict) -> Portfolio:
        positions = []
        for p in data.get("positions", []):
            positions.append(Position(
                position_id=str(p["positionId"]),
                symbol=str(p.get("symbol", "")),
                instrument_id=int(p["instrumentId"]),
                transaction=Transaction.BUY if p["isBuy"] else Transaction.SELL,
                units=float(p["units"]), amount=float(p["amount"]),
                open_price=float(p["openRate"]), leverage=int(p["leverage"]),
                stop_loss=None, take_profit=None))
        return Portfolio(cash=float(data["credit"]), positions=positions)
