# src/etorobot/risk/manager.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from etorobot.config.settings import RiskConfig
from etorobot.core.events import OrderEvent, Signal
from etorobot.core.types import Direction, Portfolio, Transaction


@dataclass
class RiskDecision:
    accepted: bool
    order: OrderEvent | None
    reason: str | None = None


class RiskManager:
    def __init__(self, cfg: RiskConfig) -> None:
        self._cfg = cfg
        self._day: date | None = None
        self._day_baseline: float = 0.0

    def _update_day(self, now: datetime, equity: float) -> None:
        if self._day != now.date():
            self._day = now.date()
            self._day_baseline = equity

    def evaluate(self, signal: Signal, portfolio: Portfolio, price: float,
                 now: datetime) -> RiskDecision:
        self._update_day(now, portfolio.equity)

        if signal.direction == Direction.CLOSE:
            for p in portfolio.positions:
                if p.instrument_id == signal.instrument_id:
                    return RiskDecision(True, OrderEvent(
                        action="close", symbol=signal.symbol,
                        instrument_id=signal.instrument_id,
                        position_id=p.position_id))
            return RiskDecision(False, None, "no open position to close")

        if signal.direction == Direction.SELL:
            return RiskDecision(False, None,
                                "short selling disabled (long-only v1)")

        limit = self._day_baseline * (1 - self._cfg.daily_loss_limit_pct)
        if portfolio.equity <= limit:
            return RiskDecision(False, None, "daily loss limit reached")

        if len(portfolio.positions) >= self._cfg.max_open_positions:
            return RiskDecision(False, None, "max open positions reached")

        if (portfolio.count_for_instrument(signal.instrument_id)
                >= self._cfg.max_positions_per_instrument):
            return RiskDecision(False, None,
                                "max positions per instrument reached")

        amount = portfolio.equity * self._cfg.position_size_pct
        if amount > portfolio.cash:
            return RiskDecision(False, None, "insufficient cash")

        is_buy = signal.direction == Direction.BUY
        txn = Transaction.BUY if is_buy else Transaction.SELL
        sl = signal.stop_loss
        tp = signal.take_profit
        if sl is None:
            sl = (price * (1 - self._cfg.default_stop_loss_pct) if is_buy
                  else price * (1 + self._cfg.default_stop_loss_pct))
        if tp is None:
            tp = (price * (1 + self._cfg.default_take_profit_pct) if is_buy
                  else price * (1 - self._cfg.default_take_profit_pct))

        return RiskDecision(True, OrderEvent(
            action="open", symbol=signal.symbol,
            instrument_id=signal.instrument_id, transaction=txn,
            amount=amount, leverage=1, stop_loss=sl, take_profit=tp))
