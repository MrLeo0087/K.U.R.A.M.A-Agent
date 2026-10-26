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


def status() -> str:
    """Every alert kind: allowed, or paused with the minutes left (the /notifications command)."""
    now = time.time()
    paused, allowed = [], []
    for kind, sources in config.MUTE_KINDS.items():
        until = max(notify.muted(s) for s in sources)
        (paused if until > now else allowed).append((kind, until))
    if not paused:
        return "🔔 All notifications are ON: " + ", ".join(LABEL[k] for k, _ in allowed) + "."
    lines = ["🔔 Notifications", "🔕 Paused:"]
    lines += [f"• {LABEL[k]}: {_human((u - now) / 60 + 0.5)} left (until {_at(u)})"
              for k, u in sorted(paused, key=lambda x: x[1])]
    lines += ["✅ On: " + (", ".join(LABEL[k] for k, _ in allowed) or "nothing else")]
    lines += ["/unmute <what> (e.g. /unmute ram) or /unmute = all back on now."]
    return "\n".join(lines)


@tool(group="telegram", safety="safe",
      description="Mute KURAMA alerts for a while (laptop + Telegram): what = resource (RAM), location, jobs, "
                  "all... or last (the alert just sent). off = unmute, status = what is muted.")
def mute_alerts(action: Literal["on", "off", "status"] = "on", what: str = "last", minutes: float = 0) -> str:
    """Mute or unmute alerts.

    Args:
        action: on = mute, off = unmute, status = list current mutes.
        what: resource, location, jobs, downloads, watchdog, web, commands, digest, backup, internet, guard,
            reminders, all, or last (whatever alert was sent most recently).
        minutes: how long (default 30, at most 24 h: never forever).
    """
    what = (what or "last").strip().lower()
    if what == "last":  # the alert the user replied to on Telegram, else the newest one
        src = notify.replied_source() or next((a["source"] for a in store.alerts_recent(5) if a.get("source")), "")
        what = _BY_SOURCE.get(src, src or "all")
    label = LABEL.get(what, f"{what} alerts")
    if action == "status":
        return status()
    if action == "off":
        gone = notify.unmute(what)
        return f"Unmuted {label}." if gone else "Nothing like that was muted."
    minutes = min(minutes or config.MUTE_DEFAULT_MIN, config.MUTE_MAX_MIN)
    until = notify.mute(what, minutes)
    return f"OK, no {label} for {_human(minutes)} (until {_at(until)}). Say 'unmute alerts' to undo."
