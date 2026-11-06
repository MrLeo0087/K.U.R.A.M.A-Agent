"""send_message_telegram (P7c): send text (e.g. a poem KURAMA just wrote) to the user's Telegram."""
from __future__ import annotations

import re

from jarvis.core import config, notify
from jarvis.core.registry import tool
from jarvis.tools.general import _tg


# safe: only ever goes to the owner's own chat (TELEGRAM_CHAT_ID)
@tool(group="telegram", safety="safe", description="Send a text message to the user's Telegram.")
def send_message_telegram(text: str) -> str:
    """Send text to the user's Telegram chat.

    Args:
        text: The full text to send.
    """
    if not text.strip():
        return "error: nothing to send"
    if err := _tg.ready():
        return err
    group, thread = None, None
    if notify.reply_target() is None and len(text) < 600 and re.search(r"https?://", text):
        from jarvis.core import tgtopics  # a link sent from the laptop: the 🔗 Share section (when sections are on)
        group, thread = tgtopics.where("share", "info")
    if not notify.send_long(text, group, title="message", thread=thread):  # complete, never cut at 5 parts
        return "error: Telegram didn't accept the message (check the bot token/chat id or your internet)"
    return f"Sent to Telegram ({len(text)} characters)."
