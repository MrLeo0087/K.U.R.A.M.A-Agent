"""VS Code, exactly (the 'KURAMA editor link' extension, vscode_ext/): which file is open, what is selected (text +
lines), unsaved edits, and edits INTO the editor (one Ctrl+Z undoes them, unsaved edits are kept, no clipboard, no
key presses). Each VS Code window keeps ~/.local/share/kurama/vscode/<pid>.json up to date; reading it costs a few
microseconds and nothing polls. Without the extension (not installed yet, VS Code closed) every function says so
(None / False) and the callers fall back to the old window-title + selection-buffer guess.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from pathlib import Path

from jarvis.core import config

log = logging.getLogger(__name__)


def states() -> list[dict]:
    """Every live VS Code window, the most recently used first (files of closed windows are removed)."""
    out: list[dict] = []
    d = Path(config.VSCODE_STATE_DIR)
    for f in d.glob("*.json") if d.is_dir() else []:
        try:
            st = json.loads(f.read_text())
            os.kill(int(st["pid"]), 0)
        except ProcessLookupError:
            f.unlink(missing_ok=True)  # that window closed (or crashed) without saying goodbye
            continue
        except (OSError, ValueError, KeyError, TypeError):
            continue
        out.append(st)
    return sorted(out, key=lambda s: max(s.get("focused_at") or 0, 0), reverse=True)


def current(title: str = "") -> dict | None:
    """The window whose title is `title` ('test.py - KURAMA - Visual Studio Code'), else the last one used."""
    ss = states()
    if not ss:
        return None
    if title:
        from jarvis.core.assist import vscode_title
        if vs := vscode_title(title):
            name, folder = vs
            same = [s for s in ss if not folder or folder in (s.get("workspace"), Path(s.get("root") or "/").name)]
            for s in same or ss:
                if Path(s.get("file") or "").name == name:
                    return s
            if same:
                return same[0]
    return ss[0]


def for_window(title: str) -> dict | None:
    """The editor state for a window title, or None when that window is not VS Code (or the extension is off)."""
    if "Visual Studio Code" not in (title or ""):
        return None
    return current(title)


def target() -> dict | None:
    """The VS Code window the user was just in (the front window, or the one right below KURAMA), or None."""
    from jarvis.core import rewrite
    wid, _ = rewrite.target_window()
    return for_window(rewrite._window_name(wid, limit=400)) if wid else None


def _call(st: dict, body: dict, timeout: float = 8.0) -> dict:
    if not st.get("port"):
        return {"ok": False, "error": "the editor link isn't ready"}
    req = urllib.request.Request(f"http://127.0.0.1:{int(st['port'])}/", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Kurama-Token": st.get("token", "")})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except (OSError, ValueError) as e:
        log.info("editor link call failed: %s", e)
        return {"ok": False, "error": "VS Code didn't answer"}


def _holder(path: Path) -> dict | None:
    """The window that has this file open (shown first), else the one whose project holds it."""
    p = str(Path(path).expanduser())
    ss = states()
    for s in ss:
        if s.get("file") == p or p in (s.get("open") or []):
            return s
    for s in ss:
        if s.get("root") and p.startswith(s["root"].rstrip("/") + "/"):
            return s
    return None


def read(path: Path) -> str:
    """The file's text as the user sees it now: the editor's buffer (unsaved edits included), else the disk."""
    path = Path(path).expanduser()
    if (st := _holder(path)) is not None:
        r = _call(st, {"op": "text", "file": str(path)})
        if r.get("ok"):
            return r.get("text") or ""
    return path.read_text(errors="replace") if path.is_file() else ""


def edit(st: dict | None, op: str, **kw) -> dict:
    """One operation in that window: replace_all / replace_range / replace_text / insert ({'ok', 'error'})."""
    if st is None:
        return {"ok": False, "error": "no VS Code window with the editor link"}
    return _call(st, {"op": op, **kw})


def save_text(path: Path, text: str) -> str:
    """Put `text` as the whole file: through the editor when a VS Code window has it (undoable, saved when it had
    no unsaved edits), else on disk. Returns 'editor' or 'disk'."""
    path = Path(path).expanduser()
    if (st := _holder(path)) is not None and edit(st, "replace_all", file=str(path), text=text).get("ok"):
        return "editor"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return "disk"


def replace_once(path: Path, old: str, new: str) -> bool:
    """Replace the one place in the (live) file that holds `old` with `new`, in the editor. False: not possible
    there (not open, not found, found twice) -> the caller decides."""
    st = _holder(Path(path).expanduser())
    return st is not None and bool(edit(st, "replace_text", file=str(Path(path).expanduser()), old=old, text=new).get("ok"))
