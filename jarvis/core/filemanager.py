"""The Files app (Nautilus) as context, like the VS Code file and the browser tab: which folder is open and what is
selected, used when Files is the app the user used most recently. scripts/kurama_fm.py does the reading (system
python3: GTK window stack, D-Bus, accessibility); on demand only, cached 2 s, ~0.1 s (+0.5 s with a selection read).
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path

from jarvis.core import config

log = logging.getLogger("jarvis.filemanager")
_cache: tuple[float, dict] = (0.0, {})
EMPTY = {"top": None, "folder": None, "selected": []}


def state() -> dict:
    """{'top': 'files'|'vscode'|'browser'|None, 'folder': str|None, 'selected': [abs paths]} (never raises)."""
    global _cache
    if time.monotonic() - _cache[0] < 2:
        return _cache[1]
    out = dict(EMPTY)
    if config.CONTEXT and config.FILES_CONTEXT:
        try:
            p = subprocess.run(["/usr/bin/python3", str(config.ROOT / "scripts" / "kurama_fm.py")],
                               capture_output=True, text=True, timeout=4)
            out.update(json.loads(p.stdout.strip().splitlines()[-1]))
        except Exception as e:  # noqa: BLE001 - context is a bonus
            log.debug("files context unavailable: %s", e)
    if out.get("top") == "files":  # evidence when "this folder" picks the wrong thing (kept small)
        try:
            path = config.LOG_DIR / "fm.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > 100_000:
                path.write_text("".join(path.read_text(encoding="utf-8").splitlines(True)[-300:]), encoding="utf-8")
            with path.open("a", encoding="utf-8") as fh:
                fh.write(time.strftime("%m-%d %H:%M:%S ") + json.dumps(
                    {k: out.get(k) for k in ("title", "folder", "selected", "folders", "sel_raw", "pick")}) + "\n")
        except OSError:
            pass
    _cache = (time.monotonic(), out)
    return out


def current() -> Path | None:
    """'this folder / this file / these': what the user points at in Files when Files is their latest app —
    the (first) selected item, else the open folder; None otherwise."""
    s = state()
    if s.get("top") != "files":
        return None
    for p in (s.get("selected") or [])[:1] + [s.get("folder")]:
        if p and Path(p).exists():
            return Path(p)
    return None


def line() -> str:
    """One sentence for the system prompt when Files is the latest app ('' otherwise)."""
    s = state()
    if s.get("top") != "files" or not s.get("folder"):
        return ""
    sel = s.get("selected") or []
    txt = f"Open in Files (the file manager): {s['folder']}."
    if sel:
        shown = ", ".join(sel[:5]) + (f" (+{len(sel) - 5} more)" if len(sel) > 5 else "")
        txt += f" Selected there: {shown} — 'this/these/it' means them."
    else:
        txt += " 'this folder/here' means it."
    return txt
