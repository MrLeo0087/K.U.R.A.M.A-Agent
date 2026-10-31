"""kurama: about KURAMA itself: what it is and can do, rename it, its power mode, background jobs, clear the chat,
pause alerts, remote desktop, make a new tool when nothing fits (safe dispatcher)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool
from jarvis.tools.core._hub import Act, run

_JOB_ACTIONS = ("list", "add", "edit", "remove", "start", "result", "cancel", "pause", "resume")


def _job_args(text: str) -> dict:
    """'add write an essay' / 'edit 2 write it in Nepali' / 'cancel 3' / 'start' -> the jobs tool's arguments."""
    words = text.strip().split(maxsplit=1)
    action = words[0].lower() if words and words[0].lower() in _JOB_ACTIONS else "list"
    rest = words[1] if len(words) > 1 and action != "list" else ""
    if action == "add":
        return {"action": "add", "text": rest}
    if action == "edit":
        n, _, new = rest.partition(" ")
        return {"action": "edit", "job": n, "text": new}
    return {"action": action, "job": rest}


TABLE = {
    "about": Act("about_me", lambda a: {"topic": a.get("text", "overview")}),
    "can_you": Act("find_capability", lambda a: {"need": a.get("text")}),
    "rename": Act("set_my_name", lambda a: {"name": a.get("text")}),
    "mode": Act("power_mode", lambda a: {"mode": a.get("text", "status")}),
    "jobs": Act("jobs", lambda a: _job_args(a.get("text") or "")),
    "clear_chat": Act("reset_kurama", lambda a: {"level": "chat"}),
    "mute_alerts": Act("mute_alerts", lambda a: {"action": "on", "minutes": a.get("text", "")}),
    "remote": Act("remote_desktop", lambda a: {"stop": (a.get("text") or "").lower() in ("stop", "off")}),
    "make_tool": Act("make_tool", lambda a: {"task": a.get("text")}),
}


@tool(group="core", safety="safe",
      description="About KURAMA: about (what you are, where things are stored), can_you (is there a way to do X), rename, "
                  "mode (power mode), jobs (KURAMA's job list: add/edit/remove/start jobs for later; background jobs: is it done, progress, result, cancel, pause, resume), "
                  "clear_chat, mute_alerts, remote (remote desktop on/off), "
                  "make_tool (build a small new tool when nothing else fits).")
def kurama(action: Literal["about", "can_you", "rename", "mode", "jobs", "clear_chat", "mute_alerts", "remote", "make_tool"],
           text: str = "") -> str:
    """KURAMA itself.

    Args:
        action: What to do.
        text: The topic / the need / the new name / the mode / for jobs '<action> <details>': list | add <what to do; another job; ...> |
            edit <n> <new text> | remove <n> | start [n] | result <n> (what job n produced: always check, never redo it) | cancel <n> | pause <n> | resume <n> /
            minutes / stop / the task.
    """
    return run(TABLE, {"action": action, "text": text})
