"""Location tracker worker (lightweight): records the laptop's location to build a history/trail.

It ticks every config.LOCATION_TICK_S but only does real work (one Wi-Fi scan + one small HTTP request,
cached) once config.LOCATION_LOG_INTERVAL_S has passed — or every config.LOCATION_LOST_INTERVAL_S while
"lost mode" is on. Points that barely moved are dropped (locationlog.record), and old points are pruned, so
this adds almost nothing to idle CPU/RAM and keeps the table tiny.
"""
from __future__ import annotations

import time

from jarvis.core import config, locationlog, store
from jarvis.workers.base import Worker


class LocationTracker(Worker):
    name = "location_tracker"
    interval_s = config.LOCATION_TICK_S

    def __init__(self, interval_s: float | None = None, now=None):
        super().__init__(interval_s)
        self._now = now or time.time
        self._last_log = 0.0
        self._last_prune = 0.0
        self.points = 0

    def tick(self) -> None:
        if not config.LOCATION_HISTORY:
            return
        now = self._now()
        lost = locationlog.lost_mode("laptop")
        due = config.LOCATION_LOST_INTERVAL_S if lost else config.LOCATION_LOG_INTERVAL_S
        if now - self._last_log < due:
            return  # just a cheap clock check: no network, no scan
        self._last_log = now
        try:
            point = locationlog.record_laptop()
            if point:
                self.points += 1
                self.log.info("laptop location: %s", point.get("place") or f"{point['lat']:.3f},{point['lon']:.3f}")
        except Exception as e:
            self.log.warning("location log failed: %s", e)
        if now - self._last_prune > 86400:  # once a day, trim old points
            self._last_prune = now
            try:
                store.locations_prune(config.LOCATION_KEEP_DAYS)
            except Exception as e:
                self.log.warning("location prune failed: %s", e)

    def info(self) -> dict:
        last = store.location_last("laptop")
        return {"enabled": config.LOCATION_HISTORY, "lost_mode": locationlog.lost_mode("laptop"),
                "logged": self.points, "last": (last or {}).get("place") or ""}
