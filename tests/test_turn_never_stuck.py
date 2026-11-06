"""11-06: one request hung inside and every later message waited forever ('Hello' showed only the dots)."""
from __future__ import annotations

import threading
import time

from jarvis.api.turns import Engine
from jarvis.core import config


class T:
    def __init__(self):
        self.events, self.closed = [], False

    def push(self, ev):
        self.events.append(ev)


def test_busy_then_left_behind(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "TURN_WAIT_S", 0.2)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    eng = Engine.__new__(Engine)
    eng.turn_lock, eng.current, eng.current_text, eng.current_t = threading.Lock(), None, "", 0.0
    eng.turn_lock.acquire()  # a turn holds it
    eng.current, eng.current_text, eng.current_t = T(), "switch to the coding agent", time.monotonic()
    t = T()
    assert eng._take_turn(t) is None and "still working on your last request" in t.events[0]["text"]
    monkeypatch.setattr(config, "TURN_STUCK_S", 0.0)  # now it has been far too long
    lock = eng._take_turn(T())
    assert lock is not None and lock is eng.turn_lock and (tmp_path / "stuck_turns.log").read_text().count("turn stuck")
