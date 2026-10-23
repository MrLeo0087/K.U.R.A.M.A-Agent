"""Shared Telegram sharing check (not a tool)."""
from __future__ import annotations

from jarvis.core import notify


def ready() -> str | None:
    """None when Telegram is configured, else a friendly error."""
    if not notify.telegram_configured():
        return "error: Telegram isn't set up (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env)"
    return None
