"""open_path: open a file or folder in VS Code (default), the file manager or its own app. Loose names, 'this/it'
(the last file/folder KURAMA showed, or a path written in the message) and full paths all work. Safe."""
from __future__ import annotations

from pathlib import Path

from jarvis.core.registry import tool

_VSCODE = ("vscode", "vs code", "code", "visual studio code", "editor", "")
_FILES = ("files", "file manager", "nautilus", "folder", "explorer")


def _find(path: str) -> Path | None:
    from jarvis.core import context, focus
    from jarvis.core.paths import smart_path
    raw = (path or "").strip().strip("\"'")
    if not raw or focus.is_anaphora(raw):
        hit = focus.refer(raw or "this")
        if hit is None and (f := context.snapshot().get("file")) is not None:
            hit = Path(f)
        return hit
    p = Path(raw).expanduser()
    return p if p.is_absolute() and p.exists() else smart_path(raw)


@tool(group="files", safety="safe",
      description="Open a file or folder in VS Code (default), the file manager or its default app: "
                  "'open Downloads in VS Code', 'open main.py in code', 'open this folder in VS Code'.")
def open_path(path: str = "", app: str = "vscode") -> str:
    """Open a file or folder in an app.

    Args:
        path: The file or folder: a name ('downloads', 'kurama project'), a full path, or 'this'/'it'.
        app: vscode (default), files (the file manager) or default (the file's own app).
    """
    from jarvis.core import focus
    from jarvis.tools.general import _sys
    from jarvis.tools.general.open_url import _open
    p = _find(path)
    if p is None or not p.exists():
        return f"error: I couldn't find {path or 'that'} — say its name or full path"
    a = (app or "").strip().lower()
    focus.set_path(str(p))
    if a in _VSCODE:
        try:
            _sys.run(["code", str(p)], timeout=15)
        except _sys.SysError as e:
            return f"error: {e}"
        return f"Opened {p.name} in VS Code ({p})."
    target = p if p.is_dir() or a not in _FILES else p.parent
    _open(str(target))  # xdg-open: a folder -> the file manager, a file -> its default app
    return f"Opened {target.name} in the file manager ({target})." if target.is_dir() else f"Opened {p.name} ({p})."
