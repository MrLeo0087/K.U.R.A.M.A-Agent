"""set_my_name: rename the assistant (default KURAMA); it answers to the new name from now on (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="self", safety="safe", description="Change your own name when the user asks; you answer to it from now on.")
def set_my_name(name: str) -> str:
    """Rename the assistant.

    Args:
        name: The new name, one or two words.
    """
    from jarvis.core import identity
    new = identity.set_name(name)
    return f"Okay, my name is {new} now. Call me {new} anytime." if new else "error: that doesn't look like a name"
