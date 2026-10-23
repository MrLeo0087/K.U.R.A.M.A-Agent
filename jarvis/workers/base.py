"""Worker base class: a tiny daemon = tick() every interval_s on its own thread.

  - interval_s is clamped to config.WORKER_MIN_INTERVAL_S (>= 5 s)
  - an exception in tick() is logged and the next tick waits interval * 2^errors (capped at
    WORKER_MAX_BACKOFF_S); a good tick resets the backoff
  - available() returns a reason to skip (e.g. "not configured") or None
  - info() is a small dict the supervisor writes to data/workers.json for tools to read
  - each worker logs to its own rotating file data/logs/worker_<name>.log (~1 MB x 3)
"""
from __future__ import annotations

import logging
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from jarvis.core import config

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def worker_logger(name: str) -> logging.Logger:
    """Logger jarvis.workers.<name> with its own RotatingFileHandler (added once)."""
    lg = logging.getLogger(f"jarvis.workers.{name}")
    path = Path(config.LOG_DIR) / f"worker_{name}.log"
    if not any(isinstance(h, RotatingFileHandler) and Path(h.baseFilename) == path.resolve()
               for h in lg.handlers):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            h = RotatingFileHandler(path, maxBytes=config.WORKER_LOG_BYTES,
                                    backupCount=config.WORKER_LOG_BACKUPS, encoding="utf-8")
            h.setFormatter(logging.Formatter(LOG_FORMAT))
            lg.addHandler(h)
        except OSError as e:  # read-only disk etc.: still log to the parent handlers
            logging.getLogger("jarvis.workers").warning("no log file for %s: %s", name, e)
    lg.setLevel(logging.INFO)
    return lg


class Worker:
    name = "worker"
    interval_s = 5.0

    def __init__(self, interval_s: float | None = None):
        self.interval_s = max(config.WORKER_MIN_INTERVAL_S, float(interval_s or self.interval_s))
        self.log = worker_logger(self.name)
        self.errors = 0  # consecutive failed ticks
        self.ticks = 0
        self.last_tick = 0.0
        self.last_error = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- override ---
    def available(self) -> str | None:
        """Reason this worker cannot run (it is then skipped), or None."""
        return None

    def setup(self) -> None:
        pass

    def tick(self) -> None:
        raise NotImplementedError

    def teardown(self) -> None:
        pass

    def info(self) -> dict:
        return {}

    # --- machinery ---
    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def next_delay(self) -> float:
        if not self.errors:
            return self.interval_s
        return min(self.interval_s * (2 ** self.errors), max(config.WORKER_MAX_BACKOFF_S, self.interval_s))

    def run_once(self) -> bool:
        """One guarded tick. True when it succeeded."""
        try:
            self.tick()
        except Exception as e:
            self.errors += 1
            self.last_error = f"{type(e).__name__}: {e}"[:300]
            self.log.exception("tick failed (%d in a row); next try in %.0f s", self.errors,
                               self.next_delay())
            return False
        finally:
            self.ticks += 1
            self.last_tick = time.time()
        if self.errors:
            self.log.info("recovered after %d failed ticks", self.errors)
        self.errors = 0
        return True

    def _loop(self) -> None:
        try:
            self.setup()
        except Exception:
            self.log.exception("setup failed; worker not started")
            self.errors = max(self.errors, 1)
            return
        self.log.info("started (every %.0f s)", self.interval_s)
        try:
            while not self._stop.is_set():
                self.run_once()
                self._stop.wait(self.next_delay())
        finally:
            try:
                self.teardown()
            except Exception:
                self.log.exception("teardown failed")
            self.log.info("stopped")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name=f"worker-{self.name}", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout)

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def status(self) -> dict:
        out = {"state": "running" if self.alive else "stopped", "interval_s": self.interval_s,
               "ticks": self.ticks, "last_tick": round(self.last_tick, 1), "errors": self.errors,
               "last_error": self.last_error}
        try:
            info = self.info()
        except Exception as e:
            info = {"error": str(e)[:200]}
        if info:
            out["info"] = info
        return out
