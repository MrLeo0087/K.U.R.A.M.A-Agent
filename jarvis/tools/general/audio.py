"""audio: speaker volume, speaker mute and microphone mute in one tool (safe).

Merged from volume, mute_audio and mic_mute (their old names still work as aliases).
"""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import alias, tool
from jarvis.tools.general.mic_mute import mic_mute
from jarvis.tools.general.mute_audio import mute_audio
from jarvis.tools.general.volume import volume


@tool(group="audio", safety="safe",
      description="Sound: get/set/step the speaker volume, or mute/unmute the speakers or the microphone.")
def audio(action: Literal["get", "set", "up", "down", "mute", "unmute", "toggle", "status"] = "get",
          target: Literal["speakers", "mic"] = "speakers", level: int | None = None, step: int = 0) -> str:
    """Control the sound.

    Args:
        action: get/set/up/down = speaker volume; mute/unmute/toggle/status = muting.
        target: speakers (default) or mic (microphone: mute/unmute/toggle/status only).
        level: Volume 0-100 for action=set.
        step: How much to go up/down (0 = default step).
    """
    if target == "mic":
        if action in ("get", "set", "up", "down"):
            return "error: the microphone can only be muted, unmuted, toggled or checked"
        return mic_mute(action)
    if action in ("get", "set", "up", "down"):
        return volume(action, level, step)
    return mute_audio(action)


alias("volume", "audio", target="speakers")
alias("mute_audio", "audio", target="speakers")
alias("mic_mute", "audio", target="mic")
