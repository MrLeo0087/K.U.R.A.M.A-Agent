"""shutdown_timer: shut down / restart the laptop later ("after 2 min", "in 1 hour", "after 90 minutes", "at 11 pm"),
cancel it, or say when it is set. Uses Ubuntu's own scheduled shutdown (`shutdown +N`, no sudo), so it happens even
if KURAMA is closed; KURAMA also warns one minute before. Setting it asks first (safe tool, confirm inside)."""
from __future__ import annotations

import math
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Literal

from jarvis.core import notify, safety
from jarvis.core.registry import tool
from jarvis.tools.general import _sys

SCHEDULED = Path("/run/systemd/shutdown/scheduled")
_warn: threading.Timer | None = None


def scheduled() -> tuple[float, str] | None:
    """(epoch seconds, 'poweroff' | 'reboot') of the shutdown Ubuntu has scheduled, or None."""
    try:
        kv = dict(ln.split("=", 1) for ln in SCHEDULED.read_text().splitlines() if "=" in ln)
        return int(kv["USEC"]) / 1e6, kv.get("MODE", "poweroff")
    except (OSError, KeyError, ValueError):
        return None


def _warn_later(at: float, word: str) -> None:
    global _warn
    if _warn:
        _warn.cancel()
    left = at - time.time() - 60
    if left > 0:
        _warn = threading.Timer(left, lambda: notify.notify(f"{word.capitalize()} in 1 minute",
                                                           f"Say 'cancel {word}' to stop it.", level="warning",
                                                           source="power", telegram=True))
        _warn.daemon = True
        _warn.start()


_UNIT = {"s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1, "m": 60, "min": 60, "mins": 60, "minute": 60,
         "minutes": 60, "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600}
_DUR = re.compile(r"(\d+(?:\.\d+)?)\s*(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|hr|h)\b", re.I)


def seconds_from(text: str) -> float | None:
    """'3s', '4min', '2hrs', '1h 30m', 'after 90 minutes', 'half an hour' -> seconds; a clock time ('at 11 pm') ->
    seconds until then; None when there is no time in it."""
    t = (text or "").lower()
    if not re.search(r"\bat\b", t) and (pairs := _DUR.findall(t)):
        return sum(float(n) * _UNIT[u] for n, u in pairs)
    if re.search(r"\bhalf\s+an?\s+hour\b", t):
        return 1800.0
    if re.search(r"\ban?\s+hour\b", t):
        return 3600.0
    from jarvis.core import when as when_mod
    w = when_mod.parse(t if re.match(r"\s*(?:after|in|at|within)\b", t) else f"in {t}")
    return w.ts - time.time() if w and w.ts > time.time() else None


def _now_later(seconds: float, kind: str) -> None:
    """Under a minute: KURAMA does it itself (Ubuntu's timer counts whole minutes)."""
    cmd = ["systemctl", "reboot" if kind == "restart" else "poweroff"]
    t = threading.Timer(seconds, lambda: _sys.run(cmd, timeout=10))
    t.daemon = False  # keep it even if this request's thread ends
    t.start()


@tool(group="clock", safety="safe",
      description="Shut down or restart the laptop LATER: 'after 2 min', 'in 1 hour', 'after 90 minutes', 'at 11 pm' "
                  "(asks first); cancel it; or say when it's set.")
def shutdown_timer(action: Literal["set", "cancel", "status"] = "set", when: str = "",
                   kind: Literal["shutdown", "restart"] = "shutdown") -> str:
    """Scheduled shutdown.

    Args:
        action: set, cancel or status.
        when: When to do it: 'after 90 minutes', 'in 2 hours', 'at 11 pm'.
        kind: shutdown or restart.
    """
    global _warn
    if action == "status":
        s = scheduled()
        if not s:
            return "No shutdown is scheduled."
        word = "restart" if s[1] == "reboot" else "shut down"
        return f"The laptop will {word} at {datetime.fromtimestamp(s[0]):%H:%M} (in {max(1, round((s[0] - time.time()) / 60))} min)."
    if action == "cancel":
        if not scheduled():
            return "No shutdown was scheduled."
        try:
            _sys.run(["shutdown", "-c"])
        except _sys.SysError as e:
            return f"error: couldn't cancel it ({e})"
        if _warn:
            _warn.cancel()
            _warn = None
        return "Cancelled: the laptop won't shut down."
    secs = seconds_from(when)
    if not secs or secs <= 0:
        return "error: say when, like '30s', '10min', '2hrs', 'after 90 minutes' or 'at 11 pm'"
    word = "restart" if kind == "restart" else "shut down"
    if secs < 60:
        if not safety.ask(f"{word.capitalize()} the laptop in {round(secs)} seconds?"):
            return "Okay, I didn't schedule it."
        _now_later(secs, kind)
        return f"Okay: the laptop will {word} in {round(secs)} seconds."
    minutes = max(1, math.ceil(secs / 60))
    at = time.time() + minutes * 60
    span = f"{minutes} min" if minutes < 120 else f"{minutes / 60:g} h"
    if not safety.ask(f"{word.capitalize()} the laptop at {datetime.fromtimestamp(at):%H:%M} (in {span})?"):
        return "Okay, I didn't schedule it."
    try:
        _sys.run(["shutdown", "-r" if kind == "restart" else "-P", f"+{minutes}"])
    except _sys.SysError as e:
        return f"error: Ubuntu didn't accept it ({e})"
    _warn_later(at, "restart" if kind == "restart" else "shutdown")
    return (f"Okay: the laptop will {word} at {datetime.fromtimestamp(at):%H:%M} (in {span}). "
            f"I'll warn you a minute before; say 'cancel shutdown' to stop it.")
