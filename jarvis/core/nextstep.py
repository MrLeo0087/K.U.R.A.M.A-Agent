"""The next step, offered after an answer: one short line ("Want it on your phone? Say yes."), and a "yes" runs it.
Every offer is an instant command (0 tokens), so accepting never costs an AI call.

    after(tool, ok, answer)  -> the line to add (and the offer is remembered for OFFER_TTL_S), or ""
    take(text)               -> the command to run when the reply is a bare "yes" to a fresh offer, else None
    offer(command, line)     -> remember an offer made elsewhere (an alert: "Say yes to clean your RAM")
    stuck(text)              -> for a request nothing understood: the closest command to say, or ""
"""
from __future__ import annotations

import json
import time

from jarvis.core import config

OFFER_TTL_S = 180
_KEY = "next_offer"

# tool that just worked -> (the line, the 0-token command a "yes" runs)
NEXT: dict[str, tuple[str, str]] = {
    "generate_image": ("Want it on your phone? Say yes and I'll send it to your Telegram.", "send it to telegram"),
    "screenshot": ("Say yes to send it to your Telegram.", "send it to telegram"),
    "write_document": ("Say yes to send it to your Telegram.", "send it to telegram"),
    "make_chart": ("Say yes to send the chart to your Telegram.", "send it to telegram"),
    "make_diagram": ("Say yes to send the diagram to your Telegram.", "send it to telegram"),
    "video_download": ("Say yes to send it to your Telegram.", "send it to telegram"),
}
KEEP_OFFER_FOR = {"_say", "explain_self", "find_capability", "help_me"}  # talking about it keeps the offer open


def offer(command: str, line: str = "") -> str:
    """Remember that a "yes" now means `command` (for OFFER_TTL_S)."""
    try:
        from jarvis.core import store
        store.kv_set(_KEY, json.dumps({"command": command, "t": time.time()}))
    except Exception:  # noqa: BLE001
        return ""
    return line


def after(tool: str, ok: bool, answer: str) -> str:
    """The next-step line for a tool that just worked (and the offer behind it), or ""."""
    line, command = NEXT.get(tool, ("", ""))
    if not ok or not command or not config.SUGGEST_NEXT or str(answer).lower().startswith(("error", "sorry")):
        return ""
    if "telegram" in command and "telegram" in str(answer).lower():
        return ""  # it already went to Telegram
    return offer(command, line)


def take(text: str) -> str | None:
    """The offered command when the reply is a bare yes to a fresh offer (the offer is used up)."""
    from jarvis.core import safety, store
    words = (text or "").lower().strip(" .!?").split()
    if not words or len(words) > 4 or safety.parse_yes_no(text) is not True:
        return None
    try:
        d = json.loads(store.kv_get(_KEY) or "{}")
    except (ValueError, TypeError):
        return None
    if not d or time.time() - float(d.get("t", 0)) > OFFER_TTL_S:
        return None
    store.kv_delete(_KEY)
    return str(d.get("command") or "") or None


def drop() -> None:
    try:
        from jarvis.core import store
        store.kv_delete(_KEY)
    except Exception:  # noqa: BLE001
        pass


def stuck(text: str) -> str:
    """When the AI couldn't do a request: the closest instant command to say instead (0 tokens), or ""."""
    try:
        from jarvis.core import selfindex
        card, sure = selfindex.best_for(text)
    except Exception:  # noqa: BLE001
        return ""
    if card is None or sure < config.HELP_TOOL_MIN or not card.say:
        return ""
    return f'Maybe this helps: say "{card.say[0]}" ({card.short()}).'
