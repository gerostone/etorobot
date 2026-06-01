# tests/risk/test_manager.py
from datetime import datetime, timezone, timedelta
import pytest
from etorobot.config.settings import RiskConfig
from etorobot.core.types import Direction, Transaction, Position, Portfolio
from etorobot.core.events import Signal
from etorobot.risk.manager import RiskManager


def _cfg(**over):
    base = dict(position_size_pct=0.10, max_open_positions=2,
                max_positions_per_instrument=1, default_stop_loss_pct=0.02,
                default_take_profit_pct=0.04, daily_loss_limit_pct=0.05)
    base.update(over)
    return RiskConfig(**base)


def _sig(direction=Direction.BUY, ts=None):
    return Signal("BTC", 100000, direction,
                  ts or datetime(2026, 1, 1, tzinfo=timezone.utc))


def _pos():
    return Position("p1", "BTC", 100000, Transaction.BUY, 1.0, 100.0, 100.0,
                    1, None, None)


def test_buy_sized_by_equity_with_sl_tp():
    rm = RiskManager(_cfg())
    pf = Portfolio(cash=1000.0, positions=[])
    d = rm.evaluate(_sig(), pf, price=200.0,
                    now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert d.accepted
    assert d.order.action == "open"
    assert d.order.transaction == Transaction.BUY
    assert d.order.amount == pytest.approx(100.0)  # 1000 * 0.10
    assert d.order.stop_loss == pytest.approx(196.0)  # 200 * 0.98
    assert d.order.take_profit == pytest.approx(208.0)  # 200 * 1.04


def test_reject_when_max_open_positions_reached():
    rm = RiskManager(_cfg(max_open_positions=1, max_positions_per_instrument=5))
    other = Position("p9", "ETH", 200000, Transaction.BUY, 1, 100, 100, 1,
                     None, None)
    pf = Portfolio(cash=1000.0, positions=[other])
    d = rm.evaluate(_sig(), pf, price=200.0,
                    now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert not d.accepted and "max open" in d.reason.lower()


def test_reject_duplicate_instrument():
    rm = RiskManager(_cfg(max_positions_per_instrument=1))
    pf = Portfolio(cash=1000.0, positions=[_pos()])
    d = rm.evaluate(_sig(), pf, price=200.0,
                    now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert not d.accepted and "instrument" in d.reason.lower()


def test_close_signal_emits_close_order_for_open_position():
    rm = RiskManager(_cfg())
    pf = Portfolio(cash=1000.0, positions=[_pos()])
    d = rm.evaluate(_sig(Direction.CLOSE), pf, price=200.0,
                    now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert d.accepted and d.order.action == "close"
    assert d.order.position_id == "p1"


def test_sell_signal_rejected_long_only():
    rm = RiskManager(_cfg())
    pf = Portfolio(cash=1000.0, positions=[])
    d = rm.evaluate(_sig(Direction.SELL), pf, price=200.0,
                    now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert not d.accepted and "short" in d.reason.lower()


def test_daily_loss_limit_kills_new_orders():
    rm = RiskManager(_cfg(daily_loss_limit_pct=0.05))
    t0 = datetime(2026, 1, 1, 9, tzinfo=timezone.utc)
    rm.evaluate(_sig(), Portfolio(cash=1000.0, positions=[]), 200.0, t0)
    later = t0 + timedelta(hours=1)
    d = rm.evaluate(_sig(), Portfolio(cash=940.0, positions=[]), 200.0, later)
    assert not d.accepted and "daily loss" in d.reason.lower()
