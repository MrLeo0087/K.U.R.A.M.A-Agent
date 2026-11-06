"""Telegram sections: KURAMA's messages sorted into topics of your own Telegram group instead of one long chat.

    ⚠️ Alerts       RAM / battery / guard warnings, errors
    🤖 Claude Code  the Claude Code watch
    ⏰ Reminders    reminders, alarms, timers, the morning brief, habits and to-dos
    ⚙️ Jobs         finished background jobs, training, downloads, installs, backups
    🖼️ Images       pictures KURAMA sends by itself (made images, screenshots)
    🔗 Share        files and links sent from the laptop (PDF, MD, zips, download links, Wi-Fi shares)
    📌 Other        everything else KURAMA sends by itself

Two-way: you can also TALK to KURAMA in any topic (General included); the answer comes back in that same topic
(only your own messages are answered: anyone else in the group is ignored). The private chat works as before.
Filed automatically: whatever you ask (in the private chat, General or any topic), the answer stays where you asked
AND a copy is filed in its section: a picture in Images (notify), a reminder / Claude Code / job request with its
answer in Reminders / Claude Code / Jobs (file_copy, by the tools that ran). Copies are made by Telegram
(copyMessages): no upload again, 0 tokens.
Setup, once: make a Telegram group, turn on Topics (group settings), add your KURAMA bot and make it an admin
that can manage topics, write anything in the group, then send "/topics setup" to the bot. Running it again only
adds the sections that are missing. "/topics off" puts everything back in the private chat. 0 tokens.
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger("jarvis.tgtopics")

SECTIONS = {"alerts": "⚠️ Alerts", "claude": "🤖 Claude Code", "reminders": "⏰ Reminders", "jobs": "⚙️ Jobs",
            "images": "🖼️ Images", "share": "🔗 Share", "other": "📌 Other"}
_KEY, _CAND = "tg_topics", "tg_group_candidate"
_REMINDER_SOURCES = ("scheduler", "reminders", "timer", "todo", "habits", "goals", "brief", "daily_digest", "study")
_JOB_SOURCES = ("jobs", "longjobs", "training", "process_watch", "kaggle", "colab", "downloads", "installer", "backup")


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
    old = _kv(_KEY)
    threads = dict(old.get("threads") or {}) if old.get("group") == g["id"] else {}
    if threads.get("jobs") and "reminders" not in threads:  # the old shared "Reminders & jobs" topic: reminders
        threads["reminders"] = threads.pop("jobs")
    made = []
    try:
        for key, name in SECTIONS.items():
            if key in threads:  # already there: never a second copy
                continue
            r = notify.telegram_call("createForumTopic", {"chat_id": g["id"], "name": name})
            threads[key] = r["message_thread_id"]
            made.append(key)
    except RuntimeError as e:
        return (f"I couldn't make the topics in '{g.get('title')}': {e}. Check that Topics are on and that I'm an admin "
                "who can manage topics, then send /topics setup again.")
    store.kv_set(_KEY, json.dumps({"group": g["id"], "title": g.get("title"), "threads": threads}))
    if threads.get("reminders") and "reminders" not in made:  # renamed from "Reminders & jobs"
        try:
            notify.telegram_call("editForumTopic", {"chat_id": g["id"], "message_thread_id": threads["reminders"],
                                                    "name": SECTIONS["reminders"]})
        except RuntimeError:
            pass
    for key, name in SECTIONS.items():
        if key not in made:
            continue
        try:
            notify.telegram_call("sendMessage", {"chat_id": g["id"], "message_thread_id": threads[key],
                                                 "text": f"{name}: KURAMA's {name.split(' ', 1)[1].lower()} come here. "
                                                         "You can talk to me here too."})
        except RuntimeError:
            pass
    return (f"Done: '{g.get('title')}' now has the sections {', '.join(SECTIONS.values())}. Alerts and updates go "
            "there, and you can talk to me in any of them (I answer in the same topic). /topics off puts everything "
            "back here.")


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
    if source in ("images", "share"):
        return source
    if source in _REMINDER_SOURCES:
        return "reminders"
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


def group_id() -> int | None:
    """The sections group (or the one seen for setup), whose topics the owner may talk in."""
    return _kv(_KEY).get("group") or _kv(_CAND).get("id")


# the tools whose request + answer is also filed in a section (pictures are filed by notify, by what is sent)
TOOL_SECTIONS = {
    "claude": ("claude_code",),
    "reminders": ("add_reminder", "set_alarm", "set_timer", "schedules", "schedule_command", "schedule", "todo",
                  "goals", "habits", "timetable"),
    "share": ("send_file_telegram", "wifi_share", "send_message_telegram", "saved_links", "read_later"),
    "jobs": ("write_document", "jobs", "run_training", "kaggle_train", "training", "backup", "download_file",
             "video_download"),
}


def section_for_tools(tools: list[str]) -> str | None:
    """The section a request belongs to, by the first tool it ran that has one ('set a reminder' -> reminders)."""
    for t in tools:
        for key, names in TOOL_SECTIONS.items():
            if t in names:
                return key
    return None


def file_copy(from_chat, ids: list[int], section: str, asked_thread: int | None = None) -> bool:
    """Copy messages (the question and its answer) into a section, unless they were already in it."""
    from jarvis.core import notify
    t = _kv(_KEY)
    thread = (t.get("threads") or {}).get(section)
    if not t.get("group") or not thread or not ids:
        return False
    if str(from_chat) == str(t["group"]) and asked_thread == thread:
        return False  # asked in that very section
    try:
        notify.telegram_call("copyMessages", {"chat_id": t["group"], "message_thread_id": thread,
                                              "from_chat_id": from_chat, "message_ids": sorted(set(ids))})
        return True
    except RuntimeError as e:
        log.info("filing in %s failed: %s", section, e)
        return False


def forget_thread(thread: int) -> None:
    """You deleted a section topic in Telegram: forget it (alerts go to the private chat; /topics setup remakes it)."""
    from jarvis.core import store
    t = _kv(_KEY)
    threads = {k: v for k, v in (t.get("threads") or {}).items() if v != thread}
    if t and threads != t.get("threads"):
        store.kv_set(_KEY, json.dumps({**t, "threads": threads}))
        log.info("topic %s is gone: forgotten", thread)
