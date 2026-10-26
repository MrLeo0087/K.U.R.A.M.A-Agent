"""Background jobs: JobManager singleton (ThreadPoolExecutor, SQLite `jobs` table, cancel events,
progress strings, on_done callbacks) and the Announcer (text: print; voice: queue a short spoken
line for when KURAMA is idle; plus a notify-send desktop notification when available).

Every job thread runs inside ratelimit.context("background", cancel) so its LLM calls are paced
behind interactive replies. LLM calls use purpose "job<N>:<step>", so job tokens come from llm_calls.
"""
from __future__ import annotations

import collections
import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from jarvis.core import config, ratelimit, store

log = logging.getLogger("jarvis.jobs")

ACTIVE = ("queued", "running")
INTERRUPTED_QUIT = "interrupted (KURAMA quit)"
INTERRUPTED_RESTART = "interrupted (KURAMA restarted)"


class JobCancelled(Exception):
    """Raised inside a job when its cancel event is set."""


@dataclass
class Job:
    id: int
    title: str
    kind: str
    request: str = ""
    lang: str = "en"
    status: str = "queued"
    progress: str = ""
    output_path: str = ""
    error: str = ""
    tokens: int = 0
    origin: str = ""  # "telegram" when asked from the phone: the result goes back there
    created: float = field(default_factory=time.time)
    finished: float | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    future: Future | None = field(default=None, repr=False)

    def describe(self) -> str:
        extra = f", {self.progress}" if self.progress and self.status in ACTIVE else ""
        out = f", saved to {self.output_path}" if self.output_path and self.status == "done" else ""
        err = f", {self.error[:80]}" if self.error and self.status == "failed" else ""
        return f"#{self.id} {self.status}: {self.title}{extra}{out}{err}"


class JobContext:
    """What a job function gets: cancel checks, progress, output path, purpose names."""

    def __init__(self, job: Job, manager: "JobManager"):
        self.job, self._m = job, manager

    @property
    def cancelled(self) -> bool:
        return self.job.cancel_event.is_set()

    def check(self) -> None:
        if self.cancelled:
            raise JobCancelled(f"job #{self.job.id} cancelled")

    def purpose(self, step: str) -> str:
        return f"job{self.job.id}:{step}"

    def progress(self, text: str) -> None:
        self.job.progress = text
        self._m._save(self.job, progress=text, tokens=self.refresh_tokens())

    def set_output(self, path: str | Path) -> None:
        self.job.output_path = str(path)
        self._m._save(self.job, output_path=str(path))

    def refresh_tokens(self) -> int:
        try:
            self.job.tokens = store.tokens_for_purpose(f"job{self.job.id}:")
        except Exception as e:
            log.debug("token count failed: %s", e)
        return self.job.tokens


JobFn = Callable[[JobContext], "str | None"]


class JobManager:
    def __init__(self, max_workers: int | None = None):
        self.max_workers = max_workers or config.JOBS_MAX_WORKERS
        self._pool = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="job")
        self._jobs: dict[int, Job] = {}
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[Job], None]] = []
        try:  # jobs left running by a previous process can never finish
            for row in store.jobs_list(50, ACTIVE):
                store.job_update(row["id"], status="failed", error=INTERRUPTED_RESTART,
                                 finished=time.time())
        except Exception as e:
            log.warning("could not clean stale jobs: %s", e)

    # --- callbacks ---
    def on_done(self, cb: Callable[[Job], None]) -> None:
        if cb not in self._callbacks:
            self._callbacks.append(cb)

    def remove_callback(self, cb: Callable[[Job], None]) -> None:
        if cb in self._callbacks:
            self._callbacks.remove(cb)

    # --- lifecycle ---
    def submit(self, title: str, kind: str, fn: JobFn, request: str = "", lang: str = "en") -> Job:
        jid = store.job_insert(title, kind, request)
        job = Job(jid, title, kind, request, lang or "en")
        try:
            from jarvis.core import safety
            job.origin = safety.context().get("channel") or ""
        except Exception:
            pass
        if job.origin == "telegram":
            _send_after[jid] = True  # asked from the phone: the result itself goes back to the phone
        with self._lock:
            self._jobs[jid] = job
        try:  # the turn that started it lists it, so the UI watches it and announces / shows the result
            from jarvis.core import safety
            started = safety.context().get("jobs")
            if isinstance(started, list) and jid not in started:
                started.append(jid)
        except Exception:
            pass
        job.future = self._pool.submit(self._run, job, fn)
        log.info("started job #%d (%s): %s", jid, kind, title)
        return job

    def _save(self, job: Job, **fields) -> None:
        try:
            store.job_update(job.id, **fields)
        except Exception as e:
            log.warning("job #%d not saved: %s", job.id, e)

    def _run(self, job: Job, fn: JobFn) -> None:
        ctx = JobContext(job, self)
        if job.cancel_event.is_set():
            self._finish(job, ctx, "cancelled")
            return
        if not self._wait_resources(job):
            self._finish(job, ctx, "cancelled")
            return
        job.status = "running"
        self._save(job, status="running")
        try:
            with ratelimit.context(ratelimit.BACKGROUND, job.cancel_event):
                out = fn(ctx)
            if out:
                job.output_path = str(out)
            status = "cancelled" if job.cancel_event.is_set() else "done"
        except (JobCancelled, ratelimit.Cancelled):
            status = "cancelled"
        except Exception as e:  # a failing job must never take KURAMA down
            log.exception("job #%d failed", job.id)
            job.error = f"{type(e).__name__}: {e}"
            status = "cancelled" if job.cancel_event.is_set() else "failed"
        self._finish(job, ctx, status)

    def _wait_resources(self, job: Job) -> bool:
        """P9b: hold a queued job while RAM/CPU is short (re-check every JOB_RECHECK_S, at most
        JOB_MAX_WAIT_S, then run anyway with a note). False when the job was cancelled meanwhile."""
        if not config.JOB_RESOURCE_GATE:
            return True
        t0 = time.monotonic()
        while (reason := resource_wait_reason()):
            if time.monotonic() - t0 >= config.JOB_MAX_WAIT_S:
                job.progress = f"started anyway after waiting {config.JOB_MAX_WAIT_S / 60:.0f} min for free {reason}"
                self._save(job, progress=job.progress)
                log.info("job #%d: %s", job.id, job.progress)
                return True
            if job.progress != f"waiting for free {reason}":
                job.progress = f"waiting for free {reason}"
                self._save(job, progress=job.progress)
            if job.cancel_event.wait(config.JOB_RECHECK_S):
                return False
        if job.progress.startswith("waiting for free"):
            job.progress = ""
        return True

    def _finish(self, job: Job, ctx: JobContext, status: str) -> None:
        job.status, job.finished = status, time.time()
        ctx.refresh_tokens()
        self._save(job, status=status, finished=job.finished, output_path=job.output_path,
                   error=job.error[:500], tokens=job.tokens, progress=job.progress)
        if status == "done":
            store.kv_delete(f"job_resume:{job.id}")
        if _send_after.pop(job.id, False) and status == "done":
            send_output(job)
        for cb in list(self._callbacks):
            try:
                cb(job)
            except Exception as e:
                log.warning("job callback failed: %s", e)

    # --- queries ---
    def get(self, job_id: int) -> Job | None:
        with self._lock:
            job = self._jobs.get(int(job_id))
        if job is not None:
            return job
        row = store.job_get(int(job_id))
        return _from_row(row) if row else None

    def list(self, limit: int = 8) -> list[Job]:
        with self._lock:
            live = dict(self._jobs)
        rows = store.jobs_list(limit)
        return [live.get(r["id"]) or _from_row(r) for r in rows]

    def active(self) -> list[Job]:
        with self._lock:
            return [j for j in self._jobs.values() if j.status in ACTIVE]

    def find(self, query: str | int) -> Job | None:
        """A job by id ("3", "#3", "job 3") or by title words (active jobs first, newest first)."""
        q = str(query).strip().lower()
        digits = q.lstrip("#").replace("job", "").strip().lstrip("#")
        if digits.isdigit():
            return self.get(int(digits))
        words = [w for w in q.replace("#", " ").split() if w not in ("the", "a", "an", "job")]
        if not words:
            act = self.active()
            return max(act, key=lambda j: j.id) if act else None
        pool = sorted(self.list(20), key=lambda j: (j.status in ACTIVE, j.id), reverse=True)
        best, score = None, 0
        for j in pool:
            title = j.title.lower()
            s = sum(1 for w in words if w in title)
            if s > score:
                best, score = j, s
        return best

    def cancel(self, query: str | int) -> Job | None:
        job = self.find(query)
        if job is None or job.status not in ACTIVE:
            return job
        job.cancel_event.set()
        if job.future is not None and job.future.cancel():  # still queued: never runs
            self._finish(job, JobContext(job, self), "cancelled")
        return job

    def wait(self, job_id: int, timeout: float | None = None) -> Job | None:
        job = self.get(job_id)
        if job is not None and job.future is not None:
            try:
                job.future.result(timeout=timeout)
            except Exception:
                pass
        return job

    def shutdown(self, cancel: bool = True, wait: bool = False) -> None:
        if cancel:
            for j in self.active():
                j.error = j.error or INTERRUPTED_QUIT  # P9b: resumable writing jobs are offered on restart
                j.cancel_event.set()
        self._pool.shutdown(wait=wait, cancel_futures=cancel)


def _from_row(row: dict) -> Job:
    return Job(row["id"], row.get("title") or "", row.get("kind") or "", row.get("request") or "",
               status=row.get("status") or "", progress=row.get("progress") or "",
               output_path=row.get("output_path") or "", error=row.get("error") or "",
               tokens=row.get("tokens") or 0, created=row.get("created") or 0.0,
               finished=row.get("finished"))


# --- follow-ups: "make X and send it to my Telegram" ---
_send_after: dict[int, bool] = {}


def then_send(job_id: int) -> str:
    """Send this job's result to the user's Telegram when it is done (now, if it already is)."""
    job = get_manager().get(int(job_id))
    if job is None:
        return f"error: no job #{job_id}"
    if job.status == "done":
        return send_output(job)
    if job.status in ACTIVE:
        _send_after[job.id] = True
        return f"I'll send it to your Telegram as soon as job #{job.id} is ready."
    return f"error: job #{job.id} {job.status}, so there's nothing to send"


def send_output(job: "Job") -> str:
    """The job's output file to Telegram: pictures as photos, short text as a message, the rest as a file."""
    from jarvis.core import notify
    from jarvis.tools.general.send_file_telegram import deliver

    p = Path(job.output_path or "")
    if not p.is_file():
        return f"error: job #{job.id} has no file to send"
    if p.suffix.lower() in (".md", ".txt"):
        text = p.read_text(encoding="utf-8", errors="replace").strip()
        if len(text) <= config.TELEGRAM_MAX_REPLY_CHARS:
            return "Sent it to your Telegram." if notify.telegram_send(text) else "error: Telegram didn't accept it"
    out = deliver(p, caption=job.title[:200])
    if out.startswith("error"):
        log.warning("job #%d: %s", job.id, out)
    return out


# --- announcer ---
SPOKEN = {
    "done": {"en": "I've finished {title}. It's saved in your outputs folder.",
             "hi": "मैंने {title} पूरा कर लिया है।", "ne": "मैले {title} पूरा गरें।"},
    "failed": {"en": "Sorry, the background job {title} failed.",
               "hi": "माफ़ कीजिए, {title} वाला काम पूरा नहीं हो सका।",
               "ne": "माफ गर्नुहोस्, {title} को काम असफल भयो।"},
}


class Announcer:
    """on_done callback. mode "text" prints; "voice" queues speech for the idle voice loop."""

    def __init__(self) -> None:
        self.mode = "text"
        self._queue: collections.deque[tuple[str, str]] = collections.deque()

    def __call__(self, job: Job) -> None:
        if job.status == "cancelled":
            return
        where = f" -> {job.output_path}" if job.output_path else ""
        line = f"[job #{job.id} {job.status}] {job.title}{where}" + (
            f" ({job.error[:120]})" if job.status == "failed" and job.error else "")
        if self.mode == "voice":
            tpl = SPOKEN.get(job.status, SPOKEN["done"])
            self._queue.append((tpl.get(job.lang, tpl["en"]).format(title=job.title), job.lang))
            print(line, flush=True)
        else:
            print(f"\n{line}", flush=True)
        notify(job)

    def pop(self) -> tuple[str, str] | None:
        """Next (spoken text, lang) or None."""
        try:
            return self._queue.popleft()
        except IndexError:
            return None

    def pending(self) -> int:
        return len(self._queue)


ANNOUNCER = Announcer()


def notify(job: Job) -> None:
    """A finished / failed background job: desktop (config.JOBS_NOTIFY) and Telegram, so it reaches the user away
    from the laptop too."""
    if not config.JOBS_NOTIFY:
        return
    from jarvis.core import notify as _n

    if job.status == "done":
        title, text, level = f"✅ Done: {job.title}", f"Saved to {job.output_path}" if job.output_path else "", "info"
    else:
        title, text, level = f"Job failed: {job.title}", (job.error or "")[:300], "warning"
    # laptop jobs stay on the laptop (desktop + the UI's announcement); phone jobs get their result sent back
    # by then_send, so only a failure of a phone job needs a separate Telegram line
    phone = job.origin == "telegram" and job.status != "done"
    try:
        _n.notify(title, text, level=level, source="jobs", telegram=phone)
    except Exception as e:  # a notification must never break the job runner
        log.debug("job notify failed: %s", e)


def set_mode(mode: str) -> None:
    ANNOUNCER.mode = mode


# --- singleton ---
_manager: JobManager | None = None
_mlock = threading.Lock()


def get_manager() -> JobManager:
    global _manager
    with _mlock:
        if _manager is None:
            _manager = JobManager()
            _manager.on_done(ANNOUNCER)
        return _manager


def reset_manager() -> None:
    """Tests / shutdown: cancel everything and drop the singleton."""
    global _manager
    with _mlock:
        if _manager is not None:
            _manager.shutdown(cancel=True, wait=False)
        _manager = None


def shutdown() -> None:
    reset_manager()


def start_task(text: str, lang: str = "en") -> Job:
    """Submit a long task from the planner: writer for write/code requests, agent for scans."""
    from jarvis.core import planner, writer

    kind = planner.job_kind(text)
    title = planner.title_of(text)
    if kind == "scan":
        return get_manager().submit(title, kind, lambda ctx: _agent_job(ctx, text), text, lang)
    return get_manager().submit(title, kind, lambda ctx: writer.run(ctx, text, lang, kind), text, lang)


def _agent_job(ctx: JobContext, text: str) -> str:
    """Run the normal agent (no planner, confirmations denied) and save its answer."""
    from jarvis.core import agent, safety, writer

    bot = agent.Agent(confirm=safety.deny_all, summarize_async=False, use_planner=False,
                      persist=False)
    ctx.progress("working")
    answer = bot.run(text)
    path = writer.output_path(ctx.job.title)
    path.write_text(f"# {ctx.job.title}\n\n{answer}\n", encoding="utf-8")
    ctx.set_output(path)
    return str(path)


# --- P9b: RAM/CPU gate, interrupted jobs, resume ---
def resource_wait_reason() -> str | None:
    """"RAM" / "CPU" while a new background job should wait, else None."""
    try:
        import os

        import psutil

        if psutil.virtual_memory().available / 1048576 < config.JOB_MIN_FREE_MB:
            return "RAM"
        if os.getloadavg()[0] > (os.cpu_count() or 1) * config.JOB_MAX_LOAD_PER_CORE:
            return "CPU"
    except Exception as e:  # never block jobs because a probe failed
        log.debug("resource probe failed: %s", e)
    return None


def _resumable() -> list[dict]:
    from jarvis.core.writer import RESUME_PREFIX

    out = []
    for key in store.kv_prefix(RESUME_PREFIX):
        try:
            row = store.job_get(int(key[len(RESUME_PREFIX):]))
        except ValueError:
            continue
        if row and row.get("status") not in ACTIVE + ("done",):
            out.append(row)
    return sorted(out, key=lambda r: r["id"])


def announce_interrupted(mark_stale: bool = False) -> int:
    """Tell the user once about writing jobs interrupted by a quit/restart. Returns how many were new.
    mark_stale (main process only): create the manager first, which marks jobs a crash left running."""
    if mark_stale:
        get_manager()
    rows = [r for r in _resumable() if (r.get("error") or "").startswith("interrupted")]
    seen = set((store.kv_get("jobs_interrupted_notified") or "").split(","))
    new = [r for r in rows if str(r["id"]) not in seen]
    if not new:
        return 0
    ids = ", ".join(f"#{r['id']}" for r in new)
    first = new[0]["id"]
    from jarvis.core import notify as _notify

    _notify.notify("Interrupted jobs", f"{len(new)} job(s) were interrupted ({ids}). Say 'resume job {first}' "
                   "to continue.", level="info", source="jobs")
    store.kv_set("jobs_interrupted_notified", ",".join(sorted((seen | {str(r["id"]) for r in new}) - {""})))
    return len(new)


def resume(query: str | int) -> str:
    """Continue an interrupted writing job from its next section (as a new job, same output file)."""
    import json

    from jarvis.core import writer

    digits = str(query).strip().lower().replace("job", "").strip().lstrip("#")
    if not digits.isdigit():
        rows = _resumable()
        if not rows:
            return "no interrupted writing job to resume"
        digits = str(rows[-1]["id"])
    jid = int(digits)
    row = store.job_get(jid)
    if row is None:
        return f"no job #{jid}"
    if row["status"] == "done":
        return f"job #{jid} is already done: {row.get('output_path') or row['title']}"
    if row["status"] in ACTIVE:
        return f"job #{jid} is still {row['status']}"
    raw = store.kv_get(f"{writer.RESUME_PREFIX}{jid}")
    if not raw:
        return f"job #{jid} can't be resumed (only writing jobs keep their progress)"
    state = json.loads(raw)
    job = get_manager().submit(row["title"], row["kind"] or "write", lambda ctx: writer.resume(ctx, state),
                               row.get("request") or "", state.get("lang", "en"))
    store.kv_delete(f"{writer.RESUME_PREFIX}{jid}")
    n = len(state["sections"])
    return (f"resuming job #{jid} as job #{job.id}: {row['title']}, from section "
            f"{min(int(state.get('done') or 0) + 1, n)}/{n} (same file)")
