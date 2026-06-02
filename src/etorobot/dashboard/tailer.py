# src/etorobot/dashboard/tailer.py
from __future__ import annotations

from etorobot.persistence.repo import Repository


class DbTailer:
    """Polls one run's signals/fills/equity, emitting only new rows by id."""

    def __init__(self, repo: Repository, run_id: int) -> None:
        self._repo = repo
        self._run_id = run_id
        self._cursor = {"signal": 0, "fill": 0, "equity": 0}

    def poll(self) -> list[dict]:
        events: list[dict] = []
        for sig in self._repo.run_signals(self._run_id,
                                          after_id=self._cursor["signal"]):
            self._cursor["signal"] = sig["id"]
            events.append({"type": "signal", "data": sig})
        for fill in self._repo.run_fills(self._run_id,
                                         after_id=self._cursor["fill"]):
            self._cursor["fill"] = fill["id"]
            events.append({"type": "fill", "data": fill})
        for eq in self._repo.run_equity(self._run_id,
                                        after_id=self._cursor["equity"]):
            self._cursor["equity"] = eq["id"]
            events.append({"type": "equity", "data": eq})
        return events

    def run_status(self) -> str | None:
        run = self._repo.get_run_row(self._run_id)
        return run["status"] if run is not None else None

    def closed(self) -> bool:
        return self.run_status() != "running"
