"""dictate: voice typing into any app (speech -> text typed at the cursor) until 'stop dictation' (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="windows", safety="safe",
      description="Speech-to-text (STT) / voice typing / dictation mode: type what the user says into whatever app "
                  "has the cursor (English, Nepali, Hindi) until they say 'stop dictation'; or turn it off.")
def dictate(action: Literal["start", "stop"] = "start", lang: Literal["auto", "en", "ne", "hi"] = "auto") -> str:
    """Start or stop dictation.

    Args:
        action: start or stop.
        lang: The language spoken (auto = detect each phrase).
    """
    from jarvis.core import dictation
    if action == "stop":
        return dictation.stop()
    return dictation.start(None if lang == "auto" else lang)
