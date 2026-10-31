"""kurama: about KURAMA itself: what it is and can do, rename it, its power mode, background jobs, clear the chat,
pause alerts, remote desktop, make a new tool when nothing fits (safe dispatcher)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool
from jarvis.tools.core._hub import Act, run

TABLE = {
    "about": Act("about_me", lambda a: {"topic": a.get("text", "overview")}),
    "can_you": Act("find_capability", lambda a: {"need": a.get("text")}),
    "rename": Act("set_my_name", lambda a: {"name": a.get("text")}),
    "mode": Act("power_mode", lambda a: {"mode": a.get("text", "status")}),
    "jobs": Act("jobs", lambda a: {"action": a.get("text", "list") if a.get("text") in ("list", "result", "cancel", "pause", "resume") else "list"}),
    "clear_chat": Act("reset_kurama", lambda a: {"level": "chat"}),
    "mute_alerts": Act("mute_alerts", lambda a: {"action": "on", "minutes": a.get("text", "")}),
    "remote": Act("remote_desktop", lambda a: {"stop": (a.get("text") or "").lower() in ("stop", "off")}),
    "make_tool": Act("make_tool", lambda a: {"task": a.get("text")}),
}


@tool(group="core", safety="safe",
      description="About KURAMA: about (what you are, where things are stored), can_you (is there a way to do X), rename, "
                  "mode (power mode), jobs (background jobs: is it done, progress, result, list, cancel, pause, resume), "
                  "clear_chat, mute_alerts, remote (remote desktop on/off), "
                  "make_tool (build a small new tool when nothing else fits).")
def kurama(action: Literal["about", "can_you", "rename", "mode", "jobs", "clear_chat", "mute_alerts", "remote", "make_tool"],
           text: str = "") -> str:
    """KURAMA itself.

    Args:
        action: What to do.
        text: The topic / the need / the new name / the mode / list|result|cancel|pause|resume / minutes / stop / the task.
    """
    return run(TABLE, {"action": action, "text": text})
