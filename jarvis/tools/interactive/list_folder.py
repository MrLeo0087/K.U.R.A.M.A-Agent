"""list_folder: what's inside one or more folders, as a numbered list (folders first, then files with size and date), so
the user can pick one: "send 3" / "send all" (handled by find_and_send's pick list, also on Telegram). Safe."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

from jarvis.core import store
from jarvis.core.registry import tool
from jarvis.tools.interactive import _proc

MAX_ITEMS = 60


def _size(n: int) -> str:
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{max(1, n // 1024)} KB"


def _targets(path: str) -> tuple[list[Path], list[str]]:
    """Folders to list and notes. "project1 and tara" is Tara inside Project1 when it exists there, else both;
    a name that isn't found exactly falls back to the closest folder (and says so)."""
    from jarvis.core.paths import similar_dirs, smart_path

    parts = [p for p in re.split(r"\s*(?:,|&|\band\b)\s*", path or "", flags=re.I) if p.strip()]
    if len(parts) > 1 and (nested := smart_path(" then ".join(parts), want="dir")) is not None:
        return [nested.resolve()], []
    dirs, notes = [], []
    for part in parts or [path]:
        try:
            dirs.append(_proc.resolve_dir(part))
            continue
        except _proc.ProcError:
            pass
        near = similar_dirs(part)
        if near:
            dirs.append(near[0])
            more = ", ".join(str(p) for p in near[1:3])
            notes.append(f"No folder is called {part!r} exactly; showing the closest, {near[0]}"
                         + (f" (also similar: {more})" if more else "") + ".")
        else:
            notes.append(f"error: no folder like {part!r} found")
    return list(dict.fromkeys(dirs)), notes


def _list_one(d: Path, pat: str, hidden: bool, start: int) -> tuple[list[str], list[Path]]:
    try:
        entries = [p for p in d.iterdir() if hidden or not p.name.startswith(".")]
    except OSError as e:
        return [f"error: can't read {d}: {e.strerror}"], []
    if pat:
        entries = [p for p in entries if pat in p.name.lower()]
    dirs = sorted((p for p in entries if p.is_dir()), key=lambda p: p.name.lower())
    files = sorted((p for p in entries if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    if not dirs and not files:
        return [f"{d} is empty" + (f" (nothing matching {pat!r})" if pat else "")], []
    shown = files[:MAX_ITEMS]
    lines = [f"{d} : {len(dirs)} folders, {len(files)} files" + (f" (newest {MAX_ITEMS} shown)" if len(files) > MAX_ITEMS else "")]
    if dirs:
        lines.append("Folders: " + ", ".join(p.name for p in dirs[:30]) + (" ..." if len(dirs) > 30 else ""))
    for i, p in enumerate(shown, start):
        st = p.stat()
        lines.append(f"{i}. {p.name} ({_size(st.st_size)}, {datetime.fromtimestamp(st.st_mtime):%d %b %Y})")
    return lines, shown


@tool(group="filesearch", safety="safe",
      description="List the files and folders inside one or more folders (numbered, so the user can pick one to open or send).")
def list_folder(path: str, pattern: str = "", hidden: bool = False) -> str:
    """List folders (not recursive): sub-folders, then files newest first. Loose or misspelled names work.

    Args:
        path: The folder(s); loose names work ("downloads", "project1 and tara", "Disk_D My Future", "music, videos").
        pattern: Optional part of the name or extension to keep (".pdf", "report").
        hidden: Include hidden files (names starting with a dot).
    """
    dirs, notes = _targets(path)
    if not dirs:
        return notes[0] if notes else f"error: not a folder: {path}"
    lines, picks = [n for n in notes if not n.startswith("error")], []
    for d in dirs[:4]:
        got, shown = _list_one(d, (pattern or "").lower().strip(), hidden, len(picks) + 1)
        lines += got + [""]
        picks += shown
    lines += [n for n in notes if n.startswith("error")]
    # the numbers above are the pick list for "send 3" / "send all" (find_and_send / the Telegram bot)
    store.kv_set("found_files", json.dumps({"t": time.time(), "paths": [str(p) for p in picks]}))
    return "\n".join(lines).strip()
