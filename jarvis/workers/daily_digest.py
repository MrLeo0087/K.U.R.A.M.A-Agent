"""Daily digest worker (P7): once per day at config.DIGEST_TIME, build the digest (zero-LLM template
by default) and send it via notify() (desktop + Telegram + alerts table). The last sent date lives
in the kv table, so restarts never send twice; if the laptop was off at that time it is sent at the
first tick later that day."""
from __future__ import annotations

from datetime import datetime
from datetime import time as dtime
from typing import Callable

from jarvis.core import config, digest, notify, store
from jarvis.workers.base import Worker

KV_KEY = "digest_last_sent"


def digest_time() -> dtime:
    try:
        hh, mm = (int(x) for x in config.DIGEST_TIME.split(":")[:2])
        return dtime(hh, mm)
    except (ValueError, AttributeError):
        return dtime(22, 0)


class DailyDigest(Worker):
    name = "daily_digest"
    interval_s = config.DIGEST_INTERVAL_S

    def __init__(self, interval_s: float | None = None, now: Callable[[], datetime] | None = None):
        super().__init__(interval_s)
        self._now = now or datetime.now
        self.sent = 0

    def due(self) -> bool:
        now = self._now()
        return now.time() >= digest_time() and store.kv_get(KV_KEY) != now.date().isoformat()

    def tick(self) -> None:
        if not self.due():
            return
        now = self._now()
        text = digest.build_digest("today", now=now)
        store.kv_set(KV_KEY, now.date().isoformat())  # mark first: a notify hiccup must not resend
        notify.notify("Daily digest", text, level="info", source=self.name)
        self.sent += 1
        self.log.info("daily digest sent (%d chars)", len(text))

    def info(self) -> dict:
        return {"time": config.DIGEST_TIME, "last_sent": store.kv_get(KV_KEY) or ""}
