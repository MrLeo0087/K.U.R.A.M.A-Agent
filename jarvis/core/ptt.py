"""Hold-to-talk: hold a key combo (default Ctrl+Space), speak, let go -> KURAMA hears it, without opening the chat.

Runs in the API server (pynput, X11, ~0 CPU: it only wakes on key events). On key down it writes "down" to
data/ptt.state and sends SIGUSR2 to the mini window (scripts/kurama_wallpaper.py, pid in data/wallpaper.pid);
the window's hidden chat page records, and on "up" transcribes and sends; what you said and the reply appear in
the caption beside the KURAMA button. If another key is pressed while holding (Ctrl + Space + C) or
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


def _norm(name: str) -> str:
    """ctrl_l / ctrl_r -> ctrl, alt_gr -> alt, shift_r -> shift, cmd_l -> cmd; other keys as they are."""
    n = (name or "").lower()
    for m in ("ctrl", "alt", "shift", "cmd"):
        if n == m or n.startswith(m + "_"):
            return m
    return n


class Holder:
    """Key events -> down / up / cancel (pure logic, testable without a keyboard). combo: "ctrl+space" or one key.
    Down: the main key is pressed while every modifier is held. Up: a modifier is released, or the main key is
    released and not pressed again within PTT_DEBOUNCE_S (a held Space auto-repeats as release+press pairs)."""

    def __init__(self, combo: str, tell=_tell, now=time.monotonic, min_hold: float | None = None, schedule=None):
        parts = [_norm(p.strip()) for p in combo.split("+") if p.strip()]
        self.main, self.mods = parts[-1], set(parts[:-1])
        self.tell, self.now = tell, now
        self.min_hold = config.PTT_MIN_HOLD_S if min_hold is None else min_hold
        self.schedule = schedule or _timer
        self.held: set[str] = set()
        self.down_at: float | None = None
        self.spoiled = False
        self.pending = None  # the delayed "main key really released" check

    def press(self, name: str) -> None:
        n = _norm(name)
        if n == self.main and self.down_at is not None:  # auto-repeat while holding: not a release
            self._cancel_pending()
        elif n == self.main and self.mods <= self.held:
            self.down_at, self.spoiled = self.now(), False
            self.tell("down")
        elif self.down_at is not None and n not in self.mods and not self.spoiled:  # a shortcut, not talking
            self.spoiled = True
            self.tell("cancel")
        self.held.add(n)

    def release(self, name: str) -> None:
        n = _norm(name)
        self.held.discard(n)
        if self.down_at is None:
            return
        if n in self.mods or n in ("ctrl", "alt", "shift", "cmd"):  # modifiers never auto-repeat
            self._finish()
        elif n == self.main:
            self._cancel_pending()
            self.pending = self.schedule(config.PTT_DEBOUNCE_S, self._finish)

    def _cancel_pending(self) -> None:
        if self.pending is not None:
            self.pending.cancel()
            self.pending = None

    def _finish(self) -> None:
        self._cancel_pending()
        if self.down_at is None:
            return
        held, self.down_at = self.now() - self.down_at, None
        if not self.spoiled:
            self.tell("up" if held >= self.min_hold else "cancel")


def _timer(delay: float, fn):
    t = threading.Timer(delay, fn)
    t.daemon = True
    t.start()
    return t


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
