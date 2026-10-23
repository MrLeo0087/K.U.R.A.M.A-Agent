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
