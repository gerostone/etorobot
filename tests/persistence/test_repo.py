# tests/persistence/test_repo.py
from datetime import datetime, timezone
from etorobot.core.types import Direction, Transaction
from etorobot.core.events import Signal, FillEvent
from etorobot.persistence.repo import Repository


def _ts():
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_records_signal_and_fill_in_memory():
    repo = Repository("sqlite:///:memory:")
    repo.record_signal(Signal("BTC", 100000, Direction.BUY, _ts()),
                       accepted=False, reason="max positions")
    repo.record_fill(FillEvent("BTC", 100000, "open", Transaction.BUY,
                               500.0, 1.0, 500.0, 0.5, "p1", _ts()))
    assert repo.count_signals() == 1
    assert repo.count_fills() == 1
    last = repo.last_signal()
    assert last.accepted is False and last.reason == "max positions"
