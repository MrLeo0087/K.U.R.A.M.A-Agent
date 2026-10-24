"""Laptop guard worker: while armed, photo + location to Telegram on unlock, wrong password or wake-up.
Logic in jarvis/core/guard.py; costs nothing while disarmed (one kv read per tick)."""
from __future__ import annotations

from jarvis.core import config, guard
from jarvis.workers.base import Worker


class Guard(Worker):
    name = "guard"
    interval_s = config.GUARD_INTERVAL_S

    def __init__(self, interval_s: float | None = None) -> None:
        super().__init__(interval_s)
        self.state: dict = {}

    def tick(self) -> None:
        for e in guard.check(self.state):
            self.log.warning("guard: %s", e)

    def info(self) -> dict:
        return {"armed": guard.armed()}
