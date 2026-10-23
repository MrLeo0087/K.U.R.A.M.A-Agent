"""mute_audio: mute, unmute or toggle the speakers via pactl on @DEFAULT_SINK@ (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool
from jarvis.tools.general import _sys


@tool(group="audio", safety="safe", description="Mute, unmute or toggle the speakers, or say whether they are muted.")
def mute_audio(action: Literal["toggle", "mute", "unmute", "status"] = "toggle") -> str:
    """Speaker mute.

    Args:
        action: toggle, mute, unmute or status.
    """
    try:
        muted = _sys.pactl_mute("sink", action)
    except _sys.SysError as e:
        return f"error: {e}"
    state = "muted" if muted else "unmuted"
    return f"sound is {state}" if action == "status" else f"sound {state}"
