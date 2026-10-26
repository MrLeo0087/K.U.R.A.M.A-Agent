"""Scheduler worker (P9b): every config.SCHEDULER_INTERVAL_S (15 s) fire due reminders / scheduled
commands (reminders.run_due), plus a heads-up config.REMINDER_LEAD_S (10 min) before each reminder. Items
missed while KURAMA was off fire once on start if < 1 h late, else they are marked missed and the user is told. On start it also tells the user once about background
jobs interrupted by the last quit/restart."""
from __future__ import annotations

import time
from typing import Callable

from jarvis.core import config, reminders, store
from jarvis.workers.base import Worker


class Scheduler(Worker):
    name = "scheduler"
    interval_s = config.SCHEDULER_INTERVAL_S

    def __init__(self, interval_s: float | None = None, now: Callable[[], float] | None = None):
        super().__init__(interval_s)
        self._now = now or time.time
        self.fired = 0
        self.missed = 0

    def setup(self) -> None:
        try:
            from jarvis.core import jobs

            jobs.announce_interrupted()
        except Exception as e:
            self.log.warning("interrupted-jobs check failed: %s", e)

    def tick(self) -> None:
        try:
            from jarvis.core import readlater
            if readlater.nudge(self._now()):
                self.log.info("list nudge sent")
        except Exception as e:
            self.log.warning("list nudge failed: %s", e)
        try:
            from jarvis.core import study
            for subject in study.check_reminders():
                self.log.info("class heads-up: %s", subject)
        except Exception as e:
            self.log.warning("timetable check failed: %s", e)
        try:
            from jarvis.core import kaggle_gpu
            kaggle_gpu.tick(self._now())
        except Exception as e:
            self.log.warning("kaggle check failed: %s", e)
        try:
            from jarvis.core import remotedesk
            remotedesk.expire_if_due(self._now())
        except Exception as e:
            self.log.warning("remote desktop expiry check failed: %s", e)
        for sid in reminders.heads_up(self._now()):
            self.log.info("schedule #%d heads-up", sid)
        for item in reminders.run_due(self._now()):
            if item["action"] == "fired":
                self.fired += 1
            else:
                self.missed += 1
            self.log.info("schedule #%d %s", item["id"], item["action"])

    def info(self) -> dict:
        rows = store.schedules_list(enabled_only=True, limit=1)
        return {"pending": len(store.schedules_list(enabled_only=True, limit=100)), "fired": self.fired,
                "missed": self.missed, "next": rows[0]["next_run"] if rows else None}
