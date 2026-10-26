"""Supervisor: run the enabled workers in ONE process.

    python -m jarvis.workers                 # config.WORKERS_ENABLED (env JARVIS_WORKERS)
    python -m jarvis.workers --only a,b      # just these
    python -m jarvis.workers --list          # names, enabled, availability

SIGINT/SIGTERM stop every worker cleanly. data/workers.json holds the PID and each worker's state
(heartbeat every 10 s) and is removed on exit; a second supervisor refuses to start.
"""
from __future__ import annotations

import argparse
import importlib
import logging
import os
import signal
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from jarvis.core import config
from jarvis.workers import status
from jarvis.workers.base import LOG_FORMAT, Worker

log = logging.getLogger("jarvis.workers")

# name -> "module:Class" (imported lazily: only the workers that run cost RAM)
WORKERS: dict[str, str] = {
    "process_watch": "jarvis.workers.process_watch:ProcessWatcher",
    "resource_guard": "jarvis.workers.resource_guard:ResourceGuard",
    "crash_watchdog": "jarvis.workers.crash_watchdog:CrashWatchdog",
    "telegram_bot": "jarvis.workers.telegram_bot:TelegramBot",
    "daily_digest": "jarvis.workers.daily_digest:DailyDigest",
    "auto_theme": "jarvis.workers.auto_theme:AutoTheme",  # P9a
    "scheduler": "jarvis.workers.scheduler:Scheduler",  # P9b
    "timemachine": "jarvis.workers.timemachine:TimeMachine",
    "guard": "jarvis.workers.guard:Guard",
    "location_tracker": "jarvis.workers.location_tracker:LocationTracker",
}
HEARTBEAT_S = 10.0


def load(name: str) -> Worker:
    mod, cls = WORKERS[name].split(":")
    return getattr(importlib.import_module(mod), cls)()


def setup_logging(verbose: bool = True) -> None:
    root = logging.getLogger("jarvis")
    root.setLevel(logging.INFO)
    path = Path(config.LOG_DIR) / "workers.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(path, maxBytes=config.WORKER_LOG_BYTES,
                             backupCount=config.WORKER_LOG_BACKUPS, encoding="utf-8")
    fh.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(fh)
    if verbose:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(sh)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO lines carry the bot-token URL
    logging.getLogger("httpcore").setLevel(logging.WARNING)


class Supervisor:
    def __init__(self, names: list[str]):
        self.names = names
        self.workers: dict[str, Worker] = {}
        self.skipped: dict[str, str] = {}
        self.stop_event = threading.Event()
        self.started = time.time()

    def start(self) -> None:
        self.sync(self.names)

    def sync(self, names: list[str]) -> None:
        """Run exactly these workers: stop the ones no longer wanted, start the missing ones (a power-mode
        change takes effect live; a skipped worker is not retried while it stays wanted)."""
        self.names = list(names)
        for name in [n for n in self.workers if n not in names]:
            w = self.workers.pop(name)
            w._stop.set()
            w.stop(timeout=8.0)
            log.info("%s: stopped (power mode)", name)
        for name in [n for n in self.skipped if n not in names]:
            del self.skipped[name]
        for name in names:
            if name in self.workers or name in self.skipped:
                continue
            if name not in WORKERS:
                self.skipped[name] = "unknown worker"
                log.warning("%s: unknown worker, skipping", name)
                continue
            try:
                w = load(name)
                reason = w.available()
            except Exception as e:
                self.skipped[name] = f"failed to load: {e}"[:200]
                log.exception("%s: failed to load", name)
                continue
            if reason:
                self.skipped[name] = reason
                w.log.info("%s, skipping", reason)
                continue
            w.start()
            self.workers[name] = w
        self.write_status()

    def snapshot(self) -> dict:
        ws = {n: w.status() for n, w in self.workers.items()}
        ws.update({n: {"state": "skipped", "reason": r} for n, r in self.skipped.items()})
        return {"pid": os.getpid(), "started": round(self.started, 1), "workers": ws,
                "in_server": getattr(self, "in_server", False)}

    def write_status(self) -> None:
        try:
            status.write(self.snapshot())
        except OSError as e:
            log.warning("could not write status file: %s", e)

    def run(self, follow_mode: bool = False) -> None:
        """Heartbeat until stop_event (signal) is set; with follow_mode, also follow the power mode's workers."""
        while not self.stop_event.wait(HEARTBEAT_S):
            if follow_mode:
                from jarvis.core import modes
                want = modes.desired_workers()
                if want != self.names:
                    self.sync(want)
            self.write_status()

    def shutdown(self) -> None:
        for name, w in self.workers.items():
            w._stop.set()  # signal all first, then join: total shutdown ~= the slowest worker
        for name, w in self.workers.items():
            w.stop(timeout=8.0)
            if w.alive:
                log.warning("%s did not stop in time", name)
        status.remove()
        log.info("supervisor stopped")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m jarvis.workers", description="KURAMA background workers")
    ap.add_argument("--only", help="comma-separated worker names (default: config.WORKERS_ENABLED)")
    ap.add_argument("--list", action="store_true", help="list workers and exit")
    ap.add_argument("--quiet", action="store_true", help="log to file only")
    args = ap.parse_args(argv)
    if args.list:
        for name in WORKERS:
            try:
                reason = load(name).available()
            except Exception as e:
                reason = f"failed to load: {e}"
            on = "enabled" if name in config.WORKERS_ENABLED else "disabled"
            print(f"{name:15} {on:9} {reason or 'ready'}")
        running = status.read()
        print(status.summary() if running else "supervisor: not running")
        return 0
    if args.only:
        names = [n.strip() for n in args.only.split(",") if n.strip()]
    else:
        from jarvis.core import modes
        names = modes.desired_workers()  # the power mode's helpers (within config.WORKERS_ENABLED)
    existing = status.read()
    if existing:
        print(f"workers already running (pid {existing.get('pid')}); stop it first", file=sys.stderr)
        return 1
    setup_logging(verbose=not args.quiet)
    sup = Supervisor(names)

    def on_signal(signum, _frame):
        log.info("signal %s: shutting down", signal.Signals(signum).name)
        sup.stop_event.set()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    log.info("supervisor pid %d starting: %s", os.getpid(), ", ".join(names) or "(none)")
    try:
        sup.start()
        sup.run(follow_mode=not args.only)
    finally:
        sup.shutdown()
    return 0
