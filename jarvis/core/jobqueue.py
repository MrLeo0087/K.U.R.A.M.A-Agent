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
import threading
import time

from jarvis.core import config, store

log = logging.getLogger("jarvis.jobqueue")

WAITING, QUEUED, RUNNING, DONE, FAILED, SKIPPED = "waiting", "queued", "running", "done", "failed", "skipped"
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
    mark = {WAITING: "waiting", QUEUED: "queued to run", RUNNING: "working on it", DONE: "done", FAILED: "failed",
            SKIPPED: "skipped"}
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
    """Run the waiting jobs (or the ones numbered in `which`: "2", "1 2", "1, 3") one after another in the background.
    Starting more while it runs adds them to the same run."""
    from jarvis.core import jobs, longjobs
    nums = [int(x) for x in re.findall(r"\d+", which or "")]
    if nums:
        rows = [r for r in (store.queue_get(n) for n in nums) if r is not None]
        if not rows:
            return f"error: there's no job {which} in my list"
    else:
        rows = _rows((WAITING, FAILED))
    rows = [r for r in rows if r["status"] in (WAITING, FAILED)]
    if not rows:
        return "Nothing is waiting in my job list."
    for r in rows:
        store.queue_update(r["n"], status=QUEUED, note="")
    names = "; ".join(f"{r['n']}. {r['text'][:40]}" for r in rows[:5])
    if any(j.kind == "queue" for j in jobs.get_manager().active()):
        return f"Added to the run that's already going: {names}."
    job = longjobs.submit(f"job list run", run_queue, {}, kind="queue",
                          max_tokens=config.QUEUE_MAX_TOKENS, max_minutes=config.QUEUE_MAX_MINUTES)
    return (f"Starting {len(rows)} job(s) one by one (background job #{job.id}): {names}. I'll message you on the "
            "laptop and Telegram as each one finishes.")


def _tell(title: str, text: str, level: str = "info") -> None:
    try:
        from jarvis.core import notify
        notify.notify(title, text, level=level, source="jobs", telegram=True)
    except Exception as e:  # noqa: BLE001
        log.warning("job list notice failed: %s", e)


def _asker(n: int, text: str, asking: threading.Event):
    """A job that needs your yes asks on Telegram and waits QUEUE_ASK_S (2 min); meanwhile the next job may start.
    No answer = no: the job is told it was declined and finds another way or stops honestly."""
    from jarvis.core import safety

    def confirm(prompt: str) -> bool:
        hook = safety.get_confirm("telegram")
        if hook is safety.deny_all:
            return False
        asking.set()
        try:
            question = f"Job {n} ({text[:60]}) needs your answer: {prompt}"
            try:
                return bool(hook(question, timeout=config.QUEUE_ASK_S))
            except TypeError:  # an older hook without a timeout
                return bool(hook(question))
        finally:
            asking.clear()
    return confirm


def _run_one(ctx, text: str, confirm=None) -> tuple[bool, str, str]:
    """One job through a background agent. (ok, short result, output path)."""
    from jarvis.core import agent, jobs, safety
    bot = agent.Agent(confirm=confirm or safety.deny_all, summarize_async=False, use_planner=True, persist=False)
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
                return False, "cancelled", ""
        if row.get("status") != "done":
            return False, f"job #{jid} {row.get('status')}: {(row.get('error') or row.get('progress') or '')[:200]}", ""
        path = row.get("output_path") or path
    if re.match(r"\s*(?:error|sorry, i couldn't|i can't|i couldn't)", answer or "", re.I):
        return False, answer[:300], path
    return True, (answer or "done")[:300], path


def _work(ctx, r: dict, asking: threading.Event, tally: dict) -> None:
    """One list job with retries (only on temporary failures) and its notices; runs in its own thread."""
    store.queue_update(r["n"], status=RUNNING, note="")
    _tell(f"KURAMA started job {r['n']}", r["text"])
    ok, out, path = False, "", ""
    for attempt in range(1, config.QUEUE_RETRIES + 1):
        ok, out, path = _run_one(ctx, r["text"], _asker(r["n"], r["text"], asking))
        store.queue_update(r["n"], tries=attempt)
        if ok or not _TEMPORARY.search(out) or ctx.job.cancel_event.is_set():
            break
        if ctx.job.cancel_event.wait(min(60, 10 * attempt)):
            break
    note = (out + (f" · {path}" if path else ""))[:400]
    if ok:
        tally["done"] += 1
        store.queue_update(r["n"], status=DONE, note=note, job_id=ctx.job.id)
        _tell(f"KURAMA finished job {r['n']}", f"{r['text']}\n{out}" + (f"\nSaved: {path}" if path else ""))
    else:
        tally["failed"] += 1
        store.queue_update(r["n"], status=FAILED if not ctx.job.cancel_event.is_set() else QUEUED, note=note,
                           job_id=ctx.job.id)
        if not ctx.job.cancel_event.is_set():
            _tell(f"KURAMA couldn't do job {r['n']}", f"{r['text']}\n{out}", level="warning")


def run_queue(ctx, params: dict) -> str | None:
    """Long-job body: the waiting jobs in order, one at a time; while a job waits for your answer on Telegram, the
    next one starts (at most QUEUE_PARALLEL at once). Retries and notices per job, a summary at the end."""
    tally = {"done": 0, "failed": 0}
    active: dict[int, tuple[threading.Thread, threading.Event]] = {}
    while True:
        for n, (t, _) in list(active.items()):
            if not t.is_alive():
                del active[n]
        if ctx.job.cancel_event.is_set():
            if not active:
                break
            ctx.job.cancel_event.wait(1)
            continue
        waiting = [r for r in _rows((QUEUED,)) if r["n"] not in active]
        free = not active or (len(active) < config.QUEUE_PARALLEL and all(a.is_set() for _, a in active.values()))
        if waiting and free:
            r, asking = waiting[0], threading.Event()
            ctx.step(f"job {r['n']}: {r['text'][:60]}")
            t = threading.Thread(target=_work, args=(ctx, r, asking, tally), name=f"queue-{r['n']}", daemon=True)
            active[r["n"]] = (t, asking)
            t.start()
            continue
        if not waiting and not active:
            break
        ctx.checkpoint(**tally)
        ctx.job.cancel_event.wait(1)
    ctx.check()
    _tell("KURAMA job list finished", f"{tally['done']} done, {tally['failed']} failed. Say 'show my job list' for details.")
    return None
