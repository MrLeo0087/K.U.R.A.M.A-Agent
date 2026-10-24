"""focus_mode: a timed focus session: Do Not Disturb on, optional closing of config.FOCUS_CLOSE apps,
and a timer that turns DND back off and notifies "focus session done". Safe.
The timer lives in this process: if KURAMA exits early, DND stays on until turned off."""
from __future__ import annotations

import threading
import time
from typing import Literal

from jarvis.core import config
from jarvis.core.registry import tool
from jarvis.tools.general import _desk, _sys

_lock = threading.Lock()
_state: dict = {"timer": None, "ends": 0.0, "prev_dnd": False, "minutes": 0}


def _close_distractions() -> list[str]:
    from jarvis.tools.general import kill_app
    closed = []
    for app in config.FOCUS_CLOSE:
        procs, label = kill_app.find_targets(app)
        if procs:
            kill_app.stop(procs, force=False)
            closed.append(label)
    return closed


def _finish(notify_user: bool) -> None:
    with _lock:
        t, _state["timer"] = _state["timer"], None
        prev, minutes = _state["prev_dnd"], _state["minutes"]
        _state["ends"] = 0.0
    if t is not None:
        t.cancel()
    try:
        _desk.set_dnd(prev)
    except _sys.SysError:
        pass
    if notify_user:
        from jarvis.core import notify
        notify.notify("Focus session done", f"{minutes} minutes of focus finished. Take a short break!",
                      source="focus_mode")


def active() -> bool:
    return _state["timer"] is not None


@tool(group="desktop", safety="safe", description="Start or stop a timed focus (pomodoro) session: Do Not Disturb on, alert when done.")
def focus_mode(minutes: int = 25, action: Literal["start", "stop", "status"] = "start") -> str:
    """Focus session.

    Args:
        minutes: Session length in minutes (1-240).
        action: start, stop, or status.
    """
    if action == "status":
        if not active():
            return "No focus session is running."
        left = max(0, round((_state["ends"] - time.time()) / 60))
        return f"Focus session running: about {left} minute{'s' if left != 1 else ''} left."
    if action == "stop":
        if not active():
            return "No focus session is running."
        _finish(notify_user=False)
        return "Focus session stopped; notifications are back."
    if err := _desk.need_gsettings():
        return err
    minutes = _sys.clamp(minutes or 25, 1, 240)
    if active():
        _finish(notify_user=False)  # restart with the new length
    try:
        prev = _desk.dnd_on()
        _desk.set_dnd(True)
    except _sys.SysError as e:
        return f"error: could not turn on Do Not Disturb ({e})"
    closed = _close_distractions() if config.FOCUS_CLOSE else []
    timer = threading.Timer(minutes * 60, _finish, args=(True,))
    timer.daemon = True
    with _lock:
        _state.update(timer=timer, ends=time.time() + minutes * 60, prev_dnd=prev, minutes=minutes)
    timer.start()
    extra = f" Closed {', '.join(closed)}." if closed else ""
    return f"Focus mode on for {minutes} minutes: Do Not Disturb is on.{extra}"
