#!/usr/bin/python3
"""What the Files app (Nautilus) shows: run with the SYSTEM python3 (PyGObject: Gdk, Gio, Atspi). Prints JSON:
{"top": "files" | "vscode" | "browser" | null,   # which of these was used most recently (highest in the window stack)
 "folder": "/abs/path" | null,                  # the Files window's folder (the most recent window when several)
 "selected": ["/abs/path", ...]}                # what is selected in it (read only when Files is the top app)
On demand only (KURAMA's context, ~0.2 s; +0.5 s to read a selection): nothing runs while idle.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlparse

import gi

gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib  # noqa: E402

KINDS = {"org.gnome.nautilus": "files", "code": "vscode", "brave-browser": "browser", "google-chrome": "browser",
         "firefox": "browser", "chromium": "browser"}


_TOP_XID = [0]
_PICK: list = []  # how the window was chosen (evidence for the log)


def _classes() -> dict[int, tuple[str, str]]:
    """xid -> (kind, title) for Files / VS Code / browser windows (wmctrl)."""
    out = {}
    try:
        lines = subprocess.run(["wmctrl", "-lx"], capture_output=True, text=True, timeout=3).stdout.splitlines()
    except (OSError, subprocess.TimeoutExpired):
        return out
    for ln in lines:
        parts = ln.split(None, 4)
        if len(parts) < 4:
            continue
        cls = parts[2].lower()
        for key, kind in KINDS.items():
            if cls.startswith(key) or f".{key}" in cls:
                out[int(parts[0], 16)] = (kind, parts[4] if len(parts) > 4 else "")
                break
    return out


def _top() -> tuple[str | None, str]:
    """The most recently used of Files / VS Code / browser (top of the stacking order) and its window title."""
    known = _classes()
    screen = Gdk.Screen.get_default()
    stack = screen.get_window_stack() if screen else []
    for w in reversed(stack or []):  # top first
        try:
            xid = w.get_xid()
        except Exception:  # noqa: BLE001
            continue
        if xid in known:
            _TOP_XID[0] = xid
            return known[xid]
    return None, ""


def _naut_xids() -> list[int]:
    """Files windows' X ids in creation order (an X id grows with each new window)."""
    return sorted(x for x, (k, _) in _classes().items() if k == "files")


def _folders() -> list[str]:
    """Open Files windows' folders (D-Bus org.freedesktop.FileManager1.OpenWindowsWithLocations)."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        v = bus.call_sync("org.gnome.Nautilus", "/org/freedesktop/FileManager1", "org.freedesktop.DBus.Properties",
                          "Get", GLib.Variant("(ss)", ("org.freedesktop.FileManager1", "OpenWindowsWithLocations")),
                          None, Gio.DBusCallFlags.NONE, 1500, None)
        locs = v.unpack()[0]
    except Exception:  # noqa: BLE001
        return []
    out = []
    for uris in locs.values():
        for u in uris:
            p = urlparse(u)
            if p.scheme == "file":
                out.append(unquote(p.path))
    return out


_SELECTED_RAW: list = []


def _selected(title: str, folder: str, folders: list[str] | None = None) -> tuple[list[str], str]:
    """Names selected in the Files window titled `title` (accessibility tree), as paths, and the folder they are in
    (the window's folder, else any open Files folder that holds them: a wrong window guess copied /home/leo)."""
    try:
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
    except (ValueError, ImportError):
        return []
    desk = Atspi.get_desktop(0)
    names: list[str] = []
    raw: list[tuple[str, str]] = []
    for i in range(desk.get_child_count()):
        app = desk.get_child_at_index(i)
        if not app or "nautilus" not in (app.get_name() or "").lower():
            continue
        frames = [app.get_child_at_index(w) for w in range(app.get_child_count())]
        frames = [f for f in frames if f is not None]
        pick = [f for f in frames if f.get_state_set().contains(Atspi.StateType.ACTIVE)]  # the focused one
        why = "active"
        if not pick and len(frames) > 1:  # several windows (two were both "Tara", full screen): the TOP one,
            xids = _naut_xids()  # matched by creation order (frames are listed in the order they were made)
            if len(xids) == len(frames) and _TOP_XID[0] in xids:
                pick, why = [frames[xids.index(_TOP_XID[0])]], "top by creation order"
            else:
                pick, why = [f for f in frames if (f.get_name() or "") == title][:1], "title"
        if not pick:
            pick, why = frames[:1], "only window"
        _PICK[:] = [why, len(frames)]
        for win in pick:
            seen = [0]

            def walk(a, depth=0):  # ANY element marked selected (cell, row, list / grid item: it differs by view)
                if a is None or depth > 30 or seen[0] > 8000:
                    return
                seen[0] += 1
                try:
                    if a.get_state_set().contains(Atspi.StateType.SELECTED) and a.get_name():
                        raw.append((a.get_role_name(), a.get_name()))
                except Exception:  # noqa: BLE001
                    pass
                for k in range(a.get_child_count()):
                    walk(a.get_child_at_index(k), depth + 1)
            walk(win)
    _SELECTED_RAW[:] = raw[:20]  # evidence for the log
    names = list(dict.fromkeys(n for _, n in raw if "/" not in n))  # entries only: never the path bar's full path
    for base in [folder] + [f for f in (folders or []) if f != folder]:
        hits = [str(Path(base) / n) for n in names if (Path(base) / n).exists()]
        if hits:
            return hits, base
    return [], folder


def main() -> dict:
    kind, title = _top()
    folders = _folders()
    folder = None
    if folders:  # the window whose title is the folder's name (title = folder name); else the first
        folder = next((f for f in folders if title and Path(f).name == title.strip()), None) or \
                 next((f for f in folders if title and title.strip() in ("Home",) and f == str(Path.home())), None) or \
                 folders[0]
    out = {"top": kind, "folder": folder, "selected": [], "title": title, "folders": folders}
    if kind == "files" and folder:
        out["selected"], out["folder"] = _selected(title, folder, folders)
        out["sel_raw"] = _SELECTED_RAW
        out["pick"] = _PICK
    return out


if __name__ == "__main__":
    try:
        print(json.dumps(main()))
    except Exception as e:  # noqa: BLE001 - never a traceback for KURAMA
        print(json.dumps({"top": None, "folder": None, "selected": [], "error": f"{type(e).__name__}: {e}"}))
