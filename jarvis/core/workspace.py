"""The workspace window: long tool results (file lists, search hits, reports) are saved as a small markdown file
under data/outputs/results/ and shown in the UI's Workspace card, while the chat (and the voice) only gives a
short overview. The LLM still gets the usual truncated result plus a note saying the full one is on screen.

Only for interactive turns from the dashboard (the agent puts a `published` list in the tool context); Telegram
turns keep the plain result, because the phone can't see the workspace.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from jarvis.core import config

log = logging.getLogger("jarvis.workspace")

NOTE = ("\n[The full result ({n} lines) is shown in the user's workspace window. Give a short overview in 1-2 "
        "sentences and say it's in the workspace; don't list or read out paths.]")


def worth_it(name: str, text: str) -> bool:
    if name in config.WORKSPACE_SKIP_TOOLS or text.startswith("error"):
        return False
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return len(lines) >= config.WORKSPACE_MIN_LINES or len(text) > config.TOOL_OUTPUT_MAX_CHARS


def publish(title: str, text: str) -> Path | None:
    """Save one result for the Workspace card; returns its path (None when saving failed)."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "result"
    path = Path(config.OUTPUTS_DIR) / "results" / f"{time.strftime('%Y%m%d-%H%M%S')}-{slug}.md"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {title}\n\n{text.strip()}\n", encoding="utf-8")
        return path
    except OSError as e:
        log.warning("could not save workspace result: %s", e)
        return None


def offer(name: str, text: str) -> str:
    """Called with a tool's full output: publish it when it's long and the turn has a workspace; returns the
    note to append to the LLM's copy ("" when nothing was published)."""
    from jarvis.core import safety

    ctx = safety.context()
    shelf = ctx.get("published")
    if shelf is None or ctx.get("channel") == "telegram" or not worth_it(name, text):
        return ""
    request = (ctx.get("user_text") or ctx.get("request") or name).strip()
    path = publish(f"{name.replace('_', ' ')}: {request[:60]}", text)
    if path is None:
        return ""
    shelf.append(str(path.relative_to(Path(config.OUTPUTS_DIR))))
    return NOTE.format(n=len(text.splitlines()))
