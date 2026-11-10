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
        from jarvis.core import automation  # daily Downloads sorting / weekly backups (slow ones live here)
        from jarvis.core import contentindex, health  # laptop health quietly; the documents index once a day
        for job in (automation.sort_auto_tick, automation.backup_tick, health.tick, contentindex.tick):
            try:
                if msg := job():
                    self.log.info("%s", msg)
            except Exception as e:
                self.log.warning("%s failed: %s", job.__name__, e)

    def info(self) -> dict:
        return {"projects": len(timemachine.projects())}
