"""Conversation focus: the folder/file the user is currently talking about, so "send this folder" / "send it"
resolve to what was just discussed instead of a random match. Shared across processes via the kv store, so it
works whether the request comes from the dashboard or Telegram.
"""
from __future__ import annotations

import time

from jarvis.core import store

_KEY = "conversation_focus"
_MAX_AGE_S = 1800  # 30 min

ANAPHORA = {"this", "that", "it", "the", "this one", "that one", "them", "the folder", "this folder",
            "that folder", "the file", "this file", "that file", "same", "here", ""}


def set_path(path: str | None) -> None:
    """Remember the folder/file the conversation is about (the last one listed/opened/found)."""
    if not path:
        return
    try:
        store.kv_set(_KEY, str(path))
        store.kv_set(_KEY + "_ts", str(time.time()))
    except Exception:
        pass


def get_path(max_age_s: float = _MAX_AGE_S) -> str | None:
    try:
        p = store.kv_get(_KEY)
        ts = float(store.kv_get(_KEY + "_ts") or 0)
    except Exception:
        return None
    return p if p and (time.time() - ts) < max_age_s else None


def is_anaphora(text: str) -> bool:
    """True when `text` just points back ('this', 'it', 'that folder') rather than naming something."""
    import re
    t = re.sub(r"\b(?:folder|file|directory|dir|one|document|zip)\b", " ", (text or "").lower())
    t = " ".join(t.split()).strip(" .")
    return t in ANAPHORA
