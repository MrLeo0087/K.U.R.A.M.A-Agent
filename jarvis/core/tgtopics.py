"""Telegram sections: KURAMA's messages sorted into topics of your own Telegram group instead of one long chat.

    ⚠️ Alerts            RAM / battery / guard warnings, errors
    🤖 Claude Code       the Claude Code watch
    ⏰ Reminders & jobs  reminders, finished background jobs, the daily summary, training
    📌 Other             everything else KURAMA sends by itself

Your conversation with KURAMA (questions, commands, /screen...) stays in the private chat with the bot.
Setup, once: make a Telegram group, turn on Topics (group settings), add your KURAMA bot and make it an admin
that can manage topics, write anything in the group, then send "/topics setup" to the bot in your private chat.
"/topics off" puts everything back in the private chat. 0 tokens.
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger("jarvis.tgtopics")

SECTIONS = {"alerts": "⚠️ Alerts", "claude": "🤖 Claude Code", "jobs": "⏰ Reminders & jobs", "other": "📌 Other"}
_KEY, _CAND = "tg_topics", "tg_group_candidate"
_JOB_SOURCES = ("scheduler", "reminders", "jobs", "longjobs", "daily_digest", "brief", "training", "process_watch",
                "kaggle", "colab", "goals", "habits")


def _kv(key: str) -> dict:
    from jarvis.core import store
    try:
        d = json.loads(store.kv_get(key) or "{}")
        return d if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        return {}


def note_group(chat: dict) -> None:
    """The bot saw a group it is in (any message, or being added): remember it for /topics setup."""
    if (chat or {}).get("type") != "supergroup":
        return
    from jarvis.core import store
    store.kv_set(_CAND, json.dumps({"id": chat.get("id"), "title": chat.get("title") or "",
                                    "forum": bool(chat.get("is_forum"))}))


def setup() -> str:
    from jarvis.core import notify, store
    g = _kv(_CAND)
    if not g.get("id"):
        return ("I haven't seen your group yet. Make a Telegram group, turn on Topics in its settings, add me and make "
                "me an admin that can manage topics, write any message in the group, then send /topics setup again.")
    threads = {}
    try:
        for key, name in SECTIONS.items():
            r = notify.telegram_call("createForumTopic", {"chat_id": g["id"], "name": name})
            threads[key] = r["message_thread_id"]
    except RuntimeError as e:
        return (f"I couldn't make the topics in '{g.get('title')}': {e}. Check that Topics are on and that I'm an admin "
                "who can manage topics, then send /topics setup again.")
    store.kv_set(_KEY, json.dumps({"group": g["id"], "title": g.get("title"), "threads": threads}))
    for key, name in SECTIONS.items():
        try:
            notify.telegram_call("sendMessage", {"chat_id": g["id"], "message_thread_id": threads[key],
                                                 "text": f"{name}: KURAMA's {name.split(' ', 1)[1].lower()} come here."})
        except RuntimeError:
            pass
    return (f"Done: '{g.get('title')}' now has the sections {', '.join(SECTIONS.values())}. Alerts and updates go "
            "there; our chat stays here. /topics off puts everything back here.")


def off() -> str:
    from jarvis.core import store
    store.kv_delete(_KEY)
    return "Sections off: everything comes to this chat again."


def status() -> str:
    t = _kv(_KEY)
    if not t:
        return "Sections are off: everything comes to this chat. /topics setup sorts alerts into topics of a group."
    return f"Sections on in '{t.get('title')}': {', '.join(SECTIONS.values())}. /topics off to stop."


def section_for(source: str, level: str, title: str = "") -> str:
    if source == "claude_code" or "Claude Code" in title:
        return "claude"
    if source in _JOB_SOURCES:
        return "jobs"
    if level in ("warning", "error"):
        return "alerts"
    return "other"


def where(source: str, level: str, title: str = "") -> tuple[int | None, int | None]:
    """(group chat id, topic thread id) for this alert, or (None, None) = the private chat."""
    t = _kv(_KEY)
    if not t.get("group"):
        return None, None
    thread = (t.get("threads") or {}).get(section_for(source, level, title))
    return (t["group"], thread) if thread else (None, None)
