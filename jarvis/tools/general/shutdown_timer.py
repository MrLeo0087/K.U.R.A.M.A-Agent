"""shutdown_timer: shut down / restart the laptop later ("after 2 min", "in 1 hour", "after 90 minutes", "at 11 pm"),
cancel it, or say when it is set. Uses Ubuntu's own scheduled shutdown (`shutdown +N`, no sudo), so it happens even
if KURAMA is closed; KURAMA also warns one minute before. Setting it asks first (safe tool, confirm inside)."""
from __future__ import annotations

import math
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


@tool(group="power", safety="safe",
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
    from jarvis.core import when as when_mod
    w = when_mod.parse(when or "")
    if w is None or w.ts <= time.time():
        return "error: say when, like 'after 30 minutes', 'in 2 hours' or 'at 11 pm'"
    minutes = max(1, math.ceil((w.ts - time.time()) / 60))
    at = time.time() + minutes * 60
    word = "restart" if kind == "restart" else "shut down"
    if not safety.ask(f"{word.capitalize()} the laptop at {datetime.fromtimestamp(at):%H:%M} (in {minutes} min)?"):
        return "Okay, I didn't schedule it."
    try:
        _sys.run(["shutdown", "-r" if kind == "restart" else "-P", f"+{minutes}"])
    except _sys.SysError as e:
        return f"error: Ubuntu didn't accept it ({e})"
    _warn_later(at, "restart" if kind == "restart" else "shutdown")
    return (f"Okay: the laptop will {word} at {datetime.fromtimestamp(at):%H:%M} (in {minutes} min). "
            f"I'll warn you a minute before; say 'cancel shutdown' to stop it.")
