"""Copy history worker ("clipboard_watch"): every text the user copies (Ctrl+C in any app) goes to the SQLite
clipboard table, so "what did I copy 10 minutes ago?" works.

Event-driven: X11 XFixes tells us when the clipboard owner changes (no polling; the thread sleeps in select()).
Private by design: kept CLIPBOARD_KEEP_H (24 h) and at most CLIPBOARD_HISTORY_MAX items, only on this laptop;
password managers' copies (KeePassXC's 'x-kde-passwordManagerHint', Bitwarden/1Password/KeePass windows) and
password-looking strings are never stored.

It also watches the PRIMARY selection (what is highlighted) and hands the newest highlight made outside KURAMA to
rewrite.remember_selection (memory only, never stored): typed requests like "what does this mean" use it."""
from __future__ import annotations

import re
import select
import subprocess
import time

from jarvis.core import config, store
from jarvis.workers.base import Worker

_SECRET_APPS = re.compile(r"keepass|bitwarden|1password|lastpass|enpass|seahorse|gnome-keyring|pass(?:word)?\s*manager", re.I)


def looks_secret(text: str) -> bool:
    """One 8-128 char token mixing upper, lower, digits (and symbols): most likely a password or a key."""
    t = text.strip()
    if not (8 <= len(t) <= 128) or re.search(r"\s", t) or re.match(r"https?://", t):
        return False
    kinds = sum(bool(re.search(p, t)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^\w]"))
    return kinds >= 3 and not re.fullmatch(r"[\w.-]+@[\w.-]+", t)  # an email address is fine


def _xclip(*args: str, timeout: float = 2.0) -> str:
    try:
        return subprocess.run(["xclip", "-selection", "clipboard", *args], capture_output=True,
                              timeout=timeout).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _xclip_sel(selection: str, timeout: float = 2.0) -> str:
    try:
        return subprocess.run(["xclip", "-selection", selection.lower(), "-o"], capture_output=True,
                              timeout=timeout).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired):
        return ""


def keep(text: str, targets: str, owner_class: str) -> bool:
    if not text.strip() or len(text) > config.CLIPBOARD_MAX_CHARS or text.startswith("__kurama_copy_"):
        return False
    if "x-kde-passwordManagerHint" in targets or _SECRET_APPS.search(owner_class or ""):
        return False
    return not looks_secret(text)


def is_copy_event(ev, atom: int) -> bool:
    """XFixes 'the clipboard has a new owner' = someone copied. python-xlib builds this event's class per display,
    so isinstance(ev, xfixes.SetSelectionOwnerNotify) is False: check its name and selection instead (that check
    silently dropped every copy at first)."""
    return type(ev).__name__ == "SetSelectionOwnerNotify" and getattr(ev, "selection", None) == atom


class ClipboardWatch(Worker):
    name = "clipboard_watch"
    interval_s = 5.0
    selection = "CLIPBOARD"  # tests use a private selection, never the user's clipboard
    primary = "PRIMARY"

    def available(self) -> str | None:
        import os
        import shutil
        if not os.environ.get("DISPLAY"):
            return "no X display"
        if not shutil.which("xclip"):
            return "xclip missing"
        return None

    def setup(self) -> None:
        from Xlib import display
        from Xlib.ext import xfixes
        self.d = display.Display()
        if not self.d.has_extension("XFIXES"):
            raise RuntimeError("no XFixes extension")
        self.d.xfixes_query_version()
        self.atom = self.d.get_atom(self.selection)
        self.d.xfixes_select_selection_input(self.d.screen().root, self.atom, xfixes.XFixesSetSelectionOwnerNotifyMask)
        self.patom = self.d.get_atom(self.primary)
        self.d.xfixes_select_selection_input(self.d.screen().root, self.patom, xfixes.XFixesSetSelectionOwnerNotifyMask)
        self.d.flush()
        self.saved = 0
        self._sel_due = 0.0  # a highlight changed: read it once the mouse settles (debounce)
        self._sel_win: tuple = (None, "", "")

    def teardown(self) -> None:
        try:
            self.d.close()
        except Exception:  # noqa: BLE001
            pass

    def _owner_class(self, owner) -> str:
        try:
            w = owner
            for _ in range(4):
                cls = w.get_wm_class()
                if cls:
                    return " ".join(cls)
                w = w.query_tree().parent
                if not w:
                    break
        except Exception:  # noqa: BLE001 - the owner window may be gone already
            pass
        return ""

    def tick(self) -> None:
        """Wait for copies (up to ~4 min per tick, waking every second to notice a stop)."""
        end = time.monotonic() + 240
        fd = self.d.fileno()
        while not self.stopping and time.monotonic() < end:
            if self._sel_due and time.monotonic() >= self._sel_due and not self.d.pending_events():
                self._sel_due = 0.0
                self._read_selection()
            if not self.d.pending_events():
                wait = max(0.05, self._sel_due - time.monotonic()) if self._sel_due else 1.0
                select.select([fd], [], [], min(wait, 1.0))
                if not self.d.pending_events():
                    continue
            ev = self.d.next_event()
            if is_copy_event(ev, self.patom):
                self._sel_win = self._active()  # the highlight is made in the window that has focus
                self._sel_due = time.monotonic() + 0.35
                continue
            if not is_copy_event(ev, self.atom):
                continue
            time.sleep(0.05)  # let the new owner answer requests
            targets = _xclip("-t", "TARGETS", "-o")
            if "UTF8_STRING" not in targets and "STRING" not in targets and "text/plain" not in targets:
                continue  # an image or files, not text
            text = _xclip("-o")
            if keep(text, targets, self._owner_class(ev.owner)):
                last = store.clip_recent(1)
                if not last or last[0]["text"] != text:
                    store.clip_add(text)
                    self.saved += 1

    def _active(self) -> tuple:
        """(window id, title, class) of the focused window."""
        from Xlib import X
        try:
            root = self.d.screen().root
            a = root.get_full_property(self.d.intern_atom("_NET_ACTIVE_WINDOW"), X.AnyPropertyType)
            wid = a.value[0] if a and len(a.value) else None
            if not wid:
                return (None, "", "")
            w = self.d.create_resource_object("window", wid)
            nm = w.get_full_property(self.d.intern_atom("_NET_WM_NAME"), 0)
            cls = w.get_wm_class() or ()
            return (wid, nm.value.decode(errors="replace") if nm else "", " ".join(cls))
        except Exception:  # noqa: BLE001 - the window may be gone
            return (None, "", "")

    def _read_selection(self) -> None:
        from jarvis.core import rewrite
        wid, title, cls = self._sel_win
        inside = rewrite._is_kurama(title, tuple(cls.split()) or None)
        text = "" if inside else _xclip_sel(self.primary)
        if not inside and (not keep(text, "", cls) and text.strip()):
            return  # a password manager / secret-looking text: never remembered
        rewrite.remember_selection(text, wid, title[:60], cls, inside)

    def info(self) -> dict:
        return {"saved": getattr(self, "saved", 0)}
