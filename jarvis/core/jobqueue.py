"""KURAMA's job list: things YOU want KURAMA to do later (a to-do is for you, a job is for KURAMA).

add / list / edit / remove keep them without running anything; "start" runs the waiting ones one by one in a single
durable long job (longjobs.py: survives restarts, capped). Each job is a normal request run by a background agent
(no yes/no questions: anything that needs your yes is skipped and reported). A failed job is retried up to
QUEUE_RETRIES times only when the failure looks temporary (network, AI limits); every start / done / failure and a
final summary are sent to the laptop and Telegram. This is the input list the Night Agent will use later.
"""
from __future__ import annotations

import logging
import re
import time

from jarvis.core import config, store

log = logging.getLogger("jarvis.jobqueue")

WAITING, RUNNING, DONE, FAILED, SKIPPED = "waiting", "running", "done", "failed", "skipped"
_TEMPORARY = re.compile(r"rate limit|429|5\d\d|timeout|timed out|connection|network|temporar|overloaded|all models "
                        r"failed|LLMError", re.I)


def _rows(statuses: tuple[str, ...] | None = None) -> list[dict]:
    return store.queue_list(statuses)


_SPLIT = re.compile(r"(?:^|\s)\(?\d{1,2}[.)]\s+|\s*;\s*(?:add\s+)?|\n+")


def split_jobs(text: str) -> list[str]:
    """'1. weather 2. calculate ...' / 'weather; add calculate ...' -> one job each (the AI passed four as one)."""
    parts = [" ".join(p.split()).strip(" ,.") for p in _SPLIT.split(text or "")]
    return [p for p in parts if len(p) > 2] or ([" ".join((text or "").split())] if (text or "").strip() else [])


def add(text: str) -> str:
    items = split_jobs(text)
    if not items:
        return "error: say what the job is, e.g. 'add a job: write an essay about Nepal'"
    added = [(store.queue_add(t), t) for t in items]
    waiting = len(_rows((WAITING,)))
    what = "; ".join(f"{n}. {t}" for n, t in added)
    return (f"Added {len(added)} job(s) to my list ({waiting} waiting): {what}. Nothing runs until you say "
            "'start the jobs'.")


def result(n: str | int) -> str | None:
    """What job n of the LIST produced (None when the list has no job n)."""
    r = _find(n)
    if r is None:
        return None
    if r["status"] == WAITING:
        return f"Job {r['n']} ({r['text']}) hasn't run yet: it's waiting. Say 'start the jobs'."
    return f"Job {r['n']} ({r['text']}) is {r['status']}" + (f": {r['note']}" if r.get("note") else ".")


def show() -> str:
    rows = _rows()
    if not rows:
        return "My job list is empty. Add one with 'add a job: ...'."
    mark = {WAITING: "waiting", RUNNING: "working on it", DONE: "done", FAILED: "failed", SKIPPED: "skipped"}
    lines = [f"{r['n']}. {r['text']} — {mark.get(r['status'], r['status'])}"
             + (f" ({r['note'][:80]})" if r.get("note") and r["status"] != WAITING else "") for r in rows]
    return "My job list:\n" + "\n".join(lines)


def _find(n: str | int) -> dict | None:
    m = re.search(r"\d+", str(n))
    return store.queue_get(int(m.group())) if m else None


def edit(n: str | int, text: str) -> str:
    r = _find(n)
    if r is None:
        return f"error: there's no job {n} in my list"
    if r["status"] == RUNNING:
        return f"error: job {r['n']} is running now; cancel it first"
    text = " ".join((text or "").split())
    if not text:
        return "error: say the new text of the job"
    store.queue_update(r["n"], text=text, status=WAITING, note="", tries=0)
    return f"Job {r['n']} is now: {text}"


def remove(n: str | int) -> str:
    if str(n).strip().lower() in ("done", "finished", "completed"):
        k = store.queue_delete_status((DONE,))
        return f"Removed {k} finished job(s) from my list."
    r = _find(n)
    if r is None:
        return f"error: there's no job {n} in my list"
    if r["status"] == RUNNING:
        return f"error: job {r['n']} is running now; cancel it first"
    store.queue_delete(r["n"])
    return f"Removed job {r['n']}: {r['text']}"


def start(which: str = "") -> str:
    """Run the waiting jobs (or just job `which`) one after another in the background."""
    from jarvis.core import jobs, longjobs
    rows = _rows((WAITING, FAILED))
    if which.strip():
        r = _find(which)
        if r is None:
            return f"error: there's no job {which} in my list"
        rows = [r]
    rows = [r for r in rows if r["status"] in (WAITING, FAILED)]
    if not rows:
        return "Nothing is waiting in my job list."
    if any(j.kind == "queue" and j.status in jobs.ACTIVE for j in jobs.get_manager().active()):
        return "I'm already working through the job list; new waiting jobs are picked up as I go."
    for r in rows:
        store.queue_update(r["n"], status=WAITING, note="")
    job = longjobs.submit(f"job list: {len(rows)} job(s)", run_queue,
                          {"only": [r["n"] for r in rows], "new_too": not which.strip()}, kind="queue",
                          max_tokens=config.QUEUE_MAX_TOKENS, max_minutes=config.QUEUE_MAX_MINUTES)
    names = "; ".join(f"{r['n']}. {r['text'][:40]}" for r in rows[:5])
    return (f"Starting {len(rows)} job(s) one by one (background job #{job.id}): {names}. I'll message you on the "
            "laptop and Telegram as each one finishes.")


def _tell(title: str, text: str, level: str = "info") -> None:
    try:
        from jarvis.core import notify
        notify.notify(title, text, level=level, source="jobs", telegram=True)
    except Exception as e:  # noqa: BLE001
        log.warning("job list notice failed: %s", e)


def _run_one(ctx, text: str) -> tuple[bool, str, str]:
    """One job through a background agent. (ok, short result, output path)."""
    from jarvis.core import agent, jobs, safety
    bot = agent.Agent(confirm=safety.deny_all, summarize_async=False, use_planner=True, persist=False)
    before = set(jobs.get_manager().ids())
    try:
        answer = bot.run(text)
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}", ""
    started = sorted(set(jobs.get_manager().ids()) - before)  # an essay / image / code job: wait for its result
    path = ""
    for jid in started:
        while (row := store.job_get(jid) or {}).get("status") in jobs.ACTIVE:
            if ctx.job.cancel_event.wait(5):
                ctx.check()
            ctx.check()
        if row.get("status") != "done":
            return False, f"job #{jid} {row.get('status')}: {(row.get('error') or row.get('progress') or '')[:200]}", ""
        path = row.get("output_path") or path
    if re.match(r"\s*(?:error|sorry, i couldn't|i can't|i couldn't)", answer or "", re.I):
        return False, answer[:300], path
    return True, (answer or "done")[:300], path


def run_queue(ctx, params: dict) -> str | None:
    """Long-job body: the listed jobs in order (new waiting ones too), with retries and notices."""
    only = set(params.get("only") or [])
    done = failed = 0
    while True:
        ctx.check()
        rows = [r for r in _rows((WAITING,)) if params.get("new_too", True) or r["n"] in only]
        if not rows:
            break
        r = rows[0]
        store.queue_update(r["n"], status=RUNNING, note="")
        ctx.step(f"job {r['n']}: {r['text'][:60]}")
        _tell(f"KURAMA started job {r['n']}", r["text"])
        ok, out, path = False, "", ""
        for attempt in range(1, config.QUEUE_RETRIES + 1):
            ok, out, path = _run_one(ctx, r["text"])
            store.queue_update(r["n"], tries=attempt)
            if ok or not _TEMPORARY.search(out):  # only a temporary failure is worth another try
                break
            ctx.step(f"job {r['n']}: try {attempt} failed ({out[:60]}), retrying")
            if ctx.job.cancel_event.wait(min(60, 10 * attempt)):
                ctx.check()
        note = (out + (f" · {path}" if path else ""))[:400]
        if ok:
            done += 1
            store.queue_update(r["n"], status=DONE, note=note, job_id=ctx.job.id)
            _tell(f"KURAMA finished job {r['n']}", f"{r['text']}\n{out}" + (f"\nSaved: {path}" if path else ""))
        else:
            failed += 1
            store.queue_update(r["n"], status=FAILED, note=note, job_id=ctx.job.id)
            _tell(f"KURAMA couldn't do job {r['n']}", f"{r['text']}\n{out}", level="warning")
        ctx.checkpoint(done=done, failed=failed)
    _tell("KURAMA job list finished", f"{done} done, {failed} failed. Say 'show my job list' for details.")
    return None
