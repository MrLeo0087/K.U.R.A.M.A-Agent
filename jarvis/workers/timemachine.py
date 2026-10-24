"""Time machine worker: every TIMEMACHINE_EVERY_S, snapshot the protected projects that changed (0 tokens).
Logic in jarvis/core/timemachine.py."""
from __future__ import annotations

from jarvis.core import config, timemachine
from jarvis.workers.base import Worker


class TimeMachine(Worker):
    name = "timemachine"
    interval_s = float(config.TIMEMACHINE_EVERY_S)

    def available(self) -> str | None:
        return None if config.TIMEMACHINE else "turned off (config.TIMEMACHINE)"

    def tick(self) -> None:
        for line in timemachine.auto_snapshots():
            self.log.info("%s", line)

    def info(self) -> dict:
        return {"projects": len(timemachine.projects())}
