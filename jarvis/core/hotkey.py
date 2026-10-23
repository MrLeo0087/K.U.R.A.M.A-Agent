"""Global push-to-talk hotkey via pynput (X11).

Mode: TOGGLE (press, don't hold). Default <ctrl>+<alt>+j (config.HOTKEY_PTT / env JARVIS_HOTKEY).
  - idle      -> press starts listening; recording stops by itself after ~0.8 s of silence
  - listening -> press ends recording now (keeps what was said)
  - speaking  -> press interrupts Jarvis and starts listening
The voice loop decides what a press means; this module only parses the combo and fires a callback.
"""
from __future__ import annotations

import logging
import os
from typing import Callable

from jarvis.core import config

log = logging.getLogger(__name__)

_ALIASES = {
    "control": "ctrl", "ctl": "ctrl", "ctrl_l": "ctrl_l", "ctrl_r": "ctrl_r",
    "option": "alt", "meta": "cmd", "super": "cmd", "win": "cmd", "windows": "cmd",
    "altgr": "alt_gr", "return": "enter", "escape": "esc", "spacebar": "space",
}
_MODIFIERS = {"ctrl", "ctrl_l", "ctrl_r", "alt", "alt_l", "alt_r", "alt_gr", "shift", "shift_l",
              "shift_r", "cmd", "cmd_l", "cmd_r"}
_SPECIAL = {"space", "enter", "esc", "tab", "backspace", "delete", "insert", "home", "end",
            "page_up", "page_down", "up", "down", "left", "right", "pause", "menu",
            "print_screen", "scroll_lock", "caps_lock", "num_lock",
            *(f"f{i}" for i in range(1, 21))}


class HotkeyError(RuntimeError):
    pass


def parse_hotkey(combo: str) -> str:
    """Validate a combo like "<ctrl>+<alt>+j" or "Ctrl+Alt+J"; return pynput's canonical form."""
    if not combo or not combo.strip():
        raise HotkeyError("empty hotkey")
    mods: list[str] = []
    keys: list[str] = []
    for raw in combo.strip().lower().split("+"):
        tok = raw.strip().strip("<>").strip()
        if not tok:
            raise HotkeyError(f"bad hotkey {combo!r}")
        tok = _ALIASES.get(tok, tok)
        if tok in _MODIFIERS:
            if f"<{tok}>" in mods:
                raise HotkeyError(f"duplicate modifier in {combo!r}")
            mods.append(f"<{tok}>")
        elif tok in _SPECIAL:
            keys.append(f"<{tok}>")
        elif len(tok) == 1 and tok.isprintable():
            keys.append(tok)
        else:
            raise HotkeyError(f"unknown key {raw.strip()!r} in {combo!r}")
    if len(keys) != 1:
        raise HotkeyError(f"hotkey {combo!r} needs exactly one non-modifier key")
    if not mods and keys[0] not in {f"<f{i}>" for i in range(1, 21)} | {"<pause>"}:
        raise HotkeyError(f"hotkey {combo!r} needs a modifier (or use an F-key)")
    return "+".join(mods + keys)


def pretty(combo: str) -> str:
    return "+".join(p.strip("<>").capitalize() for p in parse_hotkey(combo).split("+"))


class HotkeyListener:
    """Run `callback` whenever the global combo is pressed. start()/stop()."""

    def __init__(self, combo: str | None = None, callback: Callable[[], None] | None = None):
        self.combo = parse_hotkey(combo or config.HOTKEY_PTT)
        self.callback = callback or (lambda: None)
        self._listener = None

    def _fire(self) -> None:
        try:
            self.callback()
        except Exception:  # never let a callback kill the X11 listener thread
            log.exception("hotkey callback failed")

    def start(self) -> "HotkeyListener":
        if not os.environ.get("DISPLAY"):
            raise HotkeyError("no X11 DISPLAY: global hotkeys need an X session")
        try:
            from pynput import keyboard

            self._listener = keyboard.GlobalHotKeys({self.combo: self._fire})
            self._listener.start()
        except Exception as e:
            raise HotkeyError(f"cannot start hotkey listener: {e}") from e
        return self

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
