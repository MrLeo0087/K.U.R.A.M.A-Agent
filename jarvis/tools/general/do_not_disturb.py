"""do_not_disturb: GNOME Do Not Disturb (org.gnome.desktop.notifications show-banners). Safe."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool
from jarvis.tools.general import _desk, _sys


@tool(group="desktop", safety="safe", description="Turn Do Not Disturb (hide notification pop-ups) on or off.")
def do_not_disturb(action: Literal["on", "off", "toggle", "status"] = "toggle") -> str:
    """Do Not Disturb.

    Args:
        action: on, off, toggle, or status.
    """
    if err := _desk.need_gsettings():
        return err
    now = _desk.dnd_on()
    if action == "status":
        return f"Do Not Disturb is {'on' if now else 'off'}."
    try:
        want = _desk.target(action, now)
        _desk.set_dnd(want)
    except (ValueError, _sys.SysError) as e:
        return f"error: {e}"
    return "Do Not Disturb is on: notifications are silenced." if want else "Do Not Disturb is off."
