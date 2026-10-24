"""send_last_result: send the latest thing KURAMA made to the user's Telegram: the picture it just generated, the
poem/essay it wrote, or the full list from the last search. If that thing is still being made, it is sent as soon as
it's ready. Safe: only ever goes to the owner's own chat."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from jarvis.core import config, notify, store, workspace
from jarvis.core.registry import tool
from jarvis.tools.general import _tg

IMG = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
KIND_OF_JOB = {"image": ("image",), "document": ("write", "code", "scan"), "list": (), "any": None}


def _newest(kind: str) -> Path | None:
    root = Path(config.OUTPUTS_DIR)
    if not root.is_dir():
        return None
    files = [p for p in root.rglob("*") if p.is_file() and not p.name.startswith(".")]
    if kind == "image":
        files = [p for p in files if p.suffix.lower() in IMG]
    elif kind == "list":
        files = [p for p in files if p.parent.name == "results"]
    elif kind == "document":
        files = [p for p in files if p.suffix.lower() not in IMG and p.parent.name != "results"]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _running(kind: str) -> dict | None:
    kinds = KIND_OF_JOB.get(kind)
    if kinds == ():
        return None
    for r in store.jobs_list(10, ("queued", "running")):
        if kinds is None or r.get("kind") in kinds:
            return r
    return None


@tool(group="telegram", safety="safe",
      description="Send the latest thing you made (picture, document or full list) to the user's Telegram.")
def send_last_result(kind: Literal["any", "image", "document", "list"] = "any") -> str:
    """Send the newest output to Telegram; if it's still being made, it's sent when ready.

    Args:
        kind: image (a generated picture), document (poem/essay/code), list (the full result of the last search),
            any (whatever was made last).
    """
    if err := _tg.ready():
        return err
    from jarvis.core import jobs

    if job := _running(kind):  # e.g. "send me that picture" while it's still being drawn
        return jobs.then_send(job["id"])
    path = _newest(kind) if kind != "list" else (workspace.latest() or _newest("list"))
    if path is None:
        return f"error: I haven't made any {'' if kind == 'any' else kind + ' '}output yet"
    if path.suffix.lower() in (".md", ".txt"):
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if len(text) <= config.TELEGRAM_MAX_REPLY_CHARS:
            return f"Sent {path.name} as a message." if notify.telegram_send(text) else \
                "error: Telegram didn't accept the message"
    from jarvis.tools.general.send_file_telegram import deliver
    return deliver(path)
