# src/etorobot/brokers/etoro.py
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from etorobot.brokers.base import Broker
from etorobot.core.events import FillEvent, OrderEvent
from etorobot.core.types import Portfolio, Position, Transaction


class EtoroBroker(Broker):
    def __init__(self, client, poll_interval: float = 0.5,
                 poll_attempts: int = 20) -> None:
        self._client = client
        self._poll_interval = poll_interval
        self._poll_attempts = poll_attempts

    async def execute(self, order: OrderEvent) -> FillEvent:
        now = datetime.now(timezone.utc)
        if order.action == "open":
            resp = await self._client.create_order(
                symbol=order.symbol, instrument_id=order.instrument_id,
                transaction=order.transaction.value, amount=order.amount,
                leverage=order.leverage, stop_loss=order.stop_loss,
                take_profit=order.take_profit)
            rate, units, position_id = await self._await_fill(
                self._open_order_id(resp))
            return FillEvent(
                order.symbol, order.instrument_id, "open", order.transaction,
                price=rate, units=units, amount=order.amount,
                commission=0.0, position_id=position_id, timestamp=now)

        await self._client.close_position(
            order.position_id, order.instrument_id)
        rate, units, fees = await self._await_close_fill(
            order.position_id, now)
        return FillEvent(
            order.symbol, order.instrument_id, "close", Transaction.SELL,
            price=rate, units=units, amount=rate * units,
            commission=fees, position_id=order.position_id, timestamp=now)

    async def _await_fill(self, order_id) -> tuple[float, float, str]:
        """Poll the async order until it resolves into a filled position.

        eToro order placement is asynchronous: the placement response carries
        only an order id. The realized rate/units/positionID appear on a later
        get_order lookup once the order executes.
        """
        for _ in range(self._poll_attempts):
            info = await self._client.get_order(order_id)
            error = self._order_error(info)
            if error is not None:
                raise RuntimeError(f"order {order_id} failed: {error}")
            fill = self._parse_fill(info)
            if fill is not None:
                return fill
            await asyncio.sleep(self._poll_interval)
        raise TimeoutError(
            f"order {order_id} did not resolve after {self._poll_attempts} "
            f"polls")

    async def _await_close_fill(self, position_id,
                                now: datetime) -> tuple[float, float, float]:
        """Poll trade history until the closed position settles.

        Close orders have no status-lookup endpoint; the realized closeRate/
        units/fees only surface in the trade history once the close settles.
        Match on positionId. A one-day lookback avoids the UTC-midnight edge.
        """
        min_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        target = str(position_id)
        for _ in range(self._poll_attempts):
            trades = await self._client.get_trade_history(min_date)
            for trade in trades:
                if str(trade.get("positionId")) == target:
                    return (float(trade["closeRate"]), float(trade["units"]),
                            float(trade.get("fees") or 0.0))
            await asyncio.sleep(self._poll_interval)
        raise TimeoutError(
            f"close of position {position_id} did not settle after "
            f"{self._poll_attempts} polls")

    async def get_portfolio(self) -> Portfolio:
        data = await self._client.get_portfolio()
        return self._parse_portfolio(data)

    @staticmethod
    def _open_order_id(resp: dict):
        return resp["orderId"]

    @staticmethod
    def _order_error(info: dict) -> str | None:
        if info.get("errorCode"):
            return info.get("errorMessage") or "unknown error"
        return None

    @staticmethod
    def _parse_fill(info: dict) -> tuple[float, float, str] | None:
        positions = info.get("positions") or []
        if not positions:
            return None
        p = positions[0]
        return float(p["rate"]), float(p["units"]), str(p["positionID"])

    @staticmethod
    def _parse_portfolio(data: dict) -> Portfolio:
        portfolio = data["clientPortfolio"]
        positions = []
        for p in portfolio.get("positions", []):
            positions.append(Position(
                position_id=str(p["positionID"]),
                symbol=str(p.get("symbol", "")),
                instrument_id=int(p["instrumentID"]),
                transaction=Transaction.BUY if p["isBuy"] else Transaction.SELL,
                units=float(p["units"]), amount=float(p["amount"]),
                open_price=float(p["openRate"]), leverage=int(p["leverage"]),
                stop_loss=_opt_float(p.get("stopLossRate")),
                take_profit=_opt_float(p.get("takeProfitRate"))))
        return Portfolio(cash=float(portfolio["credit"]), positions=positions)


def _opt_float(value) -> float | None:
    return None if value is None else float(value)
