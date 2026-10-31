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
    pttlog(f"key {state}")
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
    n = {"super": "cmd", "win": "cmd", "meta": "cmd", "control": "ctrl"}.get(n, n)
    for m in ("ctrl", "alt", "shift", "cmd"):
        if n == m or n.startswith(m + "_"):
            return m
    return n


def pttlog(line: str) -> None:
    """data/logs/ptt.log: every hold-to-talk step (key, window, page) — evidence when it stops by itself."""
    try:
        path = config.LOG_DIR / "ptt.log"
        if path.exists() and path.stat().st_size > 100_000:
            path.write_text("".join(path.read_text(encoding="utf-8").splitlines(True)[-400:]), encoding="utf-8")
        with path.open("a", encoding="utf-8") as fh:
            fh.write(time.strftime("%H:%M:%S.") + f"{time.time() % 1:.2f}"[2:] + " server " + line + "\n")
    except OSError:
        pass


class Holder:
    """Key events -> down / up / cancel (pure logic, testable without a keyboard). combo: "ctrl+space" or one key.
    Down: the main key is pressed while every modifier is held. Up: a modifier is released, or the main key is
    released and not pressed again within PTT_DEBOUNCE_S (a held Space auto-repeats as release+press pairs)."""

    def __init__(self, combo: str, tell=_tell, now=time.monotonic, min_hold: float | None = None, schedule=None,
                 dismiss: str = ""):
        parts = [_norm(p.strip()) for p in combo.split("+") if p.strip()]
        self.main, self.mods = parts[-1], set(parts[:-1])
        self.tell, self.now = tell, now
        self.min_hold = config.PTT_MIN_HOLD_S if min_hold is None else min_hold
        self.schedule = schedule or _timer
        self.held: set[str] = set()
        self.down_at: float | None = None
        self.spoiled = False
        self.pending = None  # the delayed "main key really released" check
        d = (dismiss or "").strip().lower()
        self.double = d == "double"  # double-tap the talk key = dismiss
        # "double:shift" = double-tap ANOTHER key (Shift) = dismiss
        self.dtap_key = _norm(d.split(":", 1)[1]) if d.startswith("double:") else None
        self.dtap_at: float | None = None
        self.dtap_clean = False
        self.dtap_last = -1e9
        dparts = [] if (self.double or self.dtap_key) else [_norm(p.strip()) for p in d.split("+") if p.strip()]
        self.dismiss = (set(dparts[:-1]), dparts[-1]) if dparts else None
        # one modifier alone (e.g. Left Ctrl): listen only after it is held alone this long, so Ctrl+C never does
        self.solo = not self.mods and self.main in ("ctrl", "alt", "shift", "cmd")
        self.waiting = None  # the delayed "start listening" while the solo key is held
        self.pressed_at: float | None = None
        self.last_tap = -1e9

    def press(self, name: str) -> None:
        n = _norm(name)
        self._dtap_press(n)
        if self.solo:
            self._solo_press(n)
            return
        if self.dismiss and n == self.dismiss[1] and self.dismiss[0] <= self.held and self.down_at is None:
            if n not in self.held:  # Super+X: close the caption / stop speaking (once per press, not on repeat)
                self.tell("dismiss")
            self.held.add(n)
            return
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
        self._dtap_release(n)
        if self.solo:
            self._solo_release(n)
            return
        self.held.discard(n)
        if self.down_at is None:
            return
        if n in self.mods or n in ("ctrl", "alt", "shift", "cmd"):  # modifiers never auto-repeat
            self._finish()
        elif n == self.main:
            self._cancel_pending()
            self.pending = self.schedule(config.PTT_DEBOUNCE_S, self._finish)

    # ---- double-tap of another key (dismiss "double:shift") ----
    def _dtap_press(self, n: str) -> None:
        if not self.dtap_key:
            return
        if n == self.dtap_key:
            if self.dtap_at is None:
                self.dtap_at, self.dtap_clean = self.now(), True
        else:  # another key in between (Shift+A = a capital letter): not a tap
            self.dtap_clean, self.dtap_last = False, -1e9

    def _dtap_release(self, n: str) -> None:
        if not self.dtap_key or n != self.dtap_key or self.dtap_at is None:
            return
        held, self.dtap_at = self.now() - self.dtap_at, None
        if not self.dtap_clean or held >= config.PTT_START_DELAY_S:
            self.dtap_last = -1e9
            return
        now = self.now()
        if now - self.dtap_last <= config.PTT_DOUBLE_TAP_S:
            self.dtap_last = -1e9
            self.tell("dismiss")
        else:
            self.dtap_last = now

    # ---- one modifier alone: hold = talk (after PTT_START_DELAY_S), double-tap = dismiss ----
    def _solo_press(self, n: str) -> None:
        if n == self.main:
            if self.pressed_at is None:  # first press (a held modifier doesn't repeat, but be safe)
                self.pressed_at, self.spoiled = self.now(), False
                self.waiting = self.schedule(config.PTT_START_DELAY_S, self._solo_start)
            return
        if self.pressed_at is not None and not self.spoiled:  # Ctrl + another key = a shortcut
            self.spoiled = True
            if self.waiting is not None:
                self.waiting.cancel()
                self.waiting = None
            if self.down_at is not None:
                self.down_at = None
                self.tell("cancel")
        self.last_tap = -1e9

    def _solo_start(self) -> None:
        self.waiting = None
        if self.pressed_at is not None and not self.spoiled and self.down_at is None:
            self.down_at = self.now()
            self.tell("down")

    def _solo_release(self, n: str) -> None:
        if n != self.main or self.pressed_at is None:
            return
        held, self.pressed_at = self.now() - self.pressed_at, None
        if self.waiting is not None:
            self.waiting.cancel()
            self.waiting = None
        if self.down_at is not None:  # it was listening: send
            self.down_at = None
            if not self.spoiled:
                self.tell("up")
            return
        if self.spoiled or held >= config.PTT_START_DELAY_S:
            return
        now = self.now()  # a quick tap: two within PTT_DOUBLE_TAP_S = dismiss
        if self.double and now - self.last_tap <= config.PTT_DOUBLE_TAP_S:
            self.last_tap = -1e9
            self.tell("dismiss")
        else:
            self.last_tap = now

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


SETTINGS_FILE = config.DATA_DIR / "ptt.json"  # set from KURAMA's Settings > Shortcuts (wins over .env)


def settings() -> dict:
    """The talk key and the close-reply action in use: data/ptt.json, else .env / config."""
    import json
    out = {"key": config.PTT_KEY, "dismiss": config.PTT_DISMISS_KEY, "enabled": config.PTT_ENABLED}
    with contextlib.suppress(OSError, ValueError):
        out.update({k: v for k, v in json.loads(SETTINGS_FILE.read_text(encoding="utf-8")).items() if k in out})
    return out


def _valid(combo: str) -> bool:
    parts = [p.strip() for p in (combo or "").lower().split("+")]
    return bool(parts) and all(p and len(p) <= 12 and p.replace("_", "").isalnum() for p in parts)


def apply(key: str, dismiss: str, enabled: bool = True) -> dict:
    """Save new shortcuts and restart the key watcher at once (no KURAMA restart)."""
    import json
    key, dismiss = (key or "").strip().lower(), (dismiss or "").strip().lower()
    if not _valid(key):
        return {"ok": False, "error": f"not a key or combo: {key!r} (e.g. shift, ctrl_l, super+z)"}
    if dismiss not in ("double", "") and not _valid(dismiss.removeprefix("double:")):
        return {"ok": False, "error": f"not a key or combo: {dismiss!r} (e.g. double, super+x)"}
    SETTINGS_FILE.write_text(json.dumps({"key": key, "dismiss": dismiss, "enabled": bool(enabled)}), encoding="utf-8")
    stop()
    on = start()
    return {"ok": True, **settings(), "running": on}


def start() -> bool:
    """Start the key watcher once (server start). False when disabled or no X11 keyboard access."""
    global _listener
    cfg = settings()
    if not cfg["enabled"]:
        return False
    with _lock:
        if _listener is not None:
            return True
        try:
            from pynput import keyboard
        except Exception as e:  # noqa: BLE001
            log.warning("hold-to-talk off: pynput unavailable (%s)", e)
            return False
        h = Holder(cfg["key"], dismiss=cfg["dismiss"])
        _listener = keyboard.Listener(on_press=lambda k: h.press(_name(k)), on_release=lambda k: h.release(_name(k)))
        _listener.daemon = True
        _listener.start()
        log.info("hold-to-talk on: hold %s and speak", cfg["key"])
        with contextlib.suppress(OSError):  # proof it runs (the window ignores this state)
            STATE_FILE.write_text(f"ready {time.time():.3f} {cfg['key']}\n", encoding="utf-8")
        return True


def stop() -> None:
    global _listener
    with _lock:
        if _listener is not None:
            _listener.stop()
            _listener = None
