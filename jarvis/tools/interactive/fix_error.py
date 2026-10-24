"""fix_error: explain an error (pasted, or what's on the clipboard) and remember how you fixed it (safe).

Known errors are answered from memory at 0 tokens, with your own earlier fix; a new one costs one short call.
"""
from __future__ import annotations

from typing import Literal

from jarvis.core import errmem
from jarvis.core.registry import tool


@tool(group="dev", safety="safe",
      description="Explain an error or traceback (pasted text, or the clipboard if none) with cause + fix, remembering "
                  "it; 'fixed' saves how the user fixed the last error; 'list' shows errors seen before.")
def fix_error(action: Literal["explain", "fixed", "list"] = "explain", text: str = "") -> str:
    """Error memory.

    Args:
        action: explain = what the error means and how to fix it; fixed = remember `text` as the user's fix for the
            last error; list = recent errors and their fixes.
        text: The error/traceback (explain; empty = read the clipboard) or how the user fixed it (fixed).
    """
    if action == "fixed":
        return errmem.remember_fix(text) if text.strip() else "error: tell me how you fixed it"
    if action == "list":
        rows = errmem.recent()
        if not rows:
            return "No errors remembered yet."
        return "\n".join(f"{r['count']}x {r['error'][:90]}" + (f" -> fixed by: {r['fix'][:80]}" if r["fix"] else "")
                         for r in rows)
    if not text.strip():
        from jarvis.tools.general.read_clipboard import read_clipboard
        text = read_clipboard(4000)
        if text.startswith("error") or not text.strip():
            return "Paste the error (or copy it first) and ask me again."
    return errmem.answer(errmem.explain(text))
