#!/usr/bin/python3
"""Dump the clickable/typeable elements of the ACTIVE window via AT-SPI, as JSON on stdout.

Runs under the SYSTEM python (/usr/bin/python3 has python3-gi + Atspi; KURAMA's venv doesn't), in a short-lived
subprocess so the GObject libraries never stay in KURAMA's memory. No jarvis imports.
Usage: atspi_dump.py [app-name]   (default: the active window)\nOutput: {"app": str, "window": str, "items": [{"role", "name", "x", "y", "w", "h", "state"}]}
"""
import json
import sys
import time

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi  # noqa: E402

MAX_NODES = 4000
DEADLINE_S = 3.0
ROLES = {
    "push button", "toggle button", "check box", "radio button", "menu item", "check menu item",
    "radio menu item", "page tab", "link", "entry", "password text", "combo box", "list item", "table cell",
    "icon", "slider", "spin button", "tree item", "menu", "switch", "button", "text", "search box",
}


def _active_window(want: str = ""):
    """The focused window, or (with `want`) the first window of the app whose name contains it."""
    desk = Atspi.get_desktop(0)
    for i in range(desk.get_child_count()):
        app = desk.get_child_at_index(i)
        if app is None:
            continue
        if want and want.lower() not in (app.get_name() or "").lower():
            continue
        for j in range(app.get_child_count()):
            win = app.get_child_at_index(j)
            if win is not None and (want or win.get_state_set().contains(Atspi.StateType.ACTIVE)):
                return app, win
    return None, None


def main() -> None:
    app, win = _active_window(sys.argv[1] if len(sys.argv) > 1 else "")
    if win is None:
        print(json.dumps({"app": "", "window": "", "items": []}))
        return
    items, seen, stack, t0 = [], 0, [win], time.time()
    while stack and seen < MAX_NODES and time.time() - t0 < DEADLINE_S:
        node = stack.pop()
        seen += 1
        try:
            st = node.get_state_set()
            if not st.contains(Atspi.StateType.SHOWING):
                continue
            role = node.get_role_name()
            if role in ROLES:
                ext = node.get_extents(Atspi.CoordType.SCREEN)
                name = (node.get_name() or node.get_description() or "").strip()
                if role in ("text", "entry", "password text", "search box") and not name:
                    name = "(text field)"
                if ext.width > 2 and ext.height > 2 and ext.x >= 0 and ext.y >= 0 and name:
                    flags = [s for s, t in (("on", Atspi.StateType.CHECKED), ("selected", Atspi.StateType.SELECTED),
                                            ("focused", Atspi.StateType.FOCUSED)) if st.contains(t)]
                    items.append({"role": role, "name": name[:80], "x": ext.x, "y": ext.y, "w": ext.width,
                                  "h": ext.height, "state": ",".join(flags)})
            n = node.get_child_count()
            for k in range(min(n, 400) - 1, -1, -1):
                c = node.get_child_at_index(k)
                if c is not None:
                    stack.append(c)
        except Exception:
            continue
    print(json.dumps({"app": app.get_name() or "", "window": win.get_name() or "", "items": items}))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never hang/crash the caller
        print(json.dumps({"app": "", "window": "", "items": [], "error": str(e)}))
        sys.exit(0)
