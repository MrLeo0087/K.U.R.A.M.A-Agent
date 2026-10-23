"""power_off: shutdown / restart is blocked by policy (never runs); lets the agent refuse clearly."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="power", safety="blocked", description="Shut down or restart the computer (blocked: not allowed).")
def power_off(action: Literal["shutdown", "restart"] = "shutdown") -> str:
    """Shutdown or restart (always refused by the safety gate).

    Args:
        action: shutdown or restart.
    """
    return f"refused: {action} is not allowed"  # unreachable: safety level 'blocked'
