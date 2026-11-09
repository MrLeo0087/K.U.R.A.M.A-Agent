"""claude_code: watch Claude Code for the owner while they are away (core/claudewatch.py): on / off, status (with a
screenshot on the phone), report, answer its permission question (yes / no), and send it the next instruction
(say). 0 tokens. Off by default; while off nothing is sent or kept (safe; yes and say ask the Telegram PIN)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="dev", safety="safe", max_chars=3500,
      description="Watch Claude Code while the user is away: on/off, status (progress, time, what it does now), "
                  "report, yes/no to its permission question, say (send it the next instruction), stop (interrupt "
                  "it), usage (how much Claude Code was used today), sessions (list the conversations), open (go "
                  "to conversation number `text`).")
def claude_code(action: Literal["on", "off", "new", "go", "status", "report", "yes", "no", "say", "stop", "usage",
                                "sessions", "open"] = "status",
                text: str = "") -> str:
    """Claude Code watch.

    Args:
        action: on, off, new (a new Claude Code chat; `text` = its first message), go (a new chat in project
            `text`, ready for say), status,
            report, yes (allow its question), no (deny it), say (the next instruction),
            stop (interrupt the task), usage (how much it was used today), sessions (your conversations,
            numbered), open (switch to conversation `text`: its number or words of its title).
        text: For say: what Claude Code should do next.
    """
    from jarvis.core import claudewatch, safety
    if action == "on":
        return claudewatch.turn_on()
    if action == "off":
        return claudewatch.turn_off()
    if action in ("yes", "no"):
        return claudewatch.answer(action == "yes")
    if action == "say":
        return claudewatch.say(text)
    if action == "new":
        return claudewatch.new(text)
    if action == "go":
        return claudewatch.go(text)
    if action == "stop":
        return claudewatch.stop()
    if action == "usage":
        return claudewatch.usage()
    if action == "sessions" or (action == "status" and text.strip().lower() in ("session", "sessions", "list")):
        return claudewatch.sessions_text()  # ('/claude session': the list too)
    if action == "open":  # a number / title: that conversation; nothing: Claude Code in the VS Code window in use
        return claudewatch.open_session(text) if text.strip() else claudewatch.go("")
    if action == "report":
        return claudewatch.report()
    card = claudewatch.status()
    if safety.context().get("channel") == "telegram" and claudewatch.is_on():  # the screen too, on the phone
        shot = claudewatch.screenshot()
        if shot is not None:
            from jarvis.tools.general.send_file_telegram import deliver
            deliver(shot, "🖥 the laptop screen now")
    return card
