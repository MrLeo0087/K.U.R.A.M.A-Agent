"""find_and_send: find a file by name anywhere on the laptop (home + every mounted disk) and send it to the
user's Telegram. One match is sent at once; several are listed with numbers ("send 2", "send all"); no match
falls back to similar names. Safe: it only ever sends to the owner's own chat (TELEGRAM_CHAT_ID).

No longer a tool of its own: the merged tool calls find_and_send() (old name kept as an alias)."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

from jarvis.core import config, store
from jarvis.tools.general import _tg

LAST_KEY = "found_files"  # the numbered list from the last search, for "send 2" / "all"
LAST_TTL_S = 1800
MAX_LIST = 10
MAX_ALL = 5


def _size(n: int) -> str:
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{max(1, n // 1024)} KB"


def _line(i: int, p: Path) -> str:
    try:
        st = p.stat()
        meta = f"{_size(st.st_size)}, {datetime.fromtimestamp(st.st_mtime):%d %b %Y}"
    except OSError:
        meta = "?"
    home = str(Path.home())
    shown = "~" + str(p)[len(home):] if str(p).startswith(home) else str(p)
    return f"{i}. {p.name} ({meta})\n   {shown}"


def search(query: str) -> list[Path]:
    from jarvis.core.paths import all_disks
    from jarvis.tools.interactive.find_files import search_names

    found, _ = search_names(query, all_disks(), MAX_LIST)
    return [Path(f) for f in found]


def last_list() -> list[Path]:
    try:
        d = json.loads(store.kv_get(LAST_KEY, "") or "{}")
    except ValueError:
        return []
    return [Path(p) for p in d.get("paths", [])] if time.time() - d.get("t", 0) < LAST_TTL_S else []


def send_paths(paths: list[Path]) -> str:
    from jarvis.tools.general.send_file_telegram import check_path, deliver

    out = []
    for p in paths:
        try:
            out.append(deliver(check_path(str(p))))
        except ValueError as e:
            out.append(f"error: {e}")
    return "\n".join(out)


def _picked(paths: list[Path], pick: int) -> str:
    if pick == -1:
        return send_paths(paths[:MAX_ALL])
    if not 1 <= pick <= len(paths):
        return f"error: pick a number from 1 to {len(paths)}"
    return send_paths([paths[pick - 1]])


def find_and_send(name: str = "", pick: int = 0) -> str:
    """Search home and every disk for a file name and send it. Several matches: lists them numbered; call
    again with pick=N (or pick=-1 for all) to send from that list.

    Args:
        name: File name or part of it ("naruto.jpg", "naruto", "*.pdf"). Empty when pick refers to the last list.
        pick: 0 = search; N = send item N of the last list; -1 = send all of them (max 5).
    """
    if err := _tg.ready():
        return err
    pick = int(pick or 0)
    name = (name or "").strip().strip("\"'")
    if name and Path(name).expanduser().is_file():  # a full path: just send it
        return send_paths([Path(name).expanduser()])
    if pick and not name:
        paths = last_list()
        if not paths:
            return "error: no recent search to pick from; tell me the file name"
        return _picked(paths, pick)
    if not name:
        return "error: tell me the file name to look for"
    name = Path(name).name if "/" in name else name  # "/wrong/dir/x.py" -> look for x.py everywhere
    paths, note = search(name), ""
    if paths and pick:  # "send all the X files" / "send the 2nd one" in one go
        store.kv_set(LAST_KEY, json.dumps({"t": time.time(), "paths": [str(p) for p in paths]}))
        return _picked(paths, pick)
    if not paths:  # "naruto.jpg" -> anything named like "naruto"
        stem = re.sub(r"\.[a-z0-9]{1,5}$", "", Path(name).name, flags=re.I)
        if stem and stem != name:
            paths, note = search(stem), f"No file named exactly {name}, but I found similar ones:\n"
    if not paths:
        return f"I couldn't find any file named like {name!r} in your home folder or on your disks."
    if len(paths) == 1 and not note:
        return send_paths(paths)
    store.kv_set(LAST_KEY, json.dumps({"t": time.time(), "paths": [str(p) for p in paths]}))
    head = note or f"I found {len(paths)}{'+' if len(paths) == MAX_LIST else ''} files matching {name!r}:\n"
    return head + "\n".join(_line(i, p) for i, p in enumerate(paths, 1)) + \
        "\nReply with a number to send it, or 'all' to send them all."
