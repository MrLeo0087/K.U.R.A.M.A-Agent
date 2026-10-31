"""Long Job Engine (Night Shift foundation, step 1): durable background jobs on top of jobs.JobManager.

A long job is a top-level function fn(ctx: LongContext, params: dict) -> str | None. It
- survives crashes and KURAMA restarts: its params and checkpoints live in SQLite (store.job_state); on the next
  start, recover() resumes it in the same job id from its last ctx.checkpoint() (the function reads ctx.state);
- has hard caps: tokens (its own LLM calls, purpose ctx.purpose(...)), running minutes (paused time doesn't count)
  and an optional end time (deadline); over a cap -> status "stopped" (resume = one more cap's worth);
- pauses by itself while free RAM is short, the battery is low and not charging, or (needs_power) the charger is
  out, and when the user says "pause job N"; it continues when that clears / on "resume job N";
- keeps a step log (store.job_steps) next to its progress line; cancel works as for every job;
- heavy=True: at most one CPU-heavy long job at a time.
Runs in the job manager's own long-job threads inside ratelimit's background priority: never blocks the voice loop
or the chat. 0 tokens itself. Lazy: nothing here runs or loads until a long job exists.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from jarvis.core import config, store
from jarvis.core.jobs import (ACTIVE, INTERRUPTED, STOPPED, Job, JobCancelled, JobContext, JobStopped,
                              get_manager)

log = logging.getLogger("jarvis.longjobs")

LongFn = Callable[["LongContext", dict], "str | None"]
RESUMABLE = (INTERRUPTED, STOPPED, "failed")  # "resume job N" continues these from their last checkpoint
_heavy = threading.Semaphore(1)


# --- owner of a running job: one process resumes it, never two ---
def _me() -> str:
    try:
        import psutil
        return f"{os.getpid()}:{int(psutil.Process().create_time())}"
    except Exception:
        return f"{os.getpid()}:0"


def _alive(owner: str | None) -> bool:
    """True when the process that owns a job still runs (pid + start time, so a reused pid doesn't count)."""
    if not owner:
        return False
    try:
        pid, started = (int(x) for x in owner.split(":", 1))
        import psutil
        return int(psutil.Process(pid).create_time()) == started or started == 0
    except Exception:
        return False


def _ref(fn: LongFn | str) -> str:
    if isinstance(fn, str):
        return fn
    if "<" in fn.__qualname__:  # a lambda / nested function can't be found again after a restart
        raise ValueError("a long job needs a top-level function")
    return f"{fn.__module__}:{fn.__qualname__}"


def _resolve(ref: str) -> LongFn:
    mod, _, name = ref.partition(":")
    obj: Any = importlib.import_module(mod)
    for part in name.split("."):
        obj = getattr(obj, part)
    return obj


def pause_reason(needs_power: bool = False) -> str | None:
    """Why a long job should pause now (low RAM / low battery / not charging), else None."""
    try:
        import psutil

        if psutil.virtual_memory().available / 1048576 < config.LONG_JOB_PAUSE_FREE_MB:
            return "low RAM"
        bat = psutil.sensors_battery()
        if bat is not None and not bat.power_plugged:
            if needs_power:
                return "not charging"
            if bat.percent < config.LONG_JOB_PAUSE_BATTERY:
                return f"battery {bat.percent:.0f}%"
    except Exception as e:  # never stop a job because a probe failed
        log.debug("pause probe failed: %s", e)
    return None


class LongContext(JobContext):
    """What a long job function gets: everything JobContext has, plus params, state + checkpoint(), step(),
    caps (tokens_left / can_spend) and check() that also pauses and stops at the caps."""

    def __init__(self, job: Job, manager, row: dict):
        super().__init__(job, manager)
        self.params: dict = json.loads(row.get("params") or "{}")
        self.state: dict = json.loads(row.get("state") or "{}")
        self.caps: dict = json.loads(row.get("caps") or "{}")
        self.resumed = bool(self.state)
        self._used0 = float(row.get("used_s") or 0.0)
        self._t0 = time.monotonic()
        self._probe_at = 0.0

    # --- budget ---
    @property
    def used_s(self) -> float:
        return self._used0 + (time.monotonic() - self._t0)

    @property
    def max_tokens(self) -> int:
        return int(self.caps.get("tokens") or 0)

    def tokens_left(self) -> int:
        return max(0, self.max_tokens - self.refresh_tokens()) if self.max_tokens else 10 ** 9

    def can_spend(self, tokens: int) -> bool:
        """Ask before an AI call: would it stay under this job's token cap?"""
        return tokens <= self.tokens_left()

    def _over_cap(self) -> str | None:
        if self.max_tokens and self.refresh_tokens() >= self.max_tokens:
            return f"out of token budget ({self.job.tokens} of {self.max_tokens})"
        secs = float(self.caps.get("seconds") or 0)
        if secs and self.used_s >= secs:
            return f"out of time budget ({self.used_s / 60:.0f} of {secs / 60:.0f} min)"
        deadline = float(self.caps.get("deadline") or 0)
        if deadline and time.time() >= deadline:
            return f"reached its end time ({time.strftime('%H:%M', time.localtime(deadline))})"
        return None

    # --- the job's own calls ---
    def checkpoint(self, **updates: Any) -> None:
        """Save progress: after a crash / restart the job continues with ctx.state as saved here."""
        self.state.update(updates)
        store.job_state_update(self.job.id, state=json.dumps(self.state, ensure_ascii=False, default=str),
                               used_s=self.used_s)

    def step(self, text: str) -> None:
        """One line in the step log (and the progress line), then check() for cancel / pause / caps."""
        self.progress(text)
        try:
            store.job_step_add(self.job.id, text[:300], self.job.tokens)
        except Exception as e:
            log.debug("step not logged: %s", e)
        self.check()

    def check(self) -> None:
        """Raise JobCancelled when cancelled, JobStopped at a cap; wait here while the job should pause."""
        super().check()
        now = time.monotonic()
        if now - self._probe_at < config.LONG_JOB_PROBE_S:
            return
        self._probe_at = now
        if (why := self._over_cap()):
            raise JobStopped(why)
        self._pause_while_needed()

    def _user_paused(self) -> bool:
        if self.job.pause_event.is_set():
            return True
        row = store.job_state_get(self.job.id)  # "pause job N" from another process (CLI / Telegram worker)
        return bool(row and row.get("paused"))

    def _pause_while_needed(self) -> None:
        while True:
            why = "paused by you" if self._user_paused() else pause_reason(bool(self.caps.get("needs_power")))
            if not why:
                break
            if self.job.status != "paused":  # stop the running clock while paused
                self._used0, self.job.status = self.used_s, "paused"
                store.job_state_update(self.job.id, used_s=self._used0)
                self._m._save(self.job, status="paused")
                store.job_step_add(self.job.id, f"paused: {why}", self.job.tokens)
                log.info("long job #%d paused: %s", self.job.id, why)
            if self.job.progress != f"paused: {why}":
                self.job.progress = f"paused: {why}"
                self._m._save(self.job, progress=self.job.progress)
            deadline = float(self.caps.get("deadline") or 0)
            if deadline and time.time() >= deadline:
                raise JobStopped(f"reached its end time while paused ({why})")
            if self.job.cancel_event.wait(config.LONG_JOB_RECHECK_S):
                raise JobCancelled(f"job #{self.job.id} cancelled")
        if self.job.status == "paused":
            self._t0, self.job.status = time.monotonic(), "running"
            self.job.progress = "continuing"
            self._m._save(self.job, status="running", progress=self.job.progress)
            store.job_step_add(self.job.id, "continuing", self.job.tokens)


# --- the body every long job runs inside its job thread ---
def _body(ctx: JobContext) -> str | None:
    job = ctx.job
    row = store.job_state_get(job.id)
    if row is None:
        raise RuntimeError(f"long job #{job.id} has no saved state")
    lc = LongContext(job, ctx._m, row)
    store.job_state_update(job.id, owner=_me())
    heavy = bool(lc.caps.get("heavy"))
    if heavy:
        lc.progress("waiting for the other heavy job to finish")
        while not _heavy.acquire(timeout=config.LONG_JOB_RECHECK_S):
            lc.check()
    try:
        store.job_step_add(job.id, "resumed from its last checkpoint" if lc.resumed else "started", job.tokens)
        lc._probe_at = 0.0
        lc.check()  # paused by the user before a restart / short on RAM right now: wait first
        fn = _resolve(row["fn"])
        out = fn(lc, lc.params)
        store.job_step_add(job.id, "finished", lc.refresh_tokens())
        return out
    finally:
        if heavy:
            _heavy.release()
        try:
            store.job_state_update(job.id, used_s=lc.used_s)
        except Exception as e:
            log.debug("used time not saved: %s", e)


# --- public API ---
def submit(title: str, fn: LongFn | str, params: dict | None = None, *, kind: str = "long",
           max_tokens: int | None = None, max_minutes: float | None = None, deadline: float | None = None,
           needs_power: bool = False, heavy: bool = False, request: str = "", lang: str = "en",
           origin: str | None = None) -> Job:
    """Start a long job. fn must be a top-level function (found again by name after a restart); params must be
    JSON. Caps default to config.LONG_JOB_DEFAULT_TOKENS / _MINUTES; 0 = no cap. Callers ask the user before
    a job whose cap is above config.AGENT_ASK_ABOVE_TOKENS (needs_ok)."""
    ref = _ref(fn)
    caps = {"tokens": config.LONG_JOB_DEFAULT_TOKENS if max_tokens is None else int(max_tokens),
            "seconds": 60.0 * (config.LONG_JOB_DEFAULT_MINUTES if max_minutes is None else float(max_minutes)),
            "deadline": deadline or 0, "needs_power": bool(needs_power), "heavy": bool(heavy)}
    caps["base_tokens"], caps["base_seconds"] = caps["tokens"], caps["seconds"]  # "resume" adds one more of these
    params_json = json.dumps(params or {}, ensure_ascii=False)

    def created(job: Job) -> None:  # saved before the thread can start: a crash right now still resumes it
        store.job_state_insert(job.id, fn=ref, params=params_json, state="{}", caps=json.dumps(caps),
                               used_s=0.0, owner=_me(), paused=0, origin=job.origin)

    return get_manager().submit(title, kind, _body, request or title, lang, durable=True, origin=origin,
                                on_created=created)


def needs_ok(max_tokens: int) -> bool:
    """A job allowed to spend this many tokens must ask the owner first."""
    return int(max_tokens) > config.AGENT_ASK_ABOVE_TOKENS


def is_long(job_id: int) -> bool:
    return store.job_state_get(int(job_id)) is not None


def steps(job_id: int, limit: int = 20) -> list[dict]:
    return store.job_steps(int(job_id), limit)


def _resubmit(row: dict, job_row: dict) -> Job:
    return get_manager().submit(job_row["title"], job_row.get("kind") or "long", _body,
                                job_row.get("request") or "", "en", job_id=job_row["id"], durable=True,
                                origin=row.get("origin") or "")


def pause(query: str | int) -> str:
    job = get_manager().find(query)
    if job is None or not is_long(job.id):
        return f"no long job matches {query!r}" if str(query).strip() else "no long job running"
    if job.status not in ACTIVE:
        return f"job #{job.id} is {job.status}, nothing to pause"
    store.job_state_update(job.id, paused=1)
    job.pause_event.set()
    return f"pausing job #{job.id}: {job.title} (it stops at its next step; say 'resume job {job.id}' to continue)"


def resume(job_id: int) -> str:
    """Continue a long job: un-pause it, or restart it from its last checkpoint (stopped at a cap: one more
    cap's worth of tokens / time; the end time is dropped)."""
    jid = int(job_id)
    row, job_row = store.job_state_get(jid), store.job_get(jid)
    if row is None or job_row is None:
        return f"no long job #{jid}"
    status = job_row["status"]
    if status in ACTIVE:
        store.job_state_update(jid, paused=0)
        live = get_manager().get(jid)
        if live is not None:
            live.pause_event.clear()
        return f"job #{jid} continues: {job_row['title']}" if row.get("paused") else f"job #{jid} is already {status}"
    if status == "done":
        return f"job #{jid} is already done: {job_row.get('output_path') or job_row['title']}"
    if status not in RESUMABLE:
        return f"job #{jid} was {status}; it can't be resumed"
    if _alive(row.get("owner")) and row.get("owner") != _me():
        return f"job #{jid} belongs to another running KURAMA process"
    note = ""
    if status == STOPPED:
        caps = json.loads(row.get("caps") or "{}")
        used_tokens, used_s = int(job_row.get("tokens") or 0), float(row.get("used_s") or 0)
        if caps.get("tokens") and used_tokens >= caps["tokens"]:
            caps["tokens"] = used_tokens + int(caps.get("base_tokens") or config.LONG_JOB_DEFAULT_TOKENS)
            note += f", token cap now {caps['tokens']}"
        if caps.get("seconds") and used_s >= caps["seconds"]:
            caps["seconds"] = used_s + float(caps.get("base_seconds") or 60.0 * config.LONG_JOB_DEFAULT_MINUTES)
            note += f", time cap now {caps['seconds'] / 60:.0f} min"
        if caps.get("deadline") and time.time() >= caps["deadline"]:
            caps["deadline"] = 0
            note += ", no end time"
        store.job_state_update(jid, caps=json.dumps(caps))
    if not store.job_state_claim(jid, row.get("owner"), _me()):
        return f"job #{jid} is being resumed elsewhere"
    store.job_state_update(jid, paused=0)
    _resubmit(row, job_row)
    return f"resuming job #{jid} from its last checkpoint: {job_row['title']}{note}"


def latest_resumable() -> int | None:
    """The newest long job that 'resume' with no number means: paused first, then interrupted / stopped."""
    ids = store.job_state_ids()
    if not ids:
        return None
    rows = [r for r in store.jobs_list(30) if r["id"] in ids]
    for want in (("paused",), RESUMABLE):
        for r in rows:
            if r["status"] in want:
                return int(r["id"])
    return None


def recover() -> list[int]:
    """At KURAMA's start: resume long jobs a crash / quit / restart left unfinished (unless another live
    process owns them). Returns their ids; tells the user once."""
    ids = store.job_state_ids()
    if not ids:
        return []
    get_manager()  # marks stale non-long jobs; long ones are left for us
    me, done = _me(), []
    for job_row in store.jobs_list(200, ACTIVE + (INTERRUPTED,)):
        jid = int(job_row["id"])
        live = get_manager().get(jid)
        if jid not in ids or (live is not None and live.future is not None):
            continue
        row = store.job_state_get(jid) or {}
        owner = row.get("owner")
        if owner != me and _alive(owner):
            continue
        if not config.LONG_JOB_AUTO_RESUME:
            store.job_update(jid, status=INTERRUPTED, error="interrupted (KURAMA restarted)")
            continue
        if not store.job_state_claim(jid, owner, me):
            continue
        _resubmit(row, job_row)
        done.append(jid)
    if done:
        log.info("resumed long jobs: %s", done)
        try:
            from jarvis.core import notify as _notify
            names = ", ".join(f"#{j}" for j in done)
            _notify.notify("Long jobs resumed", f"KURAMA restarted and continued {len(done)} long job(s) ({names}) "
                           "from their last checkpoint.", level="info", source="jobs", telegram=False)
        except Exception as e:
            log.debug("resume notice failed: %s", e)
    return done


# --- a 0-token self-test job (tests + live check: "does the long job engine survive a restart?") ---
def selftest(ctx: LongContext, params: dict) -> str:
    """Counts n steps of `sleep` seconds, checkpointing each; writes one line per step at the end."""
    n, pause_s = int(params.get("n", 10)), float(params.get("sleep", 2.0))
    done = list(ctx.state.get("done", []))
    for i in range(len(done) + 1, n + 1):
        ctx.step(f"step {i}/{n}")
        if ctx.job.cancel_event.wait(pause_s):
            ctx.check()
        done.append({"i": i, "pid": os.getpid(), "ts": round(time.time(), 1)})
        ctx.checkpoint(done=done)
    path = Path(config.OUTPUTS_DIR) / f"long_selftest_{ctx.job.id}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"step {d['i']} pid {d['pid']}\n" for d in done), encoding="utf-8")
    ctx.set_output(path)
    return str(path)
