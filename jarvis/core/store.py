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
CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY, ts REAL NOT NULL, device TEXT NOT NULL, lat REAL, lon REAL,
    accuracy INTEGER, source TEXT, place TEXT
);
CREATE INDEX IF NOT EXISTS idx_loc_device_ts ON locations(device, ts);
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
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY, start REAL NOT NULL, end REAL, turns INTEGER DEFAULT 0, summary TEXT,
    channel TEXT, extracted INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_start ON sessions(start);
CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY, text TEXT NOT NULL, kind TEXT DEFAULT 'reminder', next_run REAL,
    repeat TEXT DEFAULT 'none', created REAL, last_run REAL, enabled INTEGER DEFAULT 1, note TEXT
);
CREATE INDEX IF NOT EXISTS idx_schedules_due ON schedules(enabled, next_run);
CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL, tag TEXT DEFAULT '', priority INTEGER DEFAULT 2,
    due REAL, due_time INTEGER DEFAULT 0, note TEXT DEFAULT '', created REAL NOT NULL, done_at REAL,
    reminder_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_todos_open ON todos(done_at, due);
CREATE TABLE IF NOT EXISTS profile (
    key TEXT PRIMARY KEY, value TEXT NOT NULL, source TEXT, created REAL, updated REAL,
    hits INTEGER DEFAULT 0, last_used REAL
);
CREATE TABLE IF NOT EXISTS errors (
    sig TEXT PRIMARY KEY, error TEXT, kind TEXT, explanation TEXT, fix TEXT, where_ TEXT,
    count INTEGER DEFAULT 1, first_seen REAL, last_seen REAL
);
CREATE TABLE IF NOT EXISTS job_state (
    job_id INTEGER PRIMARY KEY, fn TEXT NOT NULL, params TEXT, state TEXT, caps TEXT,
    used_s REAL DEFAULT 0, owner TEXT, paused INTEGER DEFAULT 0, origin TEXT, updated REAL
);
CREATE TABLE IF NOT EXISTS job_queue (
    n INTEGER PRIMARY KEY, text TEXT NOT NULL, status TEXT DEFAULT 'waiting', created REAL, updated REAL,
    tries INTEGER DEFAULT 0, note TEXT DEFAULT '', job_id INTEGER
);
CREATE TABLE IF NOT EXISTS job_steps (
    id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL, ts REAL NOT NULL, text TEXT, tokens INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_job_steps_job ON job_steps(job_id, id);
"""
# P7: FTS5 over chat messages (external content, kept in sync by triggers).
_MESSAGES_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(text, content='messages', content_rowid='id',
    tokenize='porter unicode61');
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
"""

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
_path: Path | None = None


def init(db_path: str | Path | None = None) -> Path:
    """(Re)open the database at db_path (default config.DB_PATH) and ensure the schema."""
    global _conn, _path, _session_id
    with _lock:
        close()
        _session_id = None
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
    added = {  # P7: STT audio seconds, message sessions, note importance
        "llm_calls": (("audio_s", "REAL DEFAULT 0"),),
        "messages": (("session", "INTEGER"),),
        "notes": (("hits", "INTEGER DEFAULT 0"), ("last_used", "REAL")),
    }
    for table, new_cols in added.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col, decl in new_cols:
            if col not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    fresh = not conn.execute("SELECT 1 FROM sqlite_master WHERE name='messages_fts'").fetchone()
    conn.executescript(_MESSAGES_FTS)
    if fresh:  # index messages stored before P7
        conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")


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
            latency_ms: int, ok: bool, error: str = "", estimated: bool = False,
            audio_s: float = 0.0) -> None:
    p, c = int(prompt_tokens or 0), int(completion_tokens or 0)
    if purpose != "stt":
        from jarvis.core import trace
        trace.on_llm(model, purpose, p, c, latency_ms, ok, error)
    _exec("INSERT INTO llm_calls(ts,model,purpose,prompt_tokens,completion_tokens,total_tokens,"
          "latency_ms,ok,error,estimated,audio_s) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
          (time.time(), model, purpose, p, c, p + c, int(latency_ms), int(bool(ok)),
           (error or "")[:500], int(bool(estimated)), float(audio_s or 0.0)))


def log_tool(tool: str, args: Any, ok: bool, latency_ms: int, safety: str = "safe",
             error: str = "", outcome: str = "", result: str = "") -> None:
    """Action log. outcome: allowed | denied | blocked | error (empty for legacy callers)."""
    from jarvis.core import trace
    trace.on_tool(tool, args, ok, latency_ms, outcome, result or error, safety)
    _exec("INSERT INTO tool_calls(ts,tool,args,ok,latency_ms,safety,error,outcome,result) "
          "VALUES (?,?,?,?,?,?,?,?,?)",
          (time.time(), tool, json.dumps(args, default=str)[:2000], int(bool(ok)),
           int(latency_ms), safety, (error or "")[:500], outcome or ("allowed" if ok else "error"),
           (result or "")[:1000]))


def location_add(device: str, lat: float, lon: float, accuracy: int = 0, source: str = "",
                 place: str = "", ts: float | None = None) -> int:
    row = _exec("INSERT INTO locations(ts,device,lat,lon,accuracy,source,place) VALUES (?,?,?,?,?,?,?)",
                (ts or time.time(), device, float(lat), float(lon), int(accuracy or 0), source, place))
    return _exec("SELECT last_insert_rowid() AS id")[0]["id"]


def locations_since(device: str, since: float, limit: int = 2000) -> list[dict]:
    rows = _exec("SELECT * FROM locations WHERE device=? AND ts>=? ORDER BY ts ASC LIMIT ?",
                 (device, since, int(limit)))
    return [dict(r) for r in rows]


def location_last(device: str) -> dict | None:
    rows = _exec("SELECT * FROM locations WHERE device=? ORDER BY ts DESC LIMIT 1", (device,))
    return dict(rows[0]) if rows else None


def locations_clear(device: str | None = None) -> int:
    before = _exec("SELECT COUNT(*) AS n FROM locations" + ("" if device is None else " WHERE device=?"),
                   () if device is None else (device,))[0]["n"]
    _exec("DELETE FROM locations" + ("" if device is None else " WHERE device=?"),
          () if device is None else (device,))
    return before


def locations_prune(keep_days: float) -> int:
    cutoff = time.time() - keep_days * 86400
    n = _exec("SELECT COUNT(*) AS n FROM locations WHERE ts<?", (cutoff,))[0]["n"]
    _exec("DELETE FROM locations WHERE ts<?", (cutoff,))
    return n


def log_routing(query: str, groups: list[str], method: str, latency_ms: int) -> None:
    _exec("INSERT INTO routing(ts,query,groups,method,latency_ms) VALUES (?,?,?,?,?)",
          (time.time(), query[:500], json.dumps(list(groups)), method, int(latency_ms)))


def add_message(role: str, text: str, session: int | None = None) -> None:
    """session defaults to the current chat session (see session_start)."""
    _exec("INSERT INTO messages(ts,role,text,session) VALUES (?,?,?,?)",
          (time.time(), role, text, session if session is not None else _session_id))


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


# --- KURAMA's job list (jarvis/core/jobqueue.py) ---
QUEUE_FIELDS = ("text", "status", "tries", "note", "job_id")


def queue_add(text: str) -> int:
    with _lock:
        if _conn is None:
            init(_path)
        now = time.time()
        return int(_conn.execute("INSERT INTO job_queue(text, status, created, updated) VALUES (?,?,?,?)",  # type: ignore[union-attr]
                                 (text, "waiting", now, now)).lastrowid)


def queue_list(statuses: tuple[str, ...] | None = None) -> list[dict]:
    if statuses:
        rows = _exec(f"SELECT * FROM job_queue WHERE status IN ({','.join('?' * len(statuses))}) ORDER BY n", statuses)
    else:
        rows = _exec("SELECT * FROM job_queue ORDER BY n")
    return [dict(r) for r in rows]


def queue_get(n: int) -> dict | None:
    rows = _exec("SELECT * FROM job_queue WHERE n=?", (n,))
    return dict(rows[0]) if rows else None


def queue_update(n: int, **fields: Any) -> None:
    cols = [k for k in fields if k in QUEUE_FIELDS]
    if cols:
        _exec(f"UPDATE job_queue SET {', '.join(c + '=?' for c in cols)}, updated=? WHERE n=?",
              tuple(fields[c] for c in cols) + (time.time(), n))


def queue_delete(n: int) -> None:
    _exec("DELETE FROM job_queue WHERE n=?", (n,))


def queue_delete_status(statuses: tuple[str, ...]) -> int:
    k = len(queue_list(statuses))
    _exec(f"DELETE FROM job_queue WHERE status IN ({','.join('?' * len(statuses))})", statuses)
    return k


# --- long jobs (jarvis/core/longjobs.py): durable state, checkpoints, step log ---
JOB_STATE_FIELDS = ("fn", "params", "state", "caps", "used_s", "owner", "paused", "origin")


def job_state_insert(job_id: int, **fields: Any) -> None:
    cols = ["job_id", "updated"] + [k for k in fields if k in JOB_STATE_FIELDS]
    vals = (job_id, time.time()) + tuple(fields[k] for k in cols[2:])
    _exec(f"INSERT OR REPLACE INTO job_state({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)


def job_state_update(job_id: int, **fields: Any) -> None:
    cols = [k for k in fields if k in JOB_STATE_FIELDS]
    if cols:
        _exec(f"UPDATE job_state SET {', '.join(c + '=?' for c in cols)}, updated=? WHERE job_id=?",
              tuple(fields[c] for c in cols) + (time.time(), job_id))


def job_state_get(job_id: int) -> dict | None:
    rows = _exec("SELECT * FROM job_state WHERE job_id=?", (job_id,))
    return dict(rows[0]) if rows else None


def job_state_ids() -> set[int]:
    return {int(r[0]) for r in _exec("SELECT job_id FROM job_state")}


def job_state_claim(job_id: int, old_owner: str | None, new_owner: str) -> bool:
    """Compare-and-swap the owner (one process resumes a job, never two)."""
    with _lock:
        if _conn is None:
            init(_path)
        cur = _conn.execute("UPDATE job_state SET owner=?, updated=? WHERE job_id=? AND owner IS ?",  # type: ignore[union-attr]
                            (new_owner, time.time(), job_id, old_owner))
        return cur.rowcount == 1


def job_step_add(job_id: int, text: str, tokens: int = 0, keep: int = 300) -> None:
    with _lock:
        if _conn is None:
            init(_path)
        cur = _conn.execute("INSERT INTO job_steps(job_id, ts, text, tokens) VALUES (?,?,?,?)",  # type: ignore[union-attr]
                            (job_id, time.time(), text, tokens))
        if cur.lastrowid and cur.lastrowid % 50 == 0:  # prune now and then: the newest `keep` steps per job
            _conn.execute("DELETE FROM job_steps WHERE job_id=? AND id <= (SELECT id FROM job_steps WHERE "  # type: ignore[union-attr]
                          "job_id=? ORDER BY id DESC LIMIT 1 OFFSET ?)", (job_id, job_id, keep))


def job_steps(job_id: int, limit: int = 20) -> list[dict]:
    rows = _exec("SELECT ts, text, tokens FROM job_steps WHERE job_id=? ORDER BY id DESC LIMIT ?", (job_id, limit))
    return [dict(r) for r in reversed(rows)]


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


# --- clipboard history (what the user copies: the clipboard_watch worker, plus KURAMA's own copies) ---
def clip_add(text: str, keep: int | None = None) -> int:
    keep = int(keep or config.CLIPBOARD_HISTORY_MAX)
    with _lock:
        if _conn is None:
            init(_path)
        cur = _conn.execute("INSERT INTO clipboard(text,created) VALUES (?,?)", (text, time.time()))  # type: ignore[union-attr]
        _conn.execute("DELETE FROM clipboard WHERE id NOT IN "  # type: ignore[union-attr]
                      "(SELECT id FROM clipboard ORDER BY id DESC LIMIT ?)", (keep,))
        _conn.execute("DELETE FROM clipboard WHERE created < ?",  # type: ignore[union-attr]
                      (time.time() - config.CLIPBOARD_KEEP_H * 3600,))
        return int(cur.lastrowid)


def clip_search(query: str = "", minutes_ago: float = 0, limit: int = 5) -> list[dict]:
    """Copies containing all the words of `query` (newest first), or the ones nearest to `minutes_ago`."""
    since = time.time() - config.CLIPBOARD_KEEP_H * 3600
    rows = [dict(r) for r in _exec("SELECT * FROM clipboard WHERE created >= ? ORDER BY id DESC LIMIT 500", (since,))]
    words = [w for w in (query or "").lower().split() if w]
    if words:
        rows = [r for r in rows if all(w in r["text"].lower() for w in words)]
    if minutes_ago:
        at = time.time() - minutes_ago * 60
        rows.sort(key=lambda r: abs(r["created"] - at))
    return rows[:limit]


def clip_clear() -> int:
    with _lock:
        if _conn is None:
            init(_path)
        return int(_conn.execute("DELETE FROM clipboard").rowcount)  # type: ignore[union-attr]


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


# --- chat sessions (P7 session recall) ---
_session_id: int | None = None


def session_start(channel: str = "", ts: float | None = None) -> int:
    """Open a new chat session and make it the current one for add_message."""
    global _session_id
    t = ts or time.time()
    with _lock:
        if _conn is None:
            init(_path)
        cur = _conn.execute("INSERT INTO sessions(start,end,turns,summary,channel) VALUES (?,?,0,'',?)",  # type: ignore[union-attr]
                            (t, t, channel))
        _session_id = int(cur.lastrowid)
    return _session_id


def current_session() -> int | None:
    return _session_id


def messages_other_channels(channel: str, since: float, limit: int = 6) -> list[dict]:
    """Recent messages from KURAMA's other channels (laptop "" vs "telegram"), oldest first."""
    rows = _exec("SELECT m.role, m.text, m.ts, s.channel FROM messages m JOIN sessions s ON m.session = s.id "
                 "WHERE COALESCE(s.channel, '') != ? AND m.ts >= ? ORDER BY m.id DESC LIMIT ?",
                 (channel or "", since, int(limit)))
    return [dict(r) for r in reversed(rows)]


def session_latest(channel: str) -> dict | None:
    """The most recent session of a channel ("telegram", ...), to carry a chat over a restart."""
    rows = _exec("SELECT * FROM sessions WHERE channel=? ORDER BY start DESC LIMIT 1", (channel,))
    return dict(rows[0]) if rows else None


def session_touch(session_id: int, turns: int = 1) -> None:
    _exec("UPDATE sessions SET end=?, turns=turns+? WHERE id=?", (time.time(), int(turns), session_id))


def session_update(session_id: int, summary: str | None = None, extracted: bool | None = None) -> None:
    if summary is not None:
        _exec("UPDATE sessions SET summary=? WHERE id=?", (summary, session_id))
    if extracted is not None:
        _exec("UPDATE sessions SET extracted=? WHERE id=?", (int(extracted), session_id))


def session_get(session_id: int) -> dict | None:
    rows = _exec("SELECT * FROM sessions WHERE id=?", (session_id,))
    return dict(rows[0]) if rows else None


def sessions_between(t0: float, t1: float, min_turns: int = 1) -> list[dict]:
    rows = _exec("SELECT * FROM sessions WHERE start>=? AND start<? AND turns>=? ORDER BY start",
                 (t0, t1, min_turns))
    return [dict(r) for r in rows]


def sessions_recent(limit: int = 5, exclude: int | None = None, min_turns: int = 1) -> list[dict]:
    rows = _exec("SELECT * FROM sessions WHERE id IS NOT ? AND turns>=? ORDER BY start DESC LIMIT ?",
                 (exclude, min_turns, int(limit)))
    return [dict(r) for r in rows]


def messages_between(t0: float, t1: float, role: str | None = None, limit: int = 500) -> list[dict]:
    if role:
        rows = _exec("SELECT id,ts,role,text,session FROM messages WHERE ts>=? AND ts<? AND role=? "
                     "ORDER BY id LIMIT ?", (t0, t1, role, int(limit)))
    else:
        rows = _exec("SELECT id,ts,role,text,session FROM messages WHERE ts>=? AND ts<? ORDER BY id "
                     "LIMIT ?", (t0, t1, int(limit)))
    return [dict(r) for r in rows]


def session_messages(session_id: int, role: str | None = None, limit: int = 200) -> list[dict]:
    sql = "SELECT id,ts,role,text FROM messages WHERE session=?" + (" AND role=?" if role else "")
    params: tuple = (session_id, role) if role else (session_id,)
    return [dict(r) for r in _exec(sql + " ORDER BY id LIMIT ?", params + (int(limit),))]


def messages_search(fts_query: str, limit: int = 8, exclude_session: int | None = None) -> list[dict]:
    """FTS5 match over past messages (best first). fts_query is an FTS5 expression."""
    try:
        rows = _exec("SELECT m.id,m.ts,m.role,m.text,m.session FROM messages_fts f "
                     "JOIN messages m ON m.id=f.rowid WHERE messages_fts MATCH ? "
                     "AND (? IS NULL OR m.session IS NOT ?) ORDER BY bm25(messages_fts) LIMIT ?",
                     (fts_query, exclude_session, exclude_session, int(limit)))
    except sqlite3.OperationalError:
        return []
    return [dict(r) for r in rows]


# --- user profile facts (P7 tiered memory) ---
def profile_set(key: str, value: str, source: str = "") -> bool:
    """Insert or REPLACE the fact for key. True if it was new or changed."""
    now = time.time()
    old = _exec("SELECT value FROM profile WHERE key=?", (key,))
    if old and old[0][0] == value:
        _exec("UPDATE profile SET last_used=? WHERE key=?", (now, key))
        return False
    _exec("INSERT INTO profile(key,value,source,created,updated,hits,last_used) VALUES (?,?,?,?,?,0,?) "
          "ON CONFLICT(key) DO UPDATE SET value=excluded.value, source=excluded.source, "
          "updated=excluded.updated, last_used=excluded.last_used", (key, value, source, now, now, now))
    return True


def profile_get(key: str) -> str | None:
    rows = _exec("SELECT value FROM profile WHERE key=?", (key,))
    return rows[0][0] if rows else None


def profile_all() -> list[dict]:
    return [dict(r) for r in _exec("SELECT * FROM profile ORDER BY updated DESC")]


def profile_delete(key: str) -> bool:
    with _lock:
        if _conn is None:
            init(_path)
        return _conn.execute("DELETE FROM profile WHERE key=?", (key,)).rowcount > 0  # type: ignore[union-attr]


def profile_touch(keys: list[str]) -> None:
    now = time.time()
    for k in keys:
        _exec("UPDATE profile SET hits=hits+1, last_used=? WHERE key=?", (now, k))


# --- range readers (P7 usage report + daily digest) ---
def llm_usage_between(t0: float, t1: float) -> list[dict]:
    """Per (model, purpose): calls, ok calls, prompt/completion/total tokens, audio seconds."""
    rows = _exec("SELECT model, purpose, COUNT(*) AS calls, SUM(ok) AS ok_calls, "
                 "COALESCE(SUM(prompt_tokens),0) AS prompt, COALESCE(SUM(completion_tokens),0) AS completion, "
                 "COALESCE(SUM(total_tokens),0) AS total, COALESCE(SUM(audio_s),0) AS audio_s "
                 "FROM llm_calls WHERE ts>=? AND ts<? GROUP BY model, purpose", (t0, t1))
    return [dict(r) for r in rows]


def routing_count(method: str, t0: float, t1: float) -> int:
    return int(_exec("SELECT COUNT(*) FROM routing WHERE method=? AND ts>=? AND ts<?", (method, t0, t1))[0][0])


def jobs_finished_between(t0: float, t1: float, status: str = "done") -> list[dict]:
    rows = _exec("SELECT * FROM jobs WHERE status=? AND finished>=? AND finished<? ORDER BY finished",
                 (status, t0, t1))
    return [dict(r) for r in rows]


def alerts_between(t0: float, t1: float) -> list[dict]:
    rows = _exec("SELECT * FROM alerts WHERE ts>=? AND ts<? ORDER BY ts", (t0, t1))
    return [dict(r) for r in rows]


def notes_between(t0: float, t1: float) -> list[dict]:
    rows = _exec("SELECT * FROM notes WHERE created>=? AND created<? ORDER BY created", (t0, t1))
    return [dict(r) for r in rows]


# --- P9b: reminders / scheduled commands ---
SCHEDULE_FIELDS = ("text", "kind", "next_run", "repeat", "last_run", "enabled", "note")


# --- to-dos: tasks the user has to do (never ring by themselves; an optional linked reminder does) ---
TODO_FIELDS = ("title", "tag", "priority", "due", "due_time", "note", "done_at", "reminder_id")


def todo_add(title: str, tag: str = "", priority: int = 2, due: float | None = None, due_time: bool = False,
             note: str = "", created: float | None = None) -> int:
    with _lock:
        if _conn is None:
            init(_path)
        cur = _conn.execute("INSERT INTO todos(title,tag,priority,due,due_time,note,created) VALUES (?,?,?,?,?,?,?)",  # type: ignore[union-attr]
                            (title, tag, int(priority), due, int(bool(due_time)), note, created or time.time()))
        return int(cur.lastrowid)


def todo_update(todo_id: int, **fields: Any) -> None:
    cols = [k for k in fields if k in TODO_FIELDS]
    if cols:
        _exec(f"UPDATE todos SET {', '.join(c + '=?' for c in cols)} WHERE id=?",
              tuple(fields[c] for c in cols) + (int(todo_id),))


def todo_get(todo_id: int) -> dict | None:
    rows = _exec("SELECT * FROM todos WHERE id=?", (int(todo_id),))
    return dict(rows[0]) if rows else None


def todos_open() -> list[dict]:
    """Open to-dos in list order: overdue/dated first (soonest), then undated; high priority first within a day."""
    rows = _exec("SELECT * FROM todos WHERE done_at IS NULL ORDER BY due IS NULL, due, priority, created")
    return [dict(r) for r in rows]


def todos_done_between(t0: float, t1: float) -> list[dict]:
    return [dict(r) for r in _exec("SELECT * FROM todos WHERE done_at>=? AND done_at<? ORDER BY done_at", (t0, t1))]


def todos_clear_done() -> int:
    with _lock:
        if _conn is None:
            init(_path)
        return _conn.execute("DELETE FROM todos WHERE done_at IS NOT NULL").rowcount  # type: ignore[union-attr]


def todo_delete(todo_id: int) -> bool:
    with _lock:
        if _conn is None:
            init(_path)
        return _conn.execute("DELETE FROM todos WHERE id=?", (int(todo_id),)).rowcount > 0  # type: ignore[union-attr]


def schedule_add(text: str, kind: str, next_run: float, repeat: str = "none", created: float | None = None,
                 note: str = "") -> int:
    with _lock:
        if _conn is None:
            init(_path)
        cur = _conn.execute("INSERT INTO schedules(text,kind,next_run,repeat,created,enabled,note) "  # type: ignore[union-attr]
                            "VALUES (?,?,?,?,?,1,?)", (text, kind, next_run, repeat or "none", created or time.time(), note))
        return int(cur.lastrowid)


def schedule_update(sched_id: int, **fields: Any) -> None:
    cols = [k for k in fields if k in SCHEDULE_FIELDS]
    if cols:
        _exec(f"UPDATE schedules SET {', '.join(c + '=?' for c in cols)} WHERE id=?",
              tuple(fields[c] for c in cols) + (sched_id,))


def schedule_get(sched_id: int) -> dict | None:
    rows = _exec("SELECT * FROM schedules WHERE id=?", (sched_id,))
    return dict(rows[0]) if rows else None


def tool_counts_between(t0: float, t1: float, limit: int = 6) -> list[tuple[str, int]]:
    """Most used tools in [t0, t1) (for the day summary)."""
    return [(r[0], r[1]) for r in _exec("SELECT tool, COUNT(*) FROM tool_calls WHERE ts>=? AND ts<? AND tool IS NOT NULL "
                                        "GROUP BY tool ORDER BY 2 DESC LIMIT ?", (t0, t1, limit))]


def schedules_list(enabled_only: bool = True, limit: int = 50) -> list[dict]:
    where = "WHERE enabled=1 " if enabled_only else ""
    return [dict(r) for r in _exec(f"SELECT * FROM schedules {where}ORDER BY next_run LIMIT ?", (limit,))]


def schedules_due(now: float) -> list[dict]:
    return [dict(r) for r in _exec("SELECT * FROM schedules WHERE enabled=1 AND next_run<=? ORDER BY next_run",
                                   (now,))]


def schedule_delete(sched_id: int) -> bool:
    with _lock:
        if _conn is None:
            init(_path)
        return _conn.execute("DELETE FROM schedules WHERE id=?", (sched_id,)).rowcount > 0  # type: ignore[union-attr]


def kv_delete(key: str) -> None:
    _exec("DELETE FROM kv WHERE key=?", (key,))


def kv_prefix(prefix: str) -> dict[str, str]:
    rows = _exec("SELECT key, value FROM kv WHERE key LIKE ?", (prefix.replace("%", "") + "%",))
    return {r[0]: r[1] for r in rows}
