"""messages: new / latest WhatsApp Web, Facebook (Messenger), Instagram and email messages on this laptop (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="usage", safety="safe",
      description="Check messages on this laptop: unread/new or latest WhatsApp Web, Facebook/Messenger, Instagram "
                  "and email (sender + text), filter by app or sender; or mark all as read.")
def messages(action: Literal["unread", "latest", "mark_read"] = "unread",
             source: Literal["all", "whatsapp", "facebook", "instagram", "email"] = "all", sender: str = "",
             hours: float = 24, limit: int = 10) -> str:
    """Messages.

    Args:
        action: unread (new since last check, then marked read), latest (recent, read or not), mark_read.
        source: all, whatsapp, facebook, instagram or email.
        sender: Only messages from this person/sender (part of the name is enough).
        hours: How far back to look.
        limit: Max messages to list.
    """
    from jarvis.core import inbox
    if action == "mark_read":
        n = inbox.mark_read(source=source)
        return f"Marked {n} message(s) as read."
    return inbox.report(source, unread=action == "unread", sender=sender.strip(), hours=float(hours or 24),
                        limit=max(1, min(int(limit or 10), 30)))
