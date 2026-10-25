"""Clearing and resetting KURAMA, in layers (personal facts are kept unless you fully reset):

  clear_chat   : forget the current conversation (chat history + rolling summary), start a fresh chat.
  clear_recent : chat + reminders/alarms/timers + short-lived caches (weather/search/found files/focus).
  reset_all    : everything clear_recent does, PLUS the learned personal facts (profile) and session history —
                 KURAMA starts brand new. The password hash and config are NOT touched.

Agents keep history in memory, so callers pass their agent (or the Telegram bot / API clear its own) and we also
bump a kv "conversation_epoch" that every agent checks, so other processes drop their in-memory chat too.
"""
from __future__ import annotations

import time

from jarvis.core import store

EPOCH_KEY = "conversation_epoch"  # agents compare this; a bump means "forget the in-memory chat"
_CACHE_KEYS = ("weather_cache", "search_cache", "found_files", "conversation_focus", "conversation_focus_ts",
               "colab_since")


def bump_epoch() -> int:
    n = int(store.kv_get(EPOCH_KEY) or "0") + 1
    store.kv_set(EPOCH_KEY, str(n))
    return n


def epoch() -> int:
    return int(store.kv_get(EPOCH_KEY) or "0")


def _clear_caches() -> None:
    for k in _CACHE_KEYS:
        try:
            store.kv_set(k, "")
        except Exception:
            pass


def clear_chat(agent=None) -> str:
    """Forget the current conversation; keep reminders and personal facts."""
    if agent is not None:
        agent.clear_conversation()
    bump_epoch()
    return "Chat cleared — fresh conversation. (Your reminders and what I know about you are kept.)"


def clear_reminders() -> int:
    """Delete all reminders, alarms, timers and the scheduled items. Returns how many were removed."""
    rows = store.schedules_list(enabled_only=False, limit=500)
    n = 0
    for r in rows:
        if store.schedule_delete(r["id"]):
            n += 1
    return n


def clear_recent(agent=None) -> str:
    """Chat + reminders/alarms/timers + caches. Keeps personal facts."""
    if agent is not None:
        agent.clear_conversation()
    n = clear_reminders()
    _clear_caches()
    bump_epoch()
    return (f"Cleared: this chat, {n} reminder/alarm/timer{'s' if n != 1 else ''}, and cached data. "
            "What I know about you (your name, notes you asked me to remember) is kept — say 'reset KURAMA' to wipe that too.")


def reset_all(agent=None) -> str:
    """Full reset: chat, reminders, caches AND learned personal facts/profile. Password and config are kept."""
    if agent is not None:
        agent.clear_conversation()
    n = clear_reminders()
    _clear_caches()
    facts = 0
    try:
        facts = store.notes_clear()
    except Exception:
        pass
    try:  # wipe the learned profile (home city, name facts, preferences), keep the password hash
        store._exec("DELETE FROM profile WHERE key NOT LIKE 'secret_%' AND key != 'password_hash'")
    except Exception:
        pass
    bump_epoch()
    return (f"KURAMA reset. Forgot this chat, {n} scheduled item{'s' if n != 1 else ''}, {facts} saved note"
            f"{'s' if facts != 1 else ''}, caches and learned facts. Starting fresh. (Your password and settings are kept.)")
