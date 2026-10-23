"""suspend_computer: put the computer to sleep with `systemctl suspend` (confirm)."""
from __future__ import annotations

from jarvis.core.registry import tool
from jarvis.tools.general import _sys


@tool(group="power", safety="confirm", description="Put the computer to sleep (suspend).")
def suspend_computer() -> str:
    """Suspend the computer (unsaved work stays in memory)."""
    try:
        _sys.run(["systemctl", "suspend"], timeout=10)
    except _sys.SysError as e:
        return f"error: {e}"
    return "suspending now"
