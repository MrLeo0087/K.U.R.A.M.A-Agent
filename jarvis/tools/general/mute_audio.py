"""mute_audio: mute, unmute or toggle the speakers via pactl on @DEFAULT_SINK@ (safe).

No longer a tool of its own: the merged tool calls mute_audio() (old name kept as an alias)."""
from __future__ import annotations

from typing import Literal

from jarvis.tools.general import _sys


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
