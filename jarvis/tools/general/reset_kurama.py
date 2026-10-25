"""reset_kurama: clear the conversation, or reminders+caches, or everything (keeps password + settings). Safe."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="self", safety="safe",
      description="Clear/reset KURAMA: 'chat' = forget this conversation; 'recent' = chat + reminders/alarms/timers "
                  "+ caches; 'all' = also wipe learned personal facts and start brand new. Password and settings are kept.")
def reset_kurama(level: Literal["chat", "recent", "all"] = "chat") -> str:
    """Clear or reset.

    Args:
        level: chat (this conversation), recent (chat + reminders + caches), all (full fresh start).
    """
    from jarvis.core import reset
    if level == "all":
        return reset.reset_all()
    if level == "recent":
        return reset.clear_recent()
    return reset.clear_chat()
