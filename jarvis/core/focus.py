"""Conversation focus = KURAMA's "current folder": the folder/file the user is talking about right now, plus a short
history, so follow-ups work like a shell's cwd:

  "list files in Final_RAG" -> then "now list data"      ("data" is looked up inside Final_RAG first)
  "open it" / "send this folder" / "list files here"     (the current folder)
  "go to the previous folder"                            (the one before)
  "the parent folder"                                     (one level up)

Every file tool that lists/opens/finds/creates a folder or file calls set_path(). Shared across processes via the
kv store (dashboard, voice and Telegram see the same focus). Kept for config.FOCUS_TTL_H hours.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from jarvis.core import config, store

_KEY = "conversation_focus"
_HIST = "focus_history"
_MAX_AGE_S = 1800  # "send it" right after a find: only a recent focus counts for sending
_HIST_LEN = 10

ANAPHORA = {"this", "that", "it", "the", "this one", "that one", "them", "the folder", "this folder",
            "that folder", "the file", "this file", "that file", "same", "here", "there", "", "current",
            "the current", "current folder", "this directory", "the same", "same folder", "that path", "this path"}
_PREV = re.compile(r"^(?:the\s+)?(?:previous|last|old|earlier|prior|before)(?:\s+(?:one|folder|directory|path))?$|"
                   r"^(?:the\s+)?(?:folder|one)\s+before$", re.I)
_PARENT = re.compile(r"^(?:the\s+)?(?:parent|upper|up|one\s+level\s+up|level\s+up)(?:\s+(?:folder|directory|one))?$", re.I)


def _history() -> list[dict]:
    try:
        return json.loads(store.kv_get(_HIST) or "[]")
    except (ValueError, TypeError):
        return []


def set_path(path: str | Path | None) -> None:
    """Remember the folder/file the conversation is about (the last one listed/opened/found/made)."""
    if not path:
        return
    p = str(Path(str(path)).expanduser())
    try:
        now = time.time()
        store.kv_set(_KEY, p)
        store.kv_set(_KEY + "_ts", str(now))
        hist = [h for h in _history() if h.get("p") != p]
        store.kv_set(_HIST, json.dumps(([{"p": p, "t": now}] + hist)[:_HIST_LEN]))
    except Exception:
        pass


def get_path(max_age_s: float = _MAX_AGE_S) -> str | None:
    """The latest focus (file or folder) if it is recent enough."""
    try:
        p = store.kv_get(_KEY)
        ts = float(store.kv_get(_KEY + "_ts") or 0)
    except Exception:
        return None
    return p if p and (time.time() - ts) < max_age_s else None


def _dir_of(p: str) -> Path | None:
    q = Path(p)
    if q.is_dir():
        return q
    if q.is_file():
        return q.parent
    return None


def cwd() -> Path | None:
    """The current folder (a focused file counts as its folder), if it still exists and isn't stale."""
    now, ttl = time.time(), config.FOCUS_TTL_H * 3600
    for h in _history():
        if now - float(h.get("t", 0)) > ttl:
            break
        if d := _dir_of(h["p"]):
            return d
    return None


def previous() -> Path | None:
    """The folder before the current one."""
    cur, now, ttl = cwd(), time.time(), config.FOCUS_TTL_H * 3600
    for h in _history():
        if now - float(h.get("t", 0)) > ttl:
            break
        d = _dir_of(h["p"])
        if d and d != cur:
            return d
    return None


def is_anaphora(text: str) -> bool:
    """True when `text` just points back ('this', 'it', 'that folder', 'here') rather than naming something."""
    t = re.sub(r"\b(?:folder|file|directory|dir|one|document|doc|zip|selected|highlighted|image|photo|picture|pic|"
               r"screenshot|video|clip|song|audio|pdf|md|txt|markdown|essay|report|note|notes|script|wallpaper|drawing)\b", " ",
               (text or "").lower())
    t = " ".join(t.split()).strip(" .")
    return t in ANAPHORA


def said_path() -> Path | None:
    """The one existing absolute path written in the user's current message, if there is exactly one."""
    import re
    try:
        from jarvis.core import safety
        said = str(safety.context().get("user_text", "") or "")
    except Exception:  # noqa: BLE001
        return None
    found = {Path(m.rstrip(".,;:!?)\"'")) for m in re.findall(r"(?<![\w~])(/[^\s\"']+|~/[^\s\"']+)", said)}
    real = [p.expanduser() for p in found if p.expanduser().exists()]
    return real[0] if len(real) == 1 else None


def refer(text: str) -> Path | None:
    """'this/it/here' -> current folder, 'previous folder' -> the one before, 'parent folder' -> one up; else None."""
    t = " ".join((text or "").lower().split()).strip(" .?")
    if not t or is_anaphora(t):
        if (pasted := said_path()) is not None:  # "/home/leo/Documents  organize this folder": that path
            return pasted
        from jarvis.core import workmem
        kind = workmem.kind_named(t)
        if kind and kind not in ("folder", "file"):  # "that image", "the pdf": the newest thing of that kind or nothing
            return workmem.latest(kind)  # (never some folder: "send that image" must not send the Files folder)
        # something KURAMA made/touched a moment ago ("make folder X ... open it") beats the Files app
        if (fresh := workmem.latest("folder" if kind == "folder" else "", config.WORKMEM_FRESH_S)) is not None:
            return fresh
        try:  # the Files app, when it is the latest app: its selected item, else its open folder
            from jarvis.core import filemanager
            if (fm := filemanager.current()) is not None:
                return fm
            if filemanager.state().get("top") == "vscode":  # VS Code is the app in use: its project folder
                from jarvis.core import context  # (11-02: 'create a new file in this project' went to /home/leo)
                snap = context.snapshot()
                root = Path(snap.get("root") or "") if snap.get("root") else (
                    snap["file"].parent if snap.get("file") else None)
                if root is not None and root.is_dir():
                    return root
        except Exception:  # noqa: BLE001
            pass
        if (p := get_path(config.FOCUS_TTL_H * 3600)) and Path(p).exists():
            return Path(p)
        return cwd()
    if _PREV.match(t):
        return previous()
    if _PARENT.match(t):
        c = cwd()
        return c.parent if c else None
    return None
