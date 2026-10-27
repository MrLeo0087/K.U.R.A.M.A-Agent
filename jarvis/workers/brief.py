"""Morning brief worker: the first unlock / wake-up of the day -> brief.deliver(). Once today's brief is given it
only reads one kv value per tick (no subprocess)."""
from __future__ import annotations

from jarvis.core import brief, config, guard
from jarvis.workers.base import Worker


class Brief(Worker):
    name = "brief"
    interval_s = config.BRIEF_INTERVAL_S

    def __init__(self, interval_s: float | None = None) -> None:
        super().__init__(interval_s)
        self.watch = brief.Watch()

    def tick(self) -> None:
        if not brief.due():
            self.watch.tick(self.watch.locked)  # keep the clock fresh so a later sleep is still noticed
            return
        if reason := self.watch.tick(guard.locked()):
            brief.deliver(reason)

    def info(self) -> dict:
        return {"due": brief.due()}
