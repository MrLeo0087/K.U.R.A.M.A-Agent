"""mic_mute: mute, unmute or toggle the microphone via pactl on @DEFAULT_SOURCE@ (safe).

No longer a tool of its own: the merged tool calls mic_mute() (old name kept as an alias)."""
from __future__ import annotations

from typing import Literal

from jarvis.tools.general import _sys


def mic_mute(action: Literal["toggle", "mute", "unmute", "status"] = "toggle") -> str:
    """Microphone mute.

    Args:
        action: toggle, mute, unmute or status.
    """
    try:
        muted = _sys.pactl_mute("source", action)
    except _sys.SysError as e:
        return f"error: {e}"
    state = "muted" if muted else "unmuted"
    return f"microphone is {state}" if action == "status" else f"microphone {state}"
