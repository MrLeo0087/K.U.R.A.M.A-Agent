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
    if notify.reply_target() is not None:  # asked on Telegram: the answer goes back where it was asked
        if not notify.send_long(text, None, title="message"):
            return "error: Telegram didn't accept the message (check the bot token/chat id or your internet)"
        return f"Sent to Telegram ({len(text)} characters)."
    # sent from the laptop: your private chat (it rings) AND your group, when sections are on: a link in 🔗 Share,
    # anything else in General (11-09: 'send hello to telegram' reached only the private chat)
    if not notify.send_long(text, config.TELEGRAM_CHAT_ID, title="message"):  # complete, never cut at 5 parts
        return "error: Telegram didn't accept the message (check the bot token/chat id or your internet)"
    from jarvis.core import tgtopics
    if group := tgtopics._kv(tgtopics._KEY).get("group"):  # sections on
        thread = tgtopics.where("share", "info")[1] if len(text) < 600 and re.search(r"https?://", text) else None
        notify.send_long(text, group, title="message", thread=thread, silent=True)  # (no second ring)
    return f"Sent to Telegram ({len(text)} characters)."
