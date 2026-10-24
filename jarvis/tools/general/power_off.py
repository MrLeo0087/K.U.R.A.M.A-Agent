"""power_off: shut down, restart or log out (confirm: always asks yes/no first). No sudo: systemd-logind lets the
logged-in user power off their own laptop."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool
from jarvis.tools.general import _sys

COMMANDS = {"shutdown": ["systemctl", "poweroff"], "restart": ["systemctl", "reboot"],
            "logout": ["gnome-session-quit", "--logout", "--no-prompt"]}
SAID = {"shutdown": "Shutting down now. Bye!", "restart": "Restarting now, see you in a minute.",
        "logout": "Logging you out now."}


@tool(group="power", safety="confirm", description="Shut down, restart or log out of the computer.")
def power_off(action: Literal["shutdown", "restart", "logout"] = "shutdown") -> str:
    """Shut down, restart or log out (asks the user first).

    Args:
        action: shutdown, restart or logout.
    """
    try:
        _sys.run(COMMANDS[action], timeout=10)
    except _sys.SysError as e:
        return f"error: {e}"
    return SAID[action]
