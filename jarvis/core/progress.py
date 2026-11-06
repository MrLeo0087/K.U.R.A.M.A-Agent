"""Everything running right now, in one list, for the Progress section of the main and the mini window: background
jobs (writing, downloads, file sends, images, scans, the coding agent's plan and steps), the music that plays, and
what just finished (shown for a minute, then gone). 0 tokens; read on demand (GET /api/v1/progress).

Each item: {id, kind, title, status, detail, frac (0..1, or None = no known amount), job, steps, ts}.
A job tells its amount in its progress line ("3/7", "42%"); a job with a plan sets its steps (set_steps), each
"done" / "doing" / "todo", and the section draws them as a checklist (the coding agent: plan -> files -> run).
"""
from __future__ import annotations

import json
import re
import time

ACTIVE = ("queued", "running", "paused")
ENDED = ("done", "failed", "cancelled", "stopped")
SHOW_ENDED_S = 24 * 3600  # finished items stay as a history (owner 11-06: "which ones completed, which video I
ENDED_MAX = 15            # downloaded"): the last 24 h, the newest 15


def frac_of(progress: str, status: str) -> float | None:
    """'42%' -> 0.42, 'file 3/7' -> 0.43, done -> 1.0, else None (the bar moves without an amount)."""
    if status == "done":
        return 1.0
    t = progress or ""
    if m := re.search(r"(\d+(?:\.\d+)?)\s*%", t):
        return max(0.0, min(1.0, float(m.group(1)) / 100))
    if (m := re.search(r"\b(\d+)\s*/\s*(\d+)\b", t)) and int(m.group(2)):
        return max(0.0, min(1.0, int(m.group(1)) / int(m.group(2))))
    return None


def _steps_key(job_id: int) -> str:
    return f"job_steps:{job_id}"


def set_steps(job_id: int, steps: list[tuple[str, str]]) -> None:
    """A job's plan as a checklist: [(text, 'done' | 'doing' | 'todo' | 'failed')] (the coding agent)."""
    from jarvis.core import store
    try:
        store.kv_set(_steps_key(job_id), json.dumps([{"text": t[:120], "state": s} for t, s in steps][:30]))
    except Exception:  # noqa: BLE001 - progress is a bonus
        pass


def steps(job_id: int) -> list[dict]:
    from jarvis.core import store
    try:
        v = json.loads(store.kv_get(_steps_key(job_id)) or "[]")
        return v if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []


def _title(t: str) -> str:
    """'send file telegram: /media/leo/.../KURAMA' -> 'Send file telegram: KURAMA' (no long paths)."""
    t = re.sub(r"(/[^\s,:]+)+/([^/\s,:]+)", r"\2", t or "").strip()
    return (t[:1].upper() + t[1:])[:90] if t else "Working"


def _job_items(now: float) -> list[dict]:
    from jarvis.core import store
    rows = store.jobs_list(12, ACTIVE) + [r for r in store.jobs_list(ENDED_MAX, ENDED)
                                         if r.get("finished") and now - float(r["finished"]) <= SHOW_ENDED_S]
    out = []
    for r in rows:
        status = str(r.get("status") or "")
        detail = str(r.get("progress") or "").strip()
        if detail.startswith("» "):  # the job's own final sentence
            detail = detail[2:]
        if status == "failed" and r.get("error"):
            detail = str(r["error"])[:160]
        out.append({"id": f"job:{r['id']}", "kind": str(r.get("kind") or "job"), "job": int(r["id"]),
                    "title": _title(str(r.get("title") or "")), "status": status, "detail": detail[:200],
                    "frac": frac_of(detail, status), "steps": steps(int(r["id"])),
                    "ts": float(r.get("created") or 0), "output": r.get("output_path") or ""})
    return out


def _music() -> list[dict]:
    try:
        from jarvis.core import music
        s = music.state()
    except Exception:  # noqa: BLE001 - no player
        return []
    if not s:
        return []

    def mmss(x: float) -> str:
        return f"{int(x) // 60}:{int(x) % 60:02d}"
    dur = float(s.get("duration") or 0)
    return [{"id": "music", "kind": "music", "job": None, "title": s.get("title") or "Music",
             "status": "paused" if s.get("paused") else "playing",
             "detail": f"{mmss(s.get('pos') or 0)} / {mmss(dur)}" if dur else "", "frac": (s["pos"] / dur) if dur else None,
             "steps": [], "ts": 0.0, "output": "",
             "count": f"{s.get('index')}/{s.get('count')}" if (s.get("count") or 0) > 1 else ""}]


def items() -> list[dict]:
    """Running first (newest first), then paused / queued, then what just ended; music on top."""
    now = time.time()
    order = {"running": 0, "paused": 1, "queued": 2}
    jobs = sorted(_job_items(now), key=lambda x: (order.get(x["status"], 3), -x["ts"]))
    for j in jobs:  # (the finished ones: shown with when they finished)
        if j["status"] not in order and j.get("ts"):
            j["when"] = time.strftime("%H:%M", time.localtime(j["ts"]))
    return _music() + jobs
