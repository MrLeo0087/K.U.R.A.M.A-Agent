"""Training Guard worker ("process_watch"): watches training runs and long processes, alerts desktop + Telegram.

Watches live in the SQLite `watches` table (they survive restarts). The logic is in jarvis/core/training.py:
  - "run":   launched by KURAMA (run_training): reads its log, restarts it on a crash (retries), reports the end
  - "proc":  a PID / process name: alerts when it exits; also reads its output when that goes to a file
  - "log":   a log file: progress (epoch, loss, acc, ETA), NaN loss, out-of-memory, crash, finished
  - "colab": a Google Colab notebook pinging through ntfy.sh; silence = probably disconnected
Every run is also checked for being stuck (no new output for TRAINING_STALL_MIN) and, while anything local is
being watched, the laptop is kept from sleeping and a low battery is reported. Plain code, 0 tokens; only a crash
gets one short LLM line explaining the cause (cached per error).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import psutil

from jarvis.core import cmdalerts, config, notify, store, training
from jarvis.workers.base import Worker

SOURCE = "process_watch"  # in TELEGRAM_INFO_SOURCES: finished runs reach the phone too
fmt_duration = training.fmt_duration
describe = training.describe


# --- process helpers ---
def _running(pid: int, create_time: float) -> bool:
    try:
        p = psutil.Process(pid)
        if abs(p.create_time() - create_time) > 1.0:
            return False  # PID reused by another process
        return p.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:
        return True


def find_processes(name: str) -> list[psutil.Process]:
    """Processes whose name equals `name` (preferred) or whose command line contains it."""
    low = name.lower().strip()
    me = {os.getpid(), os.getppid()}
    exact, loose = [], []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        if p.info["pid"] in me:
            continue
        pname = (p.info.get("name") or "").lower()
        cmd = " ".join(p.info.get("cmdline") or []).lower()
        if pname == low:
            exact.append(p)
        elif len(low) >= 3 and low in cmd and "jarvis" not in cmd:
            loose.append(p)
    return exact or loose


def register_process(target: str, label: str = "") -> tuple[int | None, str]:
    """Add a PID / process-name watch. Returns (watch id or None, message)."""
    target = (target or "").strip()
    if not target:
        return None, "error: give a PID or a process name"
    pids: dict[str, float] = {}
    if target.isdigit():
        try:
            p = psutil.Process(int(target))
            pids[str(p.pid)] = p.create_time()
            name = p.name()
        except psutil.NoSuchProcess:
            return None, f"error: no process with PID {target}"
    else:
        procs = find_processes(target)
        for p in procs[:20]:
            try:
                pids[str(p.pid)] = p.create_time()
            except psutil.Error:
                pass
        if not pids:
            return None, f"error: no running process matches {target!r}"
        name = target
    label = (label or name)[:60]
    state: dict = {"pids": pids, "started": min(pids.values())}
    log = next((lp for pid in pids if (lp := training.proc_log(int(pid)))), None)
    if log:  # it writes to a file: read progress from there too
        state.update(log=log, offset=os.path.getsize(log))
    wid = store.watch_add("proc", target, label, "", state)
    return wid, (f"watch #{wid}: {label} (PID {', '.join(list(pids)[:5])}{'…' if len(pids) > 5 else ''})"
                 + (f", reading {log}" if log else ""))


def compile_pattern(patterns: str) -> re.Pattern:
    return re.compile(patterns or config.LOG_WATCH_ERROR_PATTERN)


def register_log(path: str, patterns: str = "", label: str = "", from_start: bool = False
                 ) -> tuple[int | None, str]:
    p = Path(os.path.expanduser((path or "").strip())).resolve()
    if not p.is_file():
        return None, f"error: no such log file: {p}"
    try:
        compile_pattern(patterns)
    except re.error as e:
        return None, f"error: bad regex {patterns!r}: {e}"
    st = p.stat()
    state = {"inode": st.st_ino, "offset": 0 if from_start else st.st_size, "tail": [], "last_alert": 0.0,
             "matches": 0, "log": str(p), "started": time.time()}
    label = (label or p.name)[:60]
    wid = store.watch_add("log", str(p), label, patterns or "", state)
    return wid, f"watch #{wid}: tailing {p} for {'custom' if patterns else 'error'} patterns"


def find_watch(query: str) -> list[dict]:
    q = (query or "").strip().lstrip("#").lower()
    active = store.watches_list(("active",))
    if q in ("all", "everything", ""):
        return active
    if q.isdigit():
        w = store.watch_get(int(q))
        return [w] if w and w["status"] == "active" else []
    return [w for w in active if q in w["label"].lower() or q in w["target"].lower()]


def read_new(path: Path, st: dict, log=None) -> list[str] | None:
    """New complete lines of a log since st['offset'] (follows rotation/truncation); None = file missing."""
    try:
        info = path.stat()
    except FileNotFoundError:
        st.setdefault("missing_since", time.time())
        return None
    st.pop("missing_since", None)
    offset = int(st.get("offset") or 0)
    if st.get("inode") and info.st_ino != st["inode"]:
        if log:
            log.info("%s rotated", path)
        offset = 0
    elif info.st_size < offset:
        if log:
            log.info("%s truncated", path)
        offset = 0
    st["inode"] = info.st_ino
    if info.st_size == offset:
        st["offset"] = offset
        return []
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read(config.LOG_WATCH_READ_MAX)
    cut = data.rfind(b"\n")
    if cut >= 0:
        data = data[: cut + 1]  # keep a half-written last line for the next tick
    elif len(data) < config.LOG_WATCH_READ_MAX:
        st["offset"] = offset
        return []
    st["offset"] = offset + len(data)
    # tqdm redraws with \r: each redraw is its own line
    text = data.decode("utf-8", errors="replace").replace("\r", "\n")
    return [ln for ln in text.splitlines() if ln.strip()]


# --- worker ---
class ProcessWatcher(Worker):
    name = "process_watch"
    interval_s = config.PROCESS_WATCH_INTERVAL_S

    def __init__(self, interval_s: float | None = None) -> None:
        super().__init__(interval_s)
        self.inhibitor: subprocess.Popen | None = None
        self.last_colab_poll = 0.0
        self.last_battery = 0.0

    def info(self) -> dict:
        try:
            return {"active": len(store.watches_list(("active",)))}
        except Exception:
            return {}

    def tick(self) -> None:
        try:
            cmdalerts.check()  # long terminal commands that just finished (one stat() when nothing new)
        except Exception as e:
            self.log.info("command alerts failed: %s", e)
        if time.time() - getattr(self, "last_net", 0.0) >= 30:  # "tell me when the internet is back"
            self.last_net = time.time()
            try:
                from jarvis.core import netdoctor
                netdoctor.check_wait()
            except Exception as e:
                self.log.info("internet wait check failed: %s", e)
        active = store.watches_list(("active",))
        for w in active:
            try:
                getattr(self, f"check_{w['kind']}", lambda _w: None)(w)
            except Exception as e:  # one broken watch must not stop the others
                self.log.warning("watch #%s failed: %s", w["id"], e)
        now = time.time()
        if any(w["kind"] == "colab" for w in active) and now - self.last_colab_poll >= config.COLAB_POLL_S:
            self.last_colab_poll = now
            try:
                self.poll_colab()
            except Exception as e:
                self.log.info("colab poll failed: %s", e)
        local = [w for w in active if w["kind"] in ("proc", "log")]  # launched runs carry their own inhibitor
        self.keep_awake(bool(local))
        if (local or any(w["kind"] == "run" for w in active)) and now - self.last_battery >= 60:
            self.last_battery = now
            self.check_battery(active)

    # ---------- alerts ----------
    def alert(self, w: dict, title: str, text: str, level: str = "info") -> None:
        notify.notify(f"{title}: {w['label']}", text, level=level, source=SOURCE)

    def handle(self, w: dict, st: dict, events: list[tuple[str, str]]) -> None:
        prog = training.progress_text(st)
        for kind, text in events:
            if kind == "nan":
                self.alert(w, "Loss is NaN", f"{text}. Training is probably diverging: lower the learning rate "
                                             f"or check the data.\n{prog}", "warning")
            elif kind == "oom":
                self.alert(w, "Out of memory", f"{text}\nTry a smaller batch size, gradient accumulation or "
                                               f"mixed precision.", "error")
            elif kind == "error" and w["kind"] == "log":
                self.alert(w, "Error in the log", self.crash_text(w, st), "error")

    def crash_text(self, w: dict, st: dict) -> str:
        err = st.get("error") or training.error_summary(st.get("tail") or []) or "it stopped with an error"
        why = training.explain(err, st.get("tail") or [])
        tail = "\n".join((st.get("tail") or [])[-5:])
        prog = training.progress_text(st)
        return f"{err}" + (f"\nLikely: {why}" if why else "") + (f"\nWhere it was: {prog}" if prog else "") + \
            f"\nLast lines:\n{tail}"

    def stalled(self, w: dict, st: dict) -> None:
        """No new output for a long time while the process still runs: probably stuck (say it once)."""
        last = float(st.get("last_output") or st.get("started") or w["created"])
        mins = config.TRAINING_STALL_MIN
        if mins and time.time() - last > mins * 60 and not st.get("stall_sent"):
            st["stall_sent"] = True
            self.alert(w, "No progress", f"No new output for {mins} minutes. It may be stuck (deadlock, waiting "
                                         f"for input, or swapping).\n{training.progress_text(st)}", "warning")

    def finished(self, w: dict, st: dict, note: str = "") -> None:
        dur = fmt_duration(time.time() - float(st.get("started") or w["created"]))
        prog = training.progress_text(st)
        result = f"finished in {dur}" + (f": {prog}" if prog else "")
        store.watch_update(w["id"], status="done", finished=time.time(), result=result, state=st)
        self.alert(w, "Training finished" if w["kind"] in ("run", "colab") or prog else "Process finished",
                   result + (f"\n{note}" if note else ""))

    # ---------- kinds ----------
    def read_log(self, w: dict, st: dict) -> None:
        if not st.get("log"):
            return
        lines = read_new(Path(st["log"]), st, self.log)
        if lines:
            st.pop("stall_sent", None)
            self.handle(w, st, training.update(st, lines))

    def check_run(self, w: dict) -> None:
        st = w["state"]
        self.read_log(w, st)
        rc = training.exit_code(w["id"], st.get("attempt", 1), st.get("pid", 0))
        if rc is None:
            self.stalled(w, st)
            store.watch_update(w["id"], state=st)
            return
        self.read_log(w, st)  # the last lines written before it exited
        if rc == 0 or (rc == -1 and not st.get("traceback")):
            self.finished(w, st)
            return
        text = self.crash_text(w, st)
        if st.get("attempt", 1) <= int(st.get("retries") or 0):
            store.watch_update(w["id"], state=st)
            err = training.start_attempt(w["id"])
            self.alert(w, "Training crashed, restarting",
                       f"Attempt {st['attempt']} failed (exit {rc}).\n{text}\n"
                       + (f"Could not restart: {err}" if err else
                          f"Started attempt {st['attempt'] + 1} of {int(st['retries']) + 1}."), "warning")
            if err:
                store.watch_update(w["id"], status="failed", finished=time.time(), result=err)
            return
        store.watch_update(w["id"], status="failed", finished=time.time(), state=st,
                           result=f"crashed (exit {rc}): {st.get('error') or 'see the log'}")
        self.alert(w, "Training crashed", f"Exit code {rc}.\n{text}\nLog: {st.get('log')}", "error")

    def check_proc(self, w: dict) -> None:
        st = w["state"]
        self.read_log(w, st)
        pids = st.get("pids") or {}
        if any(_running(int(pid), ct) for pid, ct in pids.items()):
            if st.get("log"):
                self.stalled(w, st)
            store.watch_update(w["id"], state=st)
            return
        if st.get("traceback"):
            store.watch_update(w["id"], status="failed", finished=time.time(), state=st,
                               result=f"crashed: {st.get('error') or 'error in its output'}")
            self.alert(w, "Process crashed", self.crash_text(w, st), "error")
            return
        runtime = fmt_duration(time.time() - (st.get("started") or w["created"]))
        prog = training.progress_text(st)
        result = f"exited after {runtime}" + (f": {prog}" if prog else "")
        store.watch_update(w["id"], status="done", finished=time.time(), result=result, state=st)
        self.log.info("watch #%s %s %s", w["id"], w["label"], result)
        notify.notify(f"Process finished: {w['label']}",
                      f"{w['label']} (PID {', '.join(list(pids)[:5])}) {result}.", level="info", source=SOURCE)

    def check_log(self, w: dict) -> None:
        st = w["state"]
        lines = read_new(Path(w["target"]), st, self.log)
        if lines is None:
            store.watch_update(w["id"], state=st)
            return
        if not lines:
            store.watch_update(w["id"], state=st)
            return
        st.pop("stall_sent", None)
        events = training.update(st, lines)
        custom = w.get("patterns")
        if custom:  # the user's own pattern: alert on every match (with the cooldown)
            rx = compile_pattern(custom)
            hits = [ln for ln in lines if rx.search(ln)]
            now = time.time()
            if hits and now - float(st.get("last_alert") or 0) >= config.LOG_WATCH_ALERT_COOLDOWN_S:
                st["last_alert"] = now
                st["matches"] = int(st.get("matches") or 0) + 1
                self.alert(w, "Log match", f"{len(hits)} line(s); first: {hits[0].strip()[:200]}", "warning")
            events = [e for e in events if e[0] != "error"]
        self.handle(w, st, [e for e in events if e[0] != "done"])
        if any(e[0] == "done" for e in events):
            done = next(t for k, t in events if k == "done")
            self.finished(w, st, done)
            return
        store.watch_update(w["id"], state=st)

    # ---------- downloads ----------
    def check_dl(self, w: dict) -> None:
        from jarvis.core import automation
        automation.check_download(w)

    # ---------- websites ----------
    def check_web(self, w: dict) -> None:
        from jarvis.core import webwatch
        webwatch.check(w)

    # ---------- Colab ----------
    def poll_colab(self) -> None:
        since = store.kv_get("colab_since") or "12h"
        msgs = training.colab_poll(since)
        runs = {w["target"]: w for w in store.watches_list(("active",)) if w["kind"] == "colab"}
        for m in msgs:
            store.kv_set("colab_since", str(m.get("id") or since))
            name = str(m.get("run") or "colab")
            w = runs.get(name)
            if w is None:  # the snippet from an earlier day, run again: a new run
                wid = store.watch_add("colab", name, name, "", {"started": time.time(), "last_msg": 0.0})
                w = runs[name] = store.watch_get(wid)
            self.colab_event(w, m)

    def colab_event(self, w: dict, m: dict) -> None:
        st = w["state"]
        st["last_msg"] = time.time()
        st.pop("silent_sent", None)
        event = m.get("event")
        nums = {k: v for k, v in m.items() if isinstance(v, (int, float)) and k not in ("time",)}
        if nums:
            metrics = st.setdefault("metrics", {})
            metrics.update({("acc" if k == "accuracy" else k): v for k, v in nums.items()})
            if k := training.loss_key(nums):
                st.setdefault("loss_hist", []).append(nums[k])
                if training.is_bad(nums[k]) and not st.get("nan_sent"):
                    st["nan_sent"] = True
                    self.alert(w, "Loss is NaN", f"{k} is {nums[k]} on Colab. Lower the learning rate or check "
                                                 f"the data.", "warning")
        if event == "start":
            st["started"] = time.time()
            self.alert(w, "Colab training started", "I'll tell you when it finishes, crashes or goes quiet.")
        elif event == "error":
            st["error"] = str(m.get("error") or "")[:300]
            why = training.explain(st["error"], [])
            store.watch_update(w["id"], status="failed", finished=time.time(), state=st,
                               result=f"crashed: {st['error'][:150]}")
            self.alert(w, "Colab training crashed", st["error"] + (f"\nLikely: {why}" if why else ""), "error")
            return
        elif event == "done":
            self.finished(w, st)
            return
        store.watch_update(w["id"], state=st)

    def check_colab(self, w: dict) -> None:
        st = w["state"]
        now = time.time()
        last = float(st.get("last_msg") or 0)
        if not last:
            if now > float(st.get("expect_until") or w["created"] + 3600):  # the snippet was never run
                store.watch_update(w["id"], status="stopped", finished=now, result="no messages from Colab")
            return
        mins = config.COLAB_SILENT_MIN
        if now - last > mins * 60 and not st.get("silent_sent"):
            st["silent_sent"] = True
            store.watch_update(w["id"], state=st)
            self.alert(w, "Colab went quiet", f"No word for {mins} minutes: the runtime may have disconnected or "
                                              f"crashed. {training.progress_text(st)}".strip(), "warning")

    # ---------- laptop ----------
    def keep_awake(self, on: bool) -> None:
        """While local work is watched, block sleep (a launched run carries its own systemd-inhibit)."""
        alive = self.inhibitor is not None and self.inhibitor.poll() is None
        if on and not alive and config.TRAINING_KEEP_AWAKE and shutil.which("systemd-inhibit"):
            try:
                self.inhibitor = subprocess.Popen(
                    ["systemd-inhibit", "--what=sleep:idle", "--who=KURAMA", "--why=watching a training run",
                     "--mode=block", "sleep", "infinity"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as e:
                self.log.info("could not block sleep: %s", e)
        elif not on and alive:
            self.inhibitor.terminate()
            self.inhibitor = None

    def check_battery(self, active: list[dict]) -> None:
        try:
            b = psutil.sensors_battery()
        except Exception:
            return
        if b is None or b.power_plugged or b.percent > config.TRAINING_BATTERY_WARN:
            return
        for w in active:
            if w["kind"] in ("run", "proc", "log") and not w["state"].get("battery_sent"):
                w["state"]["battery_sent"] = True
                store.watch_update(w["id"], state=w["state"])
                self.alert(w, "Battery low while training", f"Battery at {int(b.percent)}% and not charging. "
                                                            f"Plug in so the run isn't lost.", "warning")
                return

    def teardown(self) -> None:
        self.keep_awake(False)
