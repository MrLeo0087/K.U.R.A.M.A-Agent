"""The assistant's name (default KURAMA, changeable by the user) and the words it answers to.

Stored in the kv table, so a new name survives restarts. The wake word, command-name stripping and the
system prompt all read it from here.
"""
from __future__ import annotations

import re

from jarvis.core import config

_KEY = "assistant_name"
_cache: str | None = None


def name() -> str:
    global _cache
    if _cache is None:
        try:
            from jarvis.core import store
            _cache = (store.kv_get(_KEY) or "").strip() or config.ASSISTANT_NAME
        except Exception:
            _cache = config.ASSISTANT_NAME
    return _cache


def names() -> tuple[str, ...]:
    """Lower-case words the assistant answers to: its current name, plus "kurama" (the original)."""
    out = [name().lower()] + [n for n in config.ASSISTANT_NAMES if n != name().lower()]
    return tuple(dict.fromkeys(out))


def clean(new: str) -> str | None:
    n = re.sub(r"[^\w\s'-]", "", (new or "")).strip()
    return n if 2 <= len(n) <= 24 and len(n.split()) <= 2 else None


def set_name(new: str) -> str | None:
    """Save a new name; returns it, or None when it isn't a usable name."""
    global _cache
    n = clean(new)
    if not n:
        return None
    from jarvis.core import store
    store.kv_set(_KEY, n)
    _cache = n
    for mod in ("jarvis.core.fastpath", "jarvis.core.wake"):  # rebuild the name patterns if loaded
        import sys
        if (m := sys.modules.get(mod)) is not None and hasattr(m, "refresh_names"):
            m.refresh_names()
    return n
