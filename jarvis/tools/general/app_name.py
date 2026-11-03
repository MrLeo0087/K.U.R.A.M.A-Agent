"""app_name: the owner's own words, kept forever: a name for an app ("when I say browser, open Brave": works inside
any sentence) or words for a whole command ("when I say good night, lock the screen") (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core import mywords
from jarvis.core.registry import tool
from jarvis.tools.general import _apps


@tool(group="apps", safety="safe",
      description="Remember the user's words forever: NAME opens APP (browser = Brave), or NAME runs COMMAND (good night = lock the screen); forget, list.")
def app_name(name: str = "", app: str = "", command: str = "", action: Literal["save", "forget", "list"] = "save") -> str:
    """The user's words.

    Args:
        name: What the user will say, e.g. "browser", "good night".
        app: The installed app it opens, e.g. "brave".
        command: Or the whole command it stands for, as the user would ask it, e.g. "lock the screen".
        action: save (app or command given), forget (name only), list.
    """
    if action == "list":
        words, apps = mywords.all_words(), _apps.taught()
        if not words and not apps:
            return "No words of yours yet. Say e.g. 'when I say code, open VS Code'."
        lines = [f"'{k}' -> {v}" for k, v in words.items()] + [f"'{k}' -> opens the app {v}" for k, v in apps.items()]
        return "Your words (kept until you change them):\n" + "\n".join(lines)
    if command.strip() and action == "save":
        return mywords.save(name, command)
    if app.strip() and action == "save":
        return _apps.teach(name, app)
    if _apps.clean_query(name) in _apps.taught():
        return _apps.teach(name, "")
    return mywords.forget(name)
