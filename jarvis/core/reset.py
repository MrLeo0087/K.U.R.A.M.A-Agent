"""Clearing and resetting KURAMA, in layers (personal facts are kept unless you fully reset):

  clear_chat   : forget the current conversation (chat history + rolling summary), start a fresh chat.
  clear_recent : chat + reminders/alarms/timers + short-lived caches (weather/search/found files/focus).
  reset_all    : factory reset: every table in both databases emptied, results / saved tools / logs / personal sheets
                 moved to a dated backup. The password, .env and settings are NOT touched.

Agents keep history in memory, so callers pass their agent (or the Telegram bot / API clear its own) and we also
bump a kv "conversation_epoch" that every agent checks, so other processes drop their in-memory chat too.
"""
from __future__ import annotations

import time
from pathlib import Path

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


# kv rows that are settings or plumbing, not memories: kept by the full reset
KEEP_KV = frozenset(("power_mode", "semantic_mode", "hear_device_sound", "telegram_offset", "todos_migrated_from_sheet"))
KEEP_TABLES = frozenset(("config_snapshots",))
SHEETS = ("READ_LATER_FILE", "LINKS_FILE", "GOALS_FILE", "CONTACTS_FILE", "EXPENSES_FILE", "HABITS_FILE", "GOALS_DIR")


def _db_path() -> Path:
    return Path(store._path or store.init())


def _wipe_db(path, keep_tables=frozenset(), keep_kv=frozenset()) -> int:
    """Delete every row of every table (FTS indexes emptied too). Returns the rows removed."""
    import sqlite3
    if not Path(path).exists():
        return 0
    c = sqlite3.connect(str(path), timeout=30)
    n = 0
    try:
        names = [r[0] for r in c.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                 if r[0] not in keep_tables]
        fts = [x for x in names if c.execute("SELECT sql FROM sqlite_master WHERE name=?", (x,)).fetchone()[0]
               .upper().startswith("CREATE VIRTUAL TABLE")]
        shadow = {f"{t}_{x}" for t in fts for x in ("data", "idx", "content", "docsize", "config")}
        for t in names:
            if t in fts or t in shadow:
                continue
            if t == "kv" and keep_kv:
                q = ",".join("?" * len(keep_kv))
                n += c.execute(f"DELETE FROM kv WHERE key NOT IN ({q})", tuple(keep_kv)).rowcount
            else:
                n += c.execute(f'DELETE FROM "{t}"').rowcount  # (the tables' triggers keep their FTS index in step)
        for t in fts:  # then make sure each search index is empty
            c.execute(f'INSERT INTO "{t}"("{t}") VALUES(\'delete-all\')')
        c.commit()
    finally:
        c.close()
    return n


def _backup(stamp: str) -> list[str]:
    """Everything the reset removes is MOVED (not deleted) to a backup first, so a mistake can be undone."""
    import shutil
    import sqlite3

    from jarvis.core import config
    out = []
    dest = _db_path().parent / "reset-backups" / stamp
    dest.mkdir(parents=True, exist_ok=True)
    for db in (_db_path(), config.MEMORY_DB_PATH):
        if Path(db).exists():
            src = sqlite3.connect(str(db), timeout=30)
            try:
                with sqlite3.connect(str(dest / Path(db).name)) as dst:
                    src.backup(dst)
            finally:
                src.close()
    for d in (config.OUTPUTS_DIR, config.SKILLS_DIR, config.LOG_DIR):
        if Path(d).is_dir() and any(Path(d).iterdir()):
            shutil.move(str(d), str(dest / Path(d).name))
            Path(d).mkdir(parents=True, exist_ok=True)
    out.append(str(dest))
    files = [f for f in (Path(str(getattr(config, k))).expanduser() for k in SHEETS) if f.exists()]
    if files:  # the personal sheets (money, habits, goals, links, contacts, reading list)
        to = files[0].parent.parent / f"KURAMA-backup-{stamp}"
        to.mkdir(parents=True, exist_ok=True)
        for f in files:
            shutil.move(str(f), str(to / f.name))
        out.append(str(to))
    return out


def reset_all(agent=None) -> str:
    """Factory reset: a brand-new KURAMA. Every chat, fact, reminder, to-do, alert, log, result, saved tool, indexed
    document and personal sheet is gone from KURAMA (moved to a dated backup first). Kept: the password, .env keys,
    settings (power mode, understanding model), and Telegram's read position (old messages are not answered again)."""
    from jarvis.core import config
    if agent is not None:
        agent.clear_conversation()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    saved = _backup(stamp)
    rows = _wipe_db(_db_path(), KEEP_TABLES, KEEP_KV) + _wipe_db(config.MEMORY_DB_PATH)
    bump_epoch()
    return (f"KURAMA is brand new: I forgot every chat, fact, reminder, to-do, alert and result ({rows} records). "
            f"A backup is in {saved[0]}" + (f" and {saved[1]}" if len(saved) > 1 else "") + ".")
