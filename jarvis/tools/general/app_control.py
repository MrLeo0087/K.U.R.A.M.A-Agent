"""app_control: drive the app on screen — shortcuts, keys, typing, click by name, or a free-form task (safe;
risky clicks like send/delete/pay ask first)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="windows", safety="safe",
      description="Control the app on screen: tab/page shortcuts, press keys, type text, click a named button/tab/"
                  "menu, or do any free-form task in an app (e.g. 'turn on dark mode in settings').")
def app_control(action: Literal["task", "click", "type", "press", "shortcut", "enable"] = "task", text: str = "",
                app: str = "") -> str:
    """Do something inside an app.

    Args:
        action: task (free-form, multi-step), click (a named element), type (text), press (keys like 'ctrl t'),
            shortcut (new_tab, close_tab, back, reload, zoom_in, tab:3 ...), enable (one-time setup for browsers).
        text: The task, element name, text, keys or shortcut name.
        app: Optional app to bring to the front first (brave, files, terminal, code, settings).
    """
    from jarvis.core import uiagent as ui
    if action == "enable":
        return ui.enable_accessibility()
    if not text.strip():
        return "error: say what to do"
    if action == "shortcut":
        name, _, n = text.partition(":")
        return ui.shortcut(name.strip(), int(n) if n.strip().isdigit() else 0, app)
    if action == "press":
        return ui.press(text, app)
    if action == "type":
        return ui.type_into(text, app)
    if action == "click":
        return ui.click_name(text, app) or ui.run_task(f"click {text}", app)
    return ui.run_task(text, app)
