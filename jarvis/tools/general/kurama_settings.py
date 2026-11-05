"""kurama_settings: change KURAMA's own settings from a fixed safe list (core/usersettings.py): the speed test's
length, reply length, voice timing, Telegram photo size, alert levels... list / get / set / reset / undo. Values
are checked against each setting's range and saved in data/user_settings.json (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core import usersettings
from jarvis.core.registry import tool


@tool(group="self", safety="safe", max_chars=2500,
      description="Change your own settings from a safe list (speed test seconds, reply length, end of speech wait, "
                  "telegram photo size, ram alert percent, speaking speed...): list, get, set, reset, undo.")
def kurama_settings(action: Literal["list", "get", "set", "reset", "undo"] = "list", name: str = "",
                    value: str = "") -> str:
    """Your settings.

    Args:
        action: list (all, with values), get (one), set (name + value), reset (name, or "all"), undo (last change).
        name: The setting, e.g. "speed test seconds".
        value: For set: the new value as said, e.g. "30 seconds", "2 minutes", "9 PM", "+20%".
    """
    if action == "set":
        return usersettings.set_value(name, value)
    if action == "get":
        return usersettings.get(name)
    if action == "reset":
        return usersettings.reset(name)
    if action == "undo":
        return usersettings.undo()
    return usersettings.listing()
