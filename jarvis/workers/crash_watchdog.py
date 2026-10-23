"""Crash watchdog (worker "crash_watchdog"): keep configured dev servers alive.

Targets come ONLY from config.WATCHDOG_TARGETS plus data/watchdog_targets.json (written by the
confirm-level add_watchdog_target tool). Every command is re-checked against config.SHELL_ALLOWLIST
(never sudo, no shell operators) before it is started; it runs without a shell, in its own session,
with output in data/logs/watchdog_<name>.log. A crashed target is restarted after an exponential
backoff (5, 10, 20 … s, capped), at most WATCHDOG_MAX_RESTARTS_PER_HOUR times per hour, then the
watchdog gives up until the hour window clears. Crashes, restarts and give-ups alert via notify().
Optional "match": adopt an already-running process whose command line contains that text.
Stopping the workers stops the targets the watchdog started.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from jarvis.core import config, notify
from jarvis.core.shellcheck import check_shell
from jarvis.workers.base import Worker

_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
LOG_KEEP_BYTES = 1_000_000


def validate(t: dict) -> str | None:
    """Reason a target is invalid, or None."""
    name, cmd = str(t.get("name") or ""), str(t.get("command") or "")
    if not _NAME.match(name):
        return f"bad target name {name!r} (letters, digits, _ . - only)"
    ok, why = check_shell(cmd)
    if not ok:
        return f"{name}: {why}"
    cwd = os.path.expanduser(str(t.get("cwd") or "~"))
    if not os.path.isdir(cwd):
        return f"{name}: cwd {cwd} does not exist"
    return None


def load_file() -> list[dict]:
    try:
        data = json.loads(Path(config.WATCHDOG_TARGETS_FILE).read_text(encoding="utf-8"))
        return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def load_targets() -> list[dict]:
    """config.WATCHDOG_TARGETS + the targets file (config wins on a name clash)."""
    out: dict[str, dict] = {}
    for t in [*load_file(), *config.WATCHDOG_TARGETS]:
        if isinstance(t, dict) and t.get("name"):
            out[str(t["name"])] = dict(t)
    return list(out.values())


def add_target(name: str, command: str, cwd: str = "", match: str = "") -> str:
    """Validate and append to data/watchdog_targets.json (the tool asks the user first)."""
    t = {"name": name.strip(), "command": command.strip(), "cwd": cwd.strip() or "~"}
    if match.strip():
        t["match"] = match.strip()
    why = validate(t)
    if why:
        return f"error: {why}"
    items = [d for d in load_file() if d.get("name") != t["name"]] + [t]
    path = Path(config.WATCHDOG_TARGETS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=1), encoding="utf-8")
    return f"added watchdog target {t['name']}: {t['command']} (cwd {t['cwd']})"


@dataclass
class TargetState:
    proc: subprocess.Popen | None = None
    adopted: int | None = None  # pid of an adopted (not started by us) process
    started_at: float = 0.0
    fails: int = 0  # consecutive crashes (drives the backoff)
    restarts: list[float] = field(default_factory=list)  # restart times in the last hour
    next_start: float = 0.0
    gave_up: bool = False
    ever_started: bool = False
    last_exit: str = ""


class CrashWatchdog(Worker):
    name = "crash_watchdog"
    interval_s = config.WATCHDOG_INTERVAL_S

    def __init__(self, interval_s: float | None = None):
        super().__init__(interval_s)
        self.targets: dict[str, dict] = {}
        self.states: dict[str, TargetState] = {}
        self._file_mtime: float | None = -1.0

    # --- targets ---
    def reload(self) -> None:
        try:
            mtime = Path(config.WATCHDOG_TARGETS_FILE).stat().st_mtime
        except OSError:
            mtime = None
        if mtime == self._file_mtime and self.targets:
            return
        self._file_mtime = mtime
        fresh = {}
        for t in load_targets():
            why = validate(t)
            if why:
                self.log.warning("target refused: %s", why)
                continue
            fresh[t["name"]] = t
        for gone in set(self.targets) - set(fresh):
            self.log.info("target %s removed", gone)
            self._terminate(gone)
            self.states.pop(gone, None)
        self.targets = fresh

    def info(self) -> dict:
        out = {}
        for name, st in self.states.items():
            pid = st.proc.pid if st.proc else st.adopted
            state = "gave up" if st.gave_up else ("running" if self._alive(name) else "down")
            out[name] = {"state": state, "pid": pid, "restarts_1h": len(st.restarts),
                         "last_exit": st.last_exit}
        return out

    # --- process control ---
    def _alive(self, name: str) -> bool:
        st = self.states.get(name)
        if not st:
            return False
        if st.proc is not None:
            return st.proc.poll() is None
        if st.adopted:
            try:
                p = psutil.Process(st.adopted)
                return p.status() != psutil.STATUS_ZOMBIE
            except psutil.NoSuchProcess:
                return False
            except psutil.AccessDenied:
                return True
        return False

    def _find_existing(self, t: dict) -> int | None:
        match = str(t.get("match") or "").strip().lower()
        if not match:
            return None
        for p in psutil.process_iter(["pid", "cmdline"]):
            cmd = " ".join(p.info.get("cmdline") or []).lower()
            if match in cmd and "jarvis" not in cmd:
                return p.info["pid"]
        return None

    def _start(self, name: str) -> None:
        t, st = self.targets[name], self.states[name]
        ok, why = check_shell(t["command"])  # re-check right before exec
        if not ok:
            raise RuntimeError(f"{name}: {why}")
        logf = Path(config.LOG_DIR) / f"watchdog_{name}.log"
        logf.parent.mkdir(parents=True, exist_ok=True)
        if logf.exists() and logf.stat().st_size > LOG_KEEP_BYTES:
            logf.replace(logf.with_suffix(".log.1"))
        with open(logf, "ab") as out:
            st.proc = subprocess.Popen(shlex.split(t["command"]), cwd=os.path.expanduser(t.get("cwd") or "~"),
                                       stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                       start_new_session=True)
        st.adopted = None
        st.started_at = time.time()

    def _terminate(self, name: str) -> None:
        st = self.states.get(name)
        if not st or st.proc is None or st.proc.poll() is not None:
            return
        try:
            os.killpg(st.proc.pid, signal.SIGTERM)
            st.proc.wait(5)
        except (ProcessLookupError, PermissionError):
            pass
        except subprocess.TimeoutExpired:
            try:
                os.killpg(st.proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    def backoff(self, fails: int) -> float:
        return min(config.WATCHDOG_BACKOFF_BASE_S * (2 ** max(0, fails - 1)), config.WATCHDOG_BACKOFF_MAX_S)

    # --- loop ---
    def tick(self) -> None:
        self.reload()
        for name in list(self.targets):
            self.check(name)

    def check(self, name: str) -> None:
        now = time.time()
        st = self.states.setdefault(name, TargetState())
        st.restarts = [t for t in st.restarts if now - t < 3600]
        if self._alive(name):
            if st.fails and now - st.started_at >= config.WATCHDOG_STABLE_S:
                st.fails = 0  # stable again: reset the backoff
            return
        if st.ever_started and (st.proc is not None or st.adopted):  # it was up and has died
            code = st.proc.returncode if st.proc is not None else None
            st.last_exit = f"exit code {code}" if code is not None else "exited"
            st.proc, st.adopted = None, None
            st.fails += 1
            st.next_start = now + self.backoff(st.fails)
            self.log.warning("%s crashed (%s); restart in %.0f s", name, st.last_exit, st.next_start - now)
            notify.notify(f"Crashed: {name}", f"{name} stopped ({st.last_exit}) after "
                          f"{int(now - st.started_at)} s. Restarting in {int(st.next_start - now)} s.",
                          level="warning", source="watchdog")
            return
        if now < st.next_start:
            return
        if not st.ever_started:
            pid = self._find_existing(self.targets[name])
            if pid:
                st.adopted, st.started_at, st.ever_started = pid, now, True
                self.log.info("%s already running (pid %d): adopted", name, pid)
                return
        if st.ever_started and len(st.restarts) >= config.WATCHDOG_MAX_RESTARTS_PER_HOUR:
            if not st.gave_up:
                st.gave_up = True
                self.log.error("%s: %d restarts in the last hour, giving up", name, len(st.restarts))
                notify.notify(f"Watchdog gave up: {name}",
                              f"{name} crashed {len(st.restarts)} times in an hour; not restarting it "
                              f"until the hour is over. Last: {st.last_exit}.", level="error", source="watchdog")
            return
        st.gave_up = False
        restart = st.ever_started
        try:
            self._start(name)
        except (OSError, RuntimeError, ValueError) as e:
            st.fails += 1
            st.next_start = now + self.backoff(st.fails)
            if restart:
                st.restarts.append(now)  # failed restarts count toward the hourly cap
            st.last_exit = f"failed to start: {e}"[:200]
            self.log.warning("%s: %s; retry in %.0f s", name, st.last_exit, st.next_start - now)
            if st.fails == 1:
                notify.notify(f"Watchdog cannot start {name}", st.last_exit, level="warning", source="watchdog")
            return
        st.ever_started = True
        if restart:
            st.restarts.append(now)
            self.log.info("%s restarted (pid %d, restart %d this hour)", name, st.proc.pid, len(st.restarts))
            notify.notify(f"Restarted: {name}", f"{name} restarted (pid {st.proc.pid}, "
                          f"{len(st.restarts)} restart(s) this hour).", level="info", source="watchdog")
        else:
            self.log.info("%s started (pid %d)", name, st.proc.pid)

    def teardown(self) -> None:
        for name in list(self.states):
            self._terminate(name)
