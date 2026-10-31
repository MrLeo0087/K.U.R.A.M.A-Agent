"""Hold-to-talk: hold one key (default Right Ctrl), speak, let go -> KURAMA hears it, without opening the chat.

Runs in the API server (pynput, X11, ~0 CPU: it only wakes on key events). On key down it writes "down" to
data/ptt.state and sends SIGUSR2 to the mini window (scripts/kurama_wallpaper.py, pid in data/wallpaper.pid);
the window's hidden chat page records, and on "up" transcribes and sends; what you said and the reply appear in
the caption beside the KURAMA button. If another key is pressed while holding (Right Ctrl + C = a shortcut) or
the hold is shorter than PTT_MIN_HOLD_S, it sends "cancel" instead: nothing is transcribed (0 tokens).
"""
from __future__ import annotations

import contextlib
import logging
import os
import signal
import threading
import time

from jarvis.core import config

log = logging.getLogger("jarvis.ptt")

STATE_FILE = config.DATA_DIR / "ptt.state"
PID_FILE = config.DATA_DIR / "wallpaper.pid"
_listener = None
_lock = threading.Lock()


def _tell(state: str) -> bool:
    """Write the state and poke the mini window. False when it isn't running."""
    try:
        STATE_FILE.write_text(f"{state} {time.time():.3f}\n", encoding="utf-8")
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGUSR2)
        return True
    except (OSError, ValueError) as e:
        log.debug("ptt %s not delivered: %s", state, e)
        return False


class Holder:
    """Key events -> down / up / cancel (pure logic, testable without a keyboard)."""

    def __init__(self, key_name: str, tell=_tell, now=time.monotonic, min_hold: float | None = None):
        self.key_name, self.tell, self.now = key_name, tell, now
        self.min_hold = config.PTT_MIN_HOLD_S if min_hold is None else min_hold
        self.down_at: float | None = None
        self.spoiled = False

    def press(self, name: str) -> None:
        if name == self.key_name:
            if self.down_at is None:  # X11 repeats: only the first press counts
                self.down_at, self.spoiled = self.now(), False
                self.tell("down")
        elif self.down_at is not None and not self.spoiled:  # a shortcut, not talking
            self.spoiled = True
            self.tell("cancel")

    def release(self, name: str) -> None:
        if name != self.key_name or self.down_at is None:
            return
        held, self.down_at = self.now() - self.down_at, None
        if self.spoiled:
            return
        self.tell("up" if held >= self.min_hold else "cancel")


def _name(key) -> str:
    return getattr(key, "name", None) or (getattr(key, "char", None) or "").lower()


def start() -> bool:
    """Start the key watcher once (server start). False when disabled or no X11 keyboard access."""
    global _listener
    if not config.PTT_ENABLED:
        return False
    with _lock:
        if _listener is not None:
            return True
        try:
            from pynput import keyboard
        except Exception as e:  # noqa: BLE001
            log.warning("hold-to-talk off: pynput unavailable (%s)", e)
            return False
        h = Holder(config.PTT_KEY)
        _listener = keyboard.Listener(on_press=lambda k: h.press(_name(k)), on_release=lambda k: h.release(_name(k)))
        _listener.daemon = True
        _listener.start()
        log.info("hold-to-talk on: hold %s and speak", config.PTT_KEY)
        with contextlib.suppress(OSError):  # proof it runs (the window ignores this state)
            STATE_FILE.write_text(f"ready {time.time():.3f} {config.PTT_KEY}\n", encoding="utf-8")
        return True


def stop() -> None:
    global _listener
    with _lock:
        if _listener is not None:
            _listener.stop()
            _listener = None
