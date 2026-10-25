"""Rewrite the selected text in place, in any app: select text, say "make this formal" / "fix grammar" /
"translate to Nepali" / "shorten this", and the new text replaces the selection.

X11 keeps the current selection in the PRIMARY buffer, so nothing has to be copied first. The rewrite is one fast
LLM call (~2x the text in tokens); the result is pasted over the still-selected text with the app's paste key, and
the user's clipboard is put back afterwards. If KURAMA's own window is in front (the request was typed in the
dashboard), the result goes to the clipboard instead, ready for Ctrl+V.
"""
from __future__ import annotations

import logging
import subprocess
import time

log = logging.getLogger(__name__)
MAX_CHARS = 6000
_SYS = ("Rewrite the user's text as instructed. Keep the meaning, names, numbers, links and formatting (line "
        "breaks, lists). Output ONLY the rewritten text: no quotes, no notes, no explanation.")


def _xclip(args: list[str], text: str | None = None) -> str:
    try:
        if text is not None:  # xclip forks to serve the selection: don't wait on its pipes
            subprocess.run(["xclip", *args, "-i"], input=text, text=True, timeout=5, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            return ""
        return subprocess.run(["xclip", *args, "-o"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def selection() -> str:
    return _xclip(["-selection", "primary"])


def _front_is_kurama() -> bool:
    try:
        out = subprocess.run(["xdotool", "getactivewindow", "getwindowname"], capture_output=True, text=True,
                             timeout=3).stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return True
    return "kurama" in out or "127.0.0.1:8000" in out or "localhost:8000" in out


def transform(text: str, instruction: str) -> str:
    from jarvis.core import llm
    reply = llm.chat([{"role": "system", "content": _SYS},
                      {"role": "user", "content": f"Instruction: {instruction}\n\nText:\n{text}"}],
                     tier="fast", purpose="rewrite", max_tokens=min(3000, len(text) // 2 + 300))
    return (reply.text or "").strip().strip('"“”')


def rewrite(instruction: str, text: str = "") -> str:
    if text.strip():
        return transform(text[:MAX_CHARS], instruction) or "error: the rewrite came back empty"
    sel = selection()
    if not sel.strip():
        return "Select the text first (highlight it with the mouse), then ask again."
    if len(sel) > MAX_CHARS:
        return f"That selection is too long ({len(sel)} characters, max {MAX_CHARS}). Select a smaller part."
    new = transform(sel, instruction)
    if not new:
        return "error: the rewrite came back empty; nothing was changed"
    old_clip = _xclip(["-selection", "clipboard"])
    _xclip(["-selection", "clipboard"], new)
    if _front_is_kurama():
        return "Done. The new text is on your clipboard: click where it should go and press Ctrl+V.\n\n" + new
    from jarvis.core import uiagent
    paste = "ctrl+shift+v" if uiagent.family(uiagent.active_class()) == "terminal" else "ctrl+v"
    time.sleep(0.15)
    uiagent.key(paste)
    time.sleep(0.4)
    if old_clip:
        _xclip(["-selection", "clipboard"], old_clip)  # leave the user's clipboard as it was
    words = len(new.split())
    return f"Replaced the selected text ({words} words)."
