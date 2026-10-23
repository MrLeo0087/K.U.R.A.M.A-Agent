"""SQLite store (stdlib sqlite3, WAL, thread-safe) for LLM/tool/routing logs and chat messages."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from jarvis.core import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY, ts REAL NOT NULL, model TEXT, purpose TEXT,
    prompt_tokens INTEGER DEFAULT 0, completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0, latency_ms INTEGER, ok INTEGER, error TEXT,
    estimated INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_llm_ts ON llm_calls(ts);
CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY, ts REAL NOT NULL, tool TEXT, args TEXT, ok INTEGER,
    latency_ms INTEGER, safety TEXT, error TEXT, outcome TEXT, result TEXT
);
CREATE INDEX IF NOT EXISTS idx_tool_ts ON tool_calls(ts);
CREATE TABLE IF NOT EXISTS routing (
    id INTEGER PRIMARY KEY, ts REAL NOT NULL, query TEXT, groups TEXT, method TEXT,
    latency_ms INTEGER
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY, ts REAL NOT NULL, role TEXT, text TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY, title TEXT, kind TEXT, status TEXT, request TEXT, created REAL,
    finished REAL, output_path TEXT, error TEXT, tokens INTEGER DEFAULT 0, progress TEXT
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY, text TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS clipboard (
    id INTEGER PRIMARY KEY, text TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY, ts REAL NOT NULL, title TEXT, text TEXT, level TEXT, source TEXT,
    announced INTEGER DEFAULT 0, channels TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_pending ON alerts(announced, ts);
CREATE TABLE IF NOT EXISTS watches (
    id INTEGER PRIMARY KEY, kind TEXT, target TEXT, label TEXT, patterns TEXT, status TEXT,
    created REAL, finished REAL, state TEXT, result TEXT
);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY, value TEXT, ts REAL
);
"""

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
_path: Path | None = None


def init(db_path: str | Path | None = None) -> Path:
    """(Re)open the database at db_path (default config.DB_PATH) and ensure the schema."""
    global _conn, _path
    with _lock:
        close()
        _path = Path(db_path) if db_path else Path(config.DB_PATH)
        _path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_path), check_same_thread=False, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA)
        _migrate(conn)
        _conn = conn
        return _path


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after P1 to existing databases."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tool_calls)")}
    for col in ("outcome", "result"):
        if col not in cols:
            conn.execute(f"ALTER TABLE tool_calls ADD COLUMN {col} TEXT")


def close() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def _exec(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with _lock:
        if _conn is None:
            init(_path)
        return _conn.execute(sql, params).fetchall()


def _today_start() -> float:
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


# --- writers ---
def log_llm(model: str, purpose: str, prompt_tokens: int, completion_tokens: int,
            latency_ms: int, ok: bool, error: str = "", estimated: bool = False) -> None:
    p, c = int(prompt_tokens or 0), int(completion_tokens or 0)
    _exec("INSERT INTO llm_calls(ts,model,purpose,prompt_tokens,completion_tokens,total_tokens,"
          "latency_ms,ok,error,estimated) VALUES (?,?,?,?,?,?,?,?,?,?)",
          (time.time(), model, purpose, p, c, p + c, int(latency_ms), int(bool(ok)),
           (error or "")[:500], int(bool(estimated))))


def log_tool(tool: str, args: Any, ok: bool, latency_ms: int, safety: str = "safe",
             error: str = "", outcome: str = "", result: str = "") -> None:
    """Action log. outcome: allowed | denied | blocked | error (empty for legacy callers)."""
    _exec("INSERT INTO tool_calls(ts,tool,args,ok,latency_ms,safety,error,outcome,result) "
          "VALUES (?,?,?,?,?,?,?,?,?)",
          (time.time(), tool, json.dumps(args, default=str)[:2000], int(bool(ok)),
           int(latency_ms), safety, (error or "")[:500], outcome or ("allowed" if ok else "error"),
           (result or "")[:1000]))


def log_routing(query: str, groups: list[str], method: str, latency_ms: int) -> None:
    _exec("INSERT INTO routing(ts,query,groups,method,latency_ms) VALUES (?,?,?,?,?)",
          (time.time(), query[:500], json.dumps(list(groups)), method, int(latency_ms)))


def add_message(role: str, text: str) -> None:
    _exec("INSERT INTO messages(ts,role,text) VALUES (?,?,?)", (time.time(), role, text))


# --- readers ---
def recent_messages(n: int = 12) -> list[dict]:
    """Last n messages, oldest first, as {role, text, ts}."""
    rows = _exec("SELECT role,text,ts FROM messages ORDER BY id DESC LIMIT ?", (int(n),))
    return [dict(r) for r in reversed(rows)]


def tokens_today(model: str | None = None) -> int:
    """Total tokens used since local midnight, for one model or all models."""
    if model:
        rows = _exec("SELECT COALESCE(SUM(total_tokens),0) FROM llm_calls WHERE ts>=? AND model=?",
                     (_today_start(), model))
    else:
        rows = _exec("SELECT COALESCE(SUM(total_tokens),0) FROM llm_calls WHERE ts>=?",
                     (_today_start(),))
    return int(rows[0][0])


def tokens_by_model_today() -> dict[str, int]:
    rows = _exec("SELECT model, SUM(total_tokens) FROM llm_calls WHERE ts>=? GROUP BY model",
                 (_today_start(),))
    return {r[0]: int(r[1] or 0) for r in rows}


def recent_tool_calls(n: int = 20) -> list[dict]:
    """Last n tool calls, newest first."""
    rows = _exec("SELECT ts,tool,args,ok,latency_ms,safety,error,outcome,result FROM tool_calls "
                 "ORDER BY id DESC LIMIT ?", (int(n),))
    return [dict(r) for r in rows]


def recent_routing(n: int = 20) -> list[dict]:
    """Last n routing decisions, newest first (groups decoded)."""
    rows = _exec("SELECT ts,query,groups,method,latency_ms FROM routing ORDER BY id DESC LIMIT ?",
                 (int(n),))
    return [{**dict(r), "groups": json.loads(r["groups"] or "[]")} for r in rows]


def tool_call_counts(since_ts: float | None = None) -> dict[str, int]:
    rows = _exec("SELECT tool, COUNT(*) FROM tool_calls WHERE ts>=? GROUP BY tool ORDER BY 2 DESC",
                 (since_ts or 0.0,))
    return {r[0]: int(r[1]) for r in rows}


# --- background jobs ---
JOB_FIELDS = ("title", "kind", "status", "request", "created", "finished", "output_path", "error",
              "tokens", "progress")


def job_insert(title: str, kind: str, request: str = "", status: str = "queued") -> int:
    with _lock:
        if _conn is None:
            init()
        cur = _conn.execute("INSERT INTO jobs(title,kind,status,request,created,tokens,progress) "  # type: ignore[union-attr]
                            "VALUES (?,?,?,?,?,0,'')", (title, kind, status, request, time.time()))
        return int(cur.lastrowid)


def job_update(job_id: int, **fields: Any) -> None:
    cols = [k for k in fields if k in JOB_FIELDS]
    if not cols:
        return
    _exec(f"UPDATE jobs SET {', '.join(c + '=?' for c in cols)} WHERE id=?",
          tuple(fields[c] for c in cols) + (job_id,))


def job_get(job_id: int) -> dict | None:
    rows = _exec("SELECT * FROM jobs WHERE id=?", (job_id,))
    return dict(rows[0]) if rows else None


def jobs_list(limit: int = 10, statuses: tuple[str, ...] | None = None) -> list[dict]:
    if statuses:
        marks = ",".join("?" * len(statuses))
        rows = _exec(f"SELECT * FROM jobs WHERE status IN ({marks}) ORDER BY id DESC LIMIT ?",
                     (*statuses, limit))
    else:
        rows = _exec("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


def tokens_for_purpose(prefix: str) -> int:
    """Total tokens of llm_calls whose purpose starts with prefix (e.g. a job's 'job7:')."""
    rows = _exec("SELECT COALESCE(SUM(total_tokens),0) FROM llm_calls WHERE purpose LIKE ?",
                 (prefix.replace("%", "") + "%",))
    return int(rows[0][0])


# --- notes (remember / recall / forget) ---
def note_add(text: str) -> int:
    with _lock:
        if _conn is None:
            init(_path)
        cur = _conn.execute("INSERT INTO notes(text,created) VALUES (?,?)", (text, time.time()))  # type: ignore[union-attr]
        return int(cur.lastrowid)


def notes_recent(limit: int = 10, query: str = "") -> list[dict]:
    """Newest first; query filters by substring (case-insensitive)."""
    if query:
        like = "%" + query.replace("%", "").replace("_", "") + "%"
        rows = _exec("SELECT * FROM notes WHERE text LIKE ? ORDER BY id DESC LIMIT ?", (like, int(limit)))
    else:
        rows = _exec("SELECT * FROM notes ORDER BY id DESC LIMIT ?", (int(limit),))
    return [dict(r) for r in rows]


def notes_count() -> int:
    return int(_exec("SELECT COUNT(*) FROM notes")[0][0])


def note_delete(note_id: int) -> bool:
    with _lock:
        if _conn is None:
            init(_path)
        return _conn.execute("DELETE FROM notes WHERE id=?", (int(note_id),)).rowcount > 0  # type: ignore[union-attr]


def notes_clear() -> int:
    with _lock:
        if _conn is None:
            init(_path)
        return int(_conn.execute("DELETE FROM notes").rowcount)  # type: ignore[union-attr]


# --- clipboard history (only text Jarvis itself copied) ---
def clip_add(text: str, keep: int | None = None) -> int:
    keep = int(keep or config.CLIPBOARD_HISTORY_MAX)
    with _lock:
        if _conn is None:
            init(_path)
        cur = _conn.execute("INSERT INTO clipboard(text,created) VALUES (?,?)", (text, time.time()))  # type: ignore[union-attr]
        _conn.execute("DELETE FROM clipboard WHERE id NOT IN "  # type: ignore[union-attr]
                      "(SELECT id FROM clipboard ORDER BY id DESC LIMIT ?)", (keep,))
        return int(cur.lastrowid)


def clip_recent(limit: int = 5) -> list[dict]:
    """Newest first."""
    return [dict(r) for r in _exec("SELECT * FROM clipboard ORDER BY id DESC LIMIT ?", (int(limit),))]


# --- alerts (P6: notify() writes, the idle voice loop announces) ---
def alert_add(title: str, text: str, level: str = "info", source: str = "", channels: str = "") -> int:
    with _lock:
        if _conn is None:
            init(_path)
        cur = _conn.execute("INSERT INTO alerts(ts,title,text,level,source,announced,channels) "  # type: ignore[union-attr]
                            "VALUES (?,?,?,?,?,0,?)", (time.time(), title, text, level, source, channels))
        return int(cur.lastrowid)


def alerts_pending(limit: int = 5, levels: tuple[str, ...] | None = None) -> list[dict]:
    """Unannounced alerts, oldest first."""
    if levels:
        marks = ",".join("?" * len(levels))
        rows = _exec(f"SELECT * FROM alerts WHERE announced=0 AND level IN ({marks}) ORDER BY id LIMIT ?",
                     (*levels, limit))
    else:
        rows = _exec("SELECT * FROM alerts WHERE announced=0 ORDER BY id LIMIT ?", (limit,))
    return [dict(r) for r in rows]


def alerts_mark_announced(ids: list[int] | None = None, older_than: float | None = None) -> None:
    if ids:
        _exec(f"UPDATE alerts SET announced=1 WHERE id IN ({','.join('?' * len(ids))})", tuple(ids))
    if older_than is not None:
        _exec("UPDATE alerts SET announced=1 WHERE announced=0 AND ts<?", (older_than,))


def alerts_recent(limit: int = 10) -> list[dict]:
    return [dict(r) for r in _exec("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,))]


# --- watches (P6 process / log watcher; persist across restarts) ---
WATCH_FIELDS = ("status", "finished", "state", "result", "label")


def watch_add(kind: str, target: str, label: str = "", patterns: str = "", state: Any = None) -> int:
    with _lock:
        if _conn is None:
            init(_path)
        cur = _conn.execute("INSERT INTO watches(kind,target,label,patterns,status,created,state,result) "  # type: ignore[union-attr]
                            "VALUES (?,?,?,?,'active',?,?,'')",
                            (kind, target, label, patterns, time.time(), json.dumps(state or {})))
        return int(cur.lastrowid)


def watch_update(watch_id: int, **fields: Any) -> None:
    cols = [k for k in fields if k in WATCH_FIELDS]
    if not cols:
        return
    vals = tuple(json.dumps(fields[c]) if c == "state" and not isinstance(fields[c], str) else fields[c]
                 for c in cols)
    _exec(f"UPDATE watches SET {', '.join(c + '=?' for c in cols)} WHERE id=?", vals + (watch_id,))


def _watch_row(r: sqlite3.Row) -> dict:
    d = dict(r)
    try:
        d["state"] = json.loads(d.get("state") or "{}")
    except ValueError:
        d["state"] = {}
    return d


def watch_get(watch_id: int) -> dict | None:
    rows = _exec("SELECT * FROM watches WHERE id=?", (watch_id,))
    return _watch_row(rows[0]) if rows else None


def watches_list(statuses: tuple[str, ...] | None = None, limit: int = 50) -> list[dict]:
    if statuses:
        marks = ",".join("?" * len(statuses))
        rows = _exec(f"SELECT * FROM watches WHERE status IN ({marks}) ORDER BY id DESC LIMIT ?",
                     (*statuses, limit))
    else:
        rows = _exec("SELECT * FROM watches ORDER BY id DESC LIMIT ?", (limit,))
    return [_watch_row(r) for r in rows]


# --- tiny key/value (e.g. the Telegram update offset) ---
def kv_get(key: str, default: str | None = None) -> str | None:
    rows = _exec("SELECT value FROM kv WHERE key=?", (key,))
    return rows[0][0] if rows else default


def kv_set(key: str, value: str) -> None:
    _exec("INSERT INTO kv(key,value,ts) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
          "ts=excluded.ts", (key, value, time.time()))
