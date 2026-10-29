"""Request traces for improving KURAMA (see MONITORING.md): one row per request in data/traces.db.

    tr = trace.begin(text, mode, channel)   # at the start of Agent.run / Agent.stream
    ... every AI call (llm._log -> store.log_llm) and tool call (store.log_tool) made while the request runs is added
        to it through a context variable, so background workers and other requests never mix in ...
    trace.end(tr, answer, agent.last, error)  # writes the row (never raises)

Separate from jarvis.db on purpose: 'Reset KURAMA' does not wipe it (it is improvement data, not KURAMA's memory).
Rows older than config.TRACE_KEEP_DAYS are dropped once a day. Off with KURAMA_TRACING=0.
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
import sqlite3
import threading
import time
import uuid
from typing import Any

from jarvis.core import config

log = logging.getLogger(__name__)

_CUR: contextvars.ContextVar[dict | None] = contextvars.ContextVar("kurama_trace", default=None)
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_conn_path: str = ""
_pruned_day = ""

SCHEMA = """
CREATE TABLE IF NOT EXISTS traces(
  id TEXT PRIMARY KEY,
  ts REAL,                -- start (unix time)
  day TEXT,               -- YYYY-MM-DD (local)
  channel TEXT,           -- laptop | telegram | ... (empty = laptop UI / CLI)
  mode TEXT,              -- text | voice | talk
  text TEXT,              -- what the user said (as KURAMA received it, after speech-to-text)
  path TEXT,              -- fastpath | multi | ai | no_ai | error
  intent TEXT,            -- the shortcut's intent name (fastpath) or the first tool's name
  route_method TEXT,      -- rules | semantic | classifier | meta | fastpath | ...
  route_groups TEXT,      -- JSON list of the tool groups the router picked
  tools_sent TEXT,        -- JSON list of the tools the AI was given
  tools TEXT,             -- JSON list: {name, args, ok, ms, outcome, result}
  plan TEXT,              -- JSON: the multi-task split, if any
  tier TEXT,              -- fast | smart | voice
  llm_calls INTEGER,      -- AI calls made for this request
  tokens_in INTEGER, tokens_out INTEGER, tokens INTEGER,
  llm TEXT,               -- JSON list: {model, purpose, in, out, ms, ok, error}
  retried INTEGER,        -- 1 = the 'I can't' / claimed-action retry fired
  asked INTEGER,          -- 1 = a yes/no question was asked
  denied INTEGER,         -- 1 = the user said no
  jobs TEXT,              -- JSON list of background job ids started
  answer TEXT,            -- the reply (first 2000 chars)
  ms INTEGER,             -- total time to the reply
  error TEXT
);
CREATE INDEX IF NOT EXISTS traces_ts ON traces(ts);
CREATE INDEX IF NOT EXISTS traces_path ON traces(path);
"""


def _db() -> sqlite3.Connection:
    global _conn, _conn_path
    path = str(config.TRACE_DB)
    if _conn is None or _conn_path != path:
        config.TRACE_DB.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(path, check_same_thread=False, timeout=10, isolation_level=None)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(SCHEMA)
        _conn_path = path
    return _conn


def current() -> dict | None:
    return _CUR.get()


def begin(text: str, mode: str = "", channel: str = "", enabled: bool = True) -> dict | None:
    """Start a trace for this request (None when tracing is off)."""
    if not (enabled and config.TRACING):
        return None
    tr = {"id": uuid.uuid4().hex[:12], "ts": time.time(), "t0": time.monotonic(), "text": text, "mode": mode,
          "channel": channel, "llm": [], "tools": [], "done": False}
    tr["token"] = _CUR.set(tr)
    return tr


def resume(tr: dict | None) -> None:
    """Re-attach a trace after a generator is resumed in another context (the web server steps a streamed reply in
    worker threads, each with a fresh copy of the context)."""
    if tr is not None and not tr["done"]:
        _CUR.set(tr)


def on_llm(model: str, purpose: str, p: int, c: int, ms: int, ok: bool, error: str = "") -> None:
    tr = _CUR.get()
    if tr is not None and not tr["done"]:
        tr["llm"].append({"model": model, "purpose": purpose, "in": int(p or 0), "out": int(c or 0), "ms": ms,
                          "ok": bool(ok), **({"error": str(error)[:200]} if error else {})})


def on_tool(tool: str, args: Any, ok: bool, ms: int, outcome: str = "", result: str = "", safety: str = "") -> None:
    tr = _CUR.get()
    if tr is not None and not tr["done"]:
        try:
            a = args if isinstance(args, (dict, list, str, int, float, type(None))) else str(args)
            json.dumps(a)
        except (TypeError, ValueError):
            a = str(args)[:300]
        tr["tools"].append({"name": tool, "args": a, "ok": bool(ok), "ms": ms, "outcome": outcome,
                            "result": str(result or "")[:300], **({"safety": safety} if safety != "safe" else {})})


def _j(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, default=str) if v else ""


_PASSWORD = re.compile(r"(pass\S*\s*(?:is\s+|=\s*|:\s*)?)\S+", re.I)  # also typos: 'passeord is X'


def redact(text: str) -> str:
    """No passwords in the improvement data: 'password is X' -> 'password is [hidden]'; a bare unlock try -> hidden."""
    try:
        from jarvis.core import selfknow
        if selfknow.looks_like_password_try(text or ""):
            return "[password]"
    except Exception:  # noqa: BLE001
        pass
    return _PASSWORD.sub(r"\1[hidden]", text or "")


def end(tr: dict | None, answer: str = "", last: dict | None = None, error: str = "") -> None:
    """Write the trace row. Never raises: monitoring must not break a reply."""
    if tr is None or tr["done"]:
        return
    tr["done"] = True
    try:
        _CUR.reset(tr["token"])
    except (ValueError, RuntimeError):  # ended in another context (a generator closed elsewhere)
        pass
    try:
        last = last or {}
        route = last.get("route")
        tools = tr["tools"] or [{"name": t.get("name"), "ok": t.get("ok")} for t in last.get("tools") or []]
        real = [t for t in tools if t.get("name") != "request_tools"]
        if error:
            path = "error"
        elif last.get("fastpath"):
            path = "fastpath"
        elif last.get("plan") and len((last.get("plan") or {}).get("tasks") or []) > 1:
            path = "multi"
        elif tr["llm"]:
            path = "ai"
        else:
            path = "no_ai" if not real else "fastpath"
        tin = sum(x["in"] for x in tr["llm"])
        tout = sum(x["out"] for x in tr["llm"])
        outcomes = {t.get("outcome") for t in tools}
        row = (tr["id"], tr["ts"], time.strftime("%Y-%m-%d", time.localtime(tr["ts"])), tr["channel"] or "",
               tr["mode"] or "", redact(tr["text"] or "")[:2000], path,
               last.get("fastpath") or (real[0]["name"] if real else ""),
               getattr(route, "method", "") or "", _j(getattr(route, "groups", None)), _j(last.get("tools_sent")),
               _j(tools), _j(last.get("plan")), last.get("tier") or "", len(tr["llm"]), tin, tout, tin + tout,
               _j(tr["llm"]), int(bool(last.get("meta_retry"))),
               int(any(t.get("safety") == "confirm" for t in tools) or "denied" in outcomes or bool(last.get("denied"))),
               int("denied" in outcomes or bool(last.get("denied"))), _j(last.get("jobs")),
               redact(answer or "")[:2000], int((time.monotonic() - tr["t0"]) * 1000), (error or "")[:500])
        with _lock:
            db = _db()
            db.execute(f"INSERT OR REPLACE INTO traces VALUES ({','.join('?' * len(row))})", row)
            _prune(db)
        if not error:
            from jarvis.core import learn
            learn.on_turn({"text": row[5], "ts": tr["ts"], "path": path, "intent": row[7], "tools": tools})
    except Exception as e:
        log.warning("trace write failed: %s", e)


def _prune(db: sqlite3.Connection) -> None:
    global _pruned_day
    today = time.strftime("%Y-%m-%d")
    if _pruned_day != today:
        _pruned_day = today
        db.execute("DELETE FROM traces WHERE ts < ?", (time.time() - config.TRACE_KEEP_DAYS * 86400,))


def clear() -> int:
    """Delete every trace (a fresh start of the data, e.g. for a new version)."""
    with _lock:
        return _db().execute("DELETE FROM traces").rowcount
