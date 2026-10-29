"""What is open right now (0 tokens to collect, ~30 to send): the file open in VS Code and the code selected in it,
or the browser's tab. Read only — nothing is clicked or typed. The selection is X's PRIMARY buffer, trusted only
when it is really in the open file (so text highlighted elsewhere, or in KURAMA, never counts).
"""
from __future__ import annotations

import shutil
import subprocess
import time

_cache: tuple[float, dict] = (0.0, {})


def _primary() -> str:
    if not shutil.which("xclip"):
        return ""
    try:
        r = subprocess.run(["xclip", "-o", "-selection", "primary"], capture_output=True, text=True, timeout=0.5)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def snapshot() -> dict:
    """{'file': Path|None, 'selection': str, 'tab': (url, title)|None}; cached for 2 s (one per request)."""
    global _cache
    if time.monotonic() - _cache[0] < 2:
        return _cache[1]
    out: dict = {"file": None, "selection": "", "tab": None}
    from jarvis.core import config
    if not config.CONTEXT:
        return out
    try:
        from jarvis.core import assist
        f = assist.open_file_in_editor()
        if f is not None and f.is_file():
            out["file"] = f
            sel = _primary().strip()
            if sel and len(sel) < 20000 and sel in f.read_text(errors="replace"):
                out["selection"] = sel
    except Exception:  # noqa: BLE001 - context is a bonus, never a failure
        pass
    if out["file"] is None:
        try:
            from jarvis.core import browsertab
            out["tab"] = browsertab.get(600)
        except Exception:  # noqa: BLE001
            pass
    _cache = (time.monotonic(), out)
    return out


def line() -> str:
    """One short sentence for the system prompt ('' when nothing useful is open)."""
    s = snapshot()
    if s["file"] is not None:
        txt = f"Open in VS Code: {s['file'].name} ({s['file'].parent.name})."
        if s["selection"]:
            sel = " ".join(s["selection"].split())
            txt += f" Selected code: `{sel[:160]}{'…' if len(sel) > 160 else ''}` — 'this/it/the code' means it;" \
                   " to change it use text edit_code."
        else:
            txt += " 'this code/file' means it; to change it use text edit_code."
        txt += " To write code into it (generate + write, like an editor): text code_to_file with the user's words."
        return txt
    if s["tab"]:
        return f"Open in the browser: {s['tab'][1][:80]} ({s['tab'][0][:100]}) — 'this page/link/video' means it."
    return ""


def editor_open() -> bool:
    return snapshot()["file"] is not None
