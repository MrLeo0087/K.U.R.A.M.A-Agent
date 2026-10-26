"""mute_alerts: pause one kind of KURAMA alert (RAM/resource, location, jobs...) or all of them for a while, on
the laptop AND on Telegram. 'all' still lets reminders, timers and the anti-theft guard through. Safe."""
from __future__ import annotations

import time
from typing import Literal

from jarvis.core import config, notify, store
from jarvis.core.registry import tool

LABEL = {"resource": "RAM / resource warnings", "location": "location messages", "jobs": "job-done messages",
         "downloads": "download messages", "watchdog": "crash-watchdog messages", "web": "web-watch messages",
         "commands": "command-finished messages", "digest": "the daily summary", "backup": "backup messages",
         "kaggle": "Kaggle messages", "internet": "internet messages", "guard": "anti-theft guard alerts",
         "reminders": "reminders and timers", "all": "all alerts (reminders, timers and the guard still come)"}
_BY_SOURCE = {src: k for k, srcs in config.MUTE_KINDS.items() for src in srcs}


def _at(ts: float) -> str:
    return time.strftime("%-I:%M %p", time.localtime(ts))


def _human(minutes: float) -> str:
    m = round(minutes)
    if m < 60:
        return f"{m} min"
    h, r = divmod(m, 60)
    return f"{h} h" + (f" {r} min" if r else "")


@tool(group="telegram", safety="safe",
      description="Mute KURAMA alerts for a while (laptop + Telegram): what = resource (RAM), location, jobs, "
                  "all... or last (the alert just sent). off = unmute, status = what is muted.")
def mute_alerts(action: Literal["on", "off", "status"] = "on", what: str = "last", minutes: float = 0) -> str:
    """Mute or unmute alerts.

    Args:
        action: on = mute, off = unmute, status = list current mutes.
        what: resource, location, jobs, downloads, watchdog, web, commands, digest, backup, internet, guard,
            reminders, all, or last (whatever alert was sent most recently).
        minutes: how long (default 60).
    """
    what = (what or "last").strip().lower()
    if what == "last":
        src = next((a["source"] for a in store.alerts_recent(5) if a.get("source")), "")
        what = _BY_SOURCE.get(src, src or "all")
    label = LABEL.get(what, f"{what} alerts")
    if action == "status":
        mutes = notify.active_mutes()
        if not mutes:
            return "Nothing is muted: every alert comes through."
        names = sorted({("all" if s == "*" else _BY_SOURCE.get(s, s), until) for s, until in mutes.items()})
        return "Muted: " + "; ".join(f"{LABEL.get(k, k)} until {_at(u)}" for k, u in names) + "."
    if action == "off":
        gone = notify.unmute(what)
        return f"Unmuted {label}." if gone else "Nothing like that was muted."
    minutes = minutes or config.MUTE_DEFAULT_MIN
    until = notify.mute(what, minutes)
    return f"OK, no {label} for {_human(minutes)} (until {_at(until)}). Say 'unmute alerts' to undo."
