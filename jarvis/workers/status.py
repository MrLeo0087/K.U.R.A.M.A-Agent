"""Read the supervisor's status file (data/workers.json) so tools can tell what is running.

Stdlib + psutil only: imported by tools inside the main KURAMA process.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from jarvis.core import config

START_HINT = "venv/bin/python -m jarvis.workers"


def path() -> Path:
    return Path(config.WORKERS_STATUS_PATH)


def _alive(pid: int) -> bool:
    try:
        import psutil

        p = psutil.Process(pid)
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE and \
            any("jarvis.workers" in a for a in p.cmdline())
    except Exception:
        return False


def read() -> dict | None:
    """The status dict if a supervisor is alive, else None (a stale file is ignored)."""
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    pid = int(data.get("pid") or 0)
    if not pid or (pid != os.getpid() and not _alive(pid)):
        return None
    return data


def write(data: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({**data, "updated": round(time.time(), 1)}, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def remove() -> None:
    try:
        path().unlink()
    except OSError:
        pass


def running(name: str) -> bool:
    data = read()
    return bool(data and (data.get("workers") or {}).get(name, {}).get("state") == "running")


def worker_info(name: str) -> dict:
    data = read() or {}
    return ((data.get("workers") or {}).get(name) or {}).get("info") or {}


def summary() -> str:
    """One line: which workers run (or how to start them)."""
    data = read()
    if not data:
        return f"background workers: not running (start: {START_HINT})"
    ws = data.get("workers") or {}
    on = [n for n, w in ws.items() if w.get("state") == "running"]
    off = [f"{n} ({w.get('reason') or w.get('state')})" for n, w in ws.items() if w.get("state") != "running"]
    line = f"background workers (pid {data.get('pid')}): {', '.join(on) or 'none running'}"
    return line + (f"; skipped: {', '.join(off)}" if off else "")
