"""lecture: record a class (microphone, or the laptop's sound for an online class), stop it and get a transcript in
~/Notes/Lectures (background job), or a summary of the last one (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core import lecture as lec
from jarvis.core.registry import tool


@tool(group="study", safety="safe",
      description="Lecture recorder: start recording a class (mic, or 'laptop' sound for an online class), stop it "
                  "(transcript written in the background into Notes/Lectures), status, or summarize the last lecture.")
def lecture(action: Literal["start", "stop", "status", "summarize"] = "status", title: str = "",
            source: Literal["mic", "laptop"] = "mic") -> str:
    """Lecture recorder.

    Args:
        action: start, stop, status, or summarize (the latest transcript; ~1-2k tokens).
        title: Name of the lecture, e.g. "DSA trees".
        source: mic = a class in the room; laptop = the laptop's own sound (Zoom/Meet/YouTube class).
    """
    if action == "start":
        return lec.start(title, source)
    if action == "stop":
        return lec.stop()
    if action == "summarize":
        return lec.summarize()
    st = lec.state()
    if lec.recording():
        import time
        return f"Recording '{st['title']}' for {int((time.time() - st['start']) / 60)} min."
    f = lec.latest_transcript()
    return "Not recording." + (f" Last transcript: {f}" if f else "")
