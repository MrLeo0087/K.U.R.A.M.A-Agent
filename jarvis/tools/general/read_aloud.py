"""read_aloud: speak given text (or the clipboard) with edge-tts in the background (safe)."""
from __future__ import annotations

from jarvis.core import config
from jarvis.core.registry import tool
from jarvis.tools.general import _sys

CLIPBOARD_WORDS = {"clipboard", "the clipboard", "my clipboard", "clip board", "what i copied", "copied text"}


@tool(group="speech", safety="safe", description='Read text aloud, or "clipboard" to read the clipboard aloud.')
def read_aloud(text: str) -> str:
    """Speak text through the speakers (non-blocking).

    Args:
        text: The text to speak, or "clipboard" to read the clipboard.
    """
    src = "text"
    if (text or "").strip().lower().rstrip(".") in CLIPBOARD_WORDS:
        try:
            text, src = _sys.clip_get(), "clipboard"
        except _sys.SysError as e:
            return f"error: {e}"
    text = " ".join((text or "").split())
    if not text:
        return "error: nothing to read (the clipboard is empty)" if src == "clipboard" else "error: nothing to read"
    cut = len(text) > config.READ_ALOUD_MAX_CHARS
    text = text[: config.READ_ALOUD_MAX_CHARS]
    from jarvis.core import planner, tts  # lazy: tts pulls the audio stack
    tts.speak(text, lang=planner.detect_lang(text), block=False)
    return f"reading {len(text)} characters aloud from the {src}" + (" (truncated)" if cut else "")
