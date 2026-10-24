"""send_last_result: send the latest full result (the whole file list, search hits, report) to the user's
Telegram: as a message when it fits, else as a .md file. Safe: only ever goes to the owner's own chat."""
from __future__ import annotations

from jarvis.core import config, notify, workspace
from jarvis.core.registry import tool
from jarvis.tools.general import _tg


@tool(group="telegram", safety="safe",
      description="Send the latest full result (e.g. the whole file list) to the user's Telegram.")
def send_last_result() -> str:
    """Send the most recent saved result in full (text message, or a file when it's long)."""
    if err := _tg.ready():
        return err
    path = workspace.latest()
    if path is None:
        return "error: there is no saved result yet; run the search again"
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if len(text) <= config.TELEGRAM_MAX_REPLY_CHARS:
        ok = notify.telegram_send(text)
        return "Sent the full list as a message." if ok else "error: Telegram didn't accept the message"
    from jarvis.tools.general.send_file_telegram import deliver
    out = deliver(path, caption=f"Full result ({len(text.splitlines())} lines)")
    return out.replace(f"Sent {path.name}", "Sent the full list as a file")
