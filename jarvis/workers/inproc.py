"""The background workers inside the server process (config.WORKERS_IN_SERVER, default on).

One Python process instead of two saves ~55 MB: the separate supervisor process was ~24 MB of interpreter, and its
Telegram bot loaded a second copy of LangChain + every tool on the first message (the server already has them).
Which workers run follows the power mode (jarvis.core.modes); reconcile_soon() applies a change at once.
A separate `python -m jarvis.workers` that is already running wins: then this one stays off.
"""
from __future__ import annotations

import logging
import threading

from jarvis.workers import status
from jarvis.workers.supervisor import HEARTBEAT_S, Supervisor

log = logging.getLogger("jarvis.workers")
_sup: Supervisor | None = None
_kick = threading.Event()


def running() -> bool:
    return _sup is not None and not _sup.stop_event.is_set()


def start() -> bool:
    """Start the in-server supervisor thread (False if another supervisor process already runs the workers)."""
    global _sup
    if running():
        return True
    other = status.read()
    if other and other.get("pid") and other.get("in_server") is not True:
        log.info("workers already run in pid %s; not starting them in the server", other.get("pid"))
        return False
    from jarvis.core import modes
    _sup = Supervisor(modes.desired_workers())
    _sup.in_server = True
    threading.Thread(target=_loop, args=(_sup,), name="kurama-workers", daemon=True).start()
    return True


def _loop(sup: Supervisor) -> None:
    from jarvis.core import modes
    try:
        sup.start()
        log.info("workers in the server: %s", ", ".join(sup.workers) or "(none)")
        while not sup.stop_event.is_set():
            _kick.wait(HEARTBEAT_S)
            _kick.clear()
            if sup.stop_event.is_set():
                break
            want = modes.desired_workers()
            if want != sup.names:
                sup.sync(want)
            sup.write_status()
    except Exception:  # noqa: BLE001 - never take the server down
        log.exception("in-server workers loop failed")


def reconcile_soon() -> None:
    """A power-mode change: sync the workers now instead of at the next heartbeat."""
    _kick.set()


def stop() -> None:
    global _sup
    sup, _sup = _sup, None
    if sup is not None:
        sup.stop_event.set()
        _kick.set()
        sup.shutdown()
