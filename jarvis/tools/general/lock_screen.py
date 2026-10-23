"""lock_screen: lock the desktop session (loginctl, then gnome-screensaver-command, then xdg-screensaver). Safe."""
from __future__ import annotations

from jarvis.core.registry import tool
from jarvis.tools.general import _sys

LOCKERS = (["loginctl", "lock-session"], ["gnome-screensaver-command", "-l"], ["xdg-screensaver", "lock"])


@tool(group="power", safety="safe", description="Lock the screen.")
def lock_screen() -> str:
    """Lock the screen now."""
    errors = []
    for argv in LOCKERS:
        if not _sys.which(argv[0]):
            continue
        try:
            _sys.run(argv, timeout=8)
            return "screen locked"
        except _sys.SysError as e:
            errors.append(f"{argv[0]}: {e}")
    if not errors:
        return "error: no screen locker found: install systemd (loginctl) or xdg-utils"
    return "error: could not lock the screen (" + "; ".join(errors)[:200] + ")"
