"""Background jobs: JobManager singleton (ThreadPoolExecutor, SQLite `jobs` table, cancel events,
progress strings, on_done callbacks) and the Announcer (text: print; voice: queue a short spoken
line for when Jarvis is idle; plus a notify-send desktop notification when available).

Every job thread runs inside ratelimit.context("background", cancel) so its LLM calls are paced
behind interactive replies. LLM calls use purpose "job<N>:<step>", so job tokens come from llm_calls.
"""
from __future__ import annotations

import collections
import logging
import shutil
import subprocess
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from jarvis.core import config, ratelimit, store

log = logging.getLogger("jarvis.jobs")

ACTIVE = ("queued", "running")


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
                store.job_update(row["id"], status="failed", error="interrupted (Jarvis restarted)",
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
        with self._lock:
            self._jobs[jid] = job
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
        except Exception as e:  # a failing job must never take Jarvis down
            log.exception("job #%d failed", job.id)
            job.error = f"{type(e).__name__}: {e}"
            status = "cancelled" if job.cancel_event.is_set() else "failed"
        self._finish(job, ctx, status)

    def _finish(self, job: Job, ctx: JobContext, status: str) -> None:
        job.status, job.finished = status, time.time()
        ctx.refresh_tokens()
        self._save(job, status=status, finished=job.finished, output_path=job.output_path,
                   error=job.error[:500], tokens=job.tokens, progress=job.progress)
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
                j.cancel_event.set()
        self._pool.shutdown(wait=wait, cancel_futures=cancel)


def _from_row(row: dict) -> Job:
    return Job(row["id"], row.get("title") or "", row.get("kind") or "", row.get("request") or "",
               status=row.get("status") or "", progress=row.get("progress") or "",
               output_path=row.get("output_path") or "", error=row.get("error") or "",
               tokens=row.get("tokens") or 0, created=row.get("created") or 0.0,
               finished=row.get("finished"))


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
        notify(line)

    def pop(self) -> tuple[str, str] | None:
        """Next (spoken text, lang) or None."""
        try:
            return self._queue.popleft()
        except IndexError:
            return None

    def pending(self) -> int:
        return len(self._queue)


ANNOUNCER = Announcer()


def notify(text: str) -> None:
    if not config.JOBS_NOTIFY:
        return
    exe = shutil.which("notify-send")
    if not exe:
        return
    try:
        subprocess.Popen([exe, "Jarvis", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError as e:
        log.debug("notify-send failed: %s", e)


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

    bot = agent.Agent(confirm=safety.deny_all, summarize_async=False, use_planner=False)
    ctx.progress("working")
    answer = bot.run(text)
    path = writer.output_path(ctx.job.title)
    path.write_text(f"# {ctx.job.title}\n\n{answer}\n", encoding="utf-8")
    ctx.set_output(path)
    return str(path)
