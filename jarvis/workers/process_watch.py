"""Long-process / training-run watcher (worker "process_watch") plus the helpers its tools use.

Watches live in the SQLite `watches` table, so they survive restarts of KURAMA and the workers:
  - kind "proc": a PID or process name. The matching PIDs (+ create times, so a reused PID is not
    mistaken for the original) are captured when the watch is added; when all are gone the watch
    is done and an alert reports the runtime.
  - kind "log": tail a log file (follows rotation and truncation) and alert on regex matches
    (default config.LOG_WATCH_ERROR_PATTERN; at most one alert per LOG_WATCH_ALERT_COOLDOWN_S)
    with the last lines; "epoch N" is tracked as progress and done/finished/completed lines alert.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

import psutil

from jarvis.core import config, notify, store
from jarvis.workers.base import Worker

DONE_COOLDOWN_S = 600.0


def fmt_duration(seconds: float) -> str:
    s = int(max(0, seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m" if h else (f"{m}m {s}s" if m else f"{s}s")


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
    started = min(pids.values())
    wid = store.watch_add("proc", target, label, "", {"pids": pids, "started": started})
    return wid, f"watch #{wid}: {label} (PID {', '.join(list(pids)[:5])}{'…' if len(pids) > 5 else ''})"


# --- log helpers ---
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
    state = {"inode": st.st_ino, "offset": 0 if from_start else st.st_size, "tail": [], "epoch": None,
             "last_alert": 0.0, "last_done": 0.0, "matches": 0}
    label = (label or p.name)[:60]
    wid = store.watch_add("log", str(p), label, patterns or "", state)
    return wid, f"watch #{wid}: tailing {p} for {'custom' if patterns else 'error'} patterns"


def describe(w: dict) -> str:
    st = w.get("state") or {}
    head = f"#{w['id']} [{w['status']}] {w['label']}"
    if w["kind"] == "proc":
        if w["status"] == "active":
            return f"{head}: running {fmt_duration(time.time() - (st.get('started') or w['created']))}"
        return f"{head}: {w.get('result') or ''}".rstrip(": ")
    extra = f", epoch {st['epoch']}" if st.get("epoch") is not None else ""
    last = (st.get("tail") or [""])[-1][:100]
    return f"{head}: log {w['target']} ({st.get('matches', 0)} alerts{extra})" + (f" | {last}" if last else "")


def find_watch(query: str) -> list[dict]:
    q = (query or "").strip().lstrip("#").lower()
    active = store.watches_list(("active",))
    if q in ("all", "everything"):
        return active
    if q.isdigit():
        w = store.watch_get(int(q))
        return [w] if w and w["status"] == "active" else []
    return [w for w in active if q and (q in w["label"].lower() or q in w["target"].lower())]


# --- worker ---
class ProcessWatcher(Worker):
    name = "process_watch"
    interval_s = config.PROCESS_WATCH_INTERVAL_S

    def info(self) -> dict:
        try:
            return {"active": len(store.watches_list(("active",)))}
        except Exception:
            return {}

    def tick(self) -> None:
        for w in store.watches_list(("active",)):
            try:
                if w["kind"] == "proc":
                    self.check_proc(w)
                elif w["kind"] == "log":
                    self.check_log(w)
            except Exception as e:  # one broken watch must not stop the others
                self.log.warning("watch #%s failed: %s", w["id"], e)

    def check_proc(self, w: dict) -> None:
        st = w["state"]
        pids = st.get("pids") or {}
        if any(_running(int(pid), ct) for pid, ct in pids.items()):
            return
        now = time.time()
        runtime = fmt_duration(now - (st.get("started") or w["created"]))
        result = f"exited after {runtime}"
        store.watch_update(w["id"], status="done", finished=now, result=result)
        self.log.info("watch #%s %s %s", w["id"], w["label"], result)
        notify.notify(f"Process finished: {w['label']}",
                      f"{w['label']} (PID {', '.join(list(pids)[:5])}) {result}.",
                      level="info", source=f"watch:{w['id']}")

    def check_log(self, w: dict) -> None:
        st = w["state"]
        path = Path(w["target"])
        try:
            info = path.stat()
        except FileNotFoundError:
            if not st.get("missing_since"):
                st["missing_since"] = time.time()
                store.watch_update(w["id"], state=st)
                self.log.info("watch #%s: %s missing (rotation?)", w["id"], path)
            return
        st.pop("missing_since", None)
        offset = int(st.get("offset") or 0)
        if info.st_ino != st.get("inode"):
            self.log.info("watch #%s: %s rotated", w["id"], path)
            st["inode"], offset = info.st_ino, 0
        elif info.st_size < offset:
            self.log.info("watch #%s: %s truncated", w["id"], path)
            offset = 0
        if info.st_size == offset:
            if offset != st.get("offset"):
                st["offset"] = offset
                store.watch_update(w["id"], state=st)
            return
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read(config.LOG_WATCH_READ_MAX)
        cut = data.rfind(b"\n")
        if cut >= 0:
            data = data[: cut + 1]  # keep a half-written last line for the next tick
        elif len(data) < config.LOG_WATCH_READ_MAX:
            return
        st["offset"] = offset + len(data)
        lines = [ln for ln in data.decode("utf-8", errors="replace").splitlines() if ln.strip()]
        self.scan(w, st, lines)
        store.watch_update(w["id"], state=st)

    def scan(self, w: dict, st: dict, lines: list[str]) -> None:
        err_re = compile_pattern(w.get("patterns") or "")
        epoch_re = re.compile(config.LOG_WATCH_EPOCH_PATTERN)
        done_re = re.compile(config.LOG_WATCH_DONE_PATTERN)
        st["tail"] = ((st.get("tail") or []) + [ln[:300] for ln in lines])[-config.LOG_WATCH_TAIL_LINES:]
        errors, done = [], None
        for ln in lines:
            m = epoch_re.search(ln)
            if m:
                st["epoch"] = int(m.group(1))
            if err_re.search(ln):
                errors.append(ln)
            elif not m and done_re.search(ln):
                done = ln  # "epoch 3 completed" is progress, not the end
        now = time.time()
        tail = "\n".join(st["tail"][-5:])
        progress = f" (epoch {st['epoch']})" if st.get("epoch") is not None else ""
        if errors and now - float(st.get("last_alert") or 0) >= config.LOG_WATCH_ALERT_COOLDOWN_S:
            st["last_alert"] = now
            st["matches"] = int(st.get("matches") or 0) + 1
            notify.notify(f"Log alert: {w['label']}{progress}",
                          f"{len(errors)} matching line(s); first: {errors[0].strip()[:200]}\n"
                          f"Last lines:\n{tail}", level="error", source=f"watch:{w['id']}")
        if done and now - float(st.get("last_done") or 0) >= DONE_COOLDOWN_S:
            st["last_done"] = now
            notify.notify(f"Log finished: {w['label']}{progress}", f"{done.strip()[:200]}\nLast lines:\n{tail}",
                          level="info", source=f"watch:{w['id']}")
