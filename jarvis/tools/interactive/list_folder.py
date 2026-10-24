"""list_folder: what's inside one folder, as a numbered list (folders first, then files with size and date), so
the user can pick one: "send 3" / "send all" (handled by find_and_send's pick list, also on Telegram). Safe."""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from jarvis.core import store
from jarvis.core.registry import tool
from jarvis.tools.interactive import _proc

MAX_ITEMS = 60


def _size(n: int) -> str:
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{max(1, n // 1024)} KB"


@tool(group="filesearch", safety="safe",
      description="List the files in a folder (numbered, so the user can pick one to open or send).")
def list_folder(path: str, pattern: str = "", hidden: bool = False) -> str:
    """List one folder (not recursive): sub-folders, then files newest first.

    Args:
        path: The folder; loose names work ("downloads", "project1 then tara", "Disk_D My Future").
        pattern: Optional part of the name or extension to keep (".pdf", "report").
        hidden: Include hidden files (names starting with a dot).
    """
    try:
        d = _proc.resolve_dir(path)
    except _proc.ProcError as e:
        return f"error: {e}"
    try:
        entries = [p for p in d.iterdir() if hidden or not p.name.startswith(".")]
    except OSError as e:
        return f"error: can't read {d}: {e.strerror}"
    pat = (pattern or "").lower().strip()
    if pat:
        entries = [p for p in entries if pat in p.name.lower()]
    dirs = sorted((p for p in entries if p.is_dir()), key=lambda p: p.name.lower())
    files = sorted((p for p in entries if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    if not dirs and not files:
        return f"{d} is empty" + (f" (nothing matching {pattern!r})" if pat else "")
    shown = files[:MAX_ITEMS]
    lines = [f"{d} : {len(dirs)} folders, {len(files)} files" + (f" (newest {MAX_ITEMS} shown)" if len(files) > MAX_ITEMS else "")]
    if dirs:
        lines.append("Folders: " + ", ".join(p.name for p in dirs[:30]) + (" ..." if len(dirs) > 30 else ""))
    for i, p in enumerate(shown, 1):
        st = p.stat()
        lines.append(f"{i}. {p.name} ({_size(st.st_size)}, {datetime.fromtimestamp(st.st_mtime):%d %b %Y})")
    # the numbers above are the pick list for "send 3" / "send all" (find_and_send / the Telegram bot)
    store.kv_set("found_files", json.dumps({"t": time.time(), "paths": [str(p) for p in shown]}))
    return "\n".join(lines)
