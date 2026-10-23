"""send_message_telegram (P7c): send text (e.g. a poem Jarvis just wrote) to the user's Telegram."""
from __future__ import annotations

from jarvis.core import config, notify
from jarvis.core.registry import tool
from jarvis.tools.general import _tg


@tool(group="telegram", safety="confirm", description="Send a text message to the user's Telegram.")
def send_message_telegram(text: str) -> str:
    """Send text to the user's Telegram chat.

    Args:
        text: The full text to send.
    """
    if not text.strip():
        return "error: nothing to send"
    if err := _tg.ready():
        return err
    chunks = [text[i:i + config.TELEGRAM_MAX_REPLY_CHARS] for i in range(0, len(text), config.TELEGRAM_MAX_REPLY_CHARS)]
    for chunk in chunks[:5]:
        if not notify.telegram_call("sendMessage", {"chat_id": config.TELEGRAM_CHAT_ID, "text": chunk,
                                                    "disable_web_page_preview": True}):
            return "error: Telegram didn't accept the message (check the bot token/chat id or your internet)"
    return f"Sent to Telegram ({len(text)} characters)."
