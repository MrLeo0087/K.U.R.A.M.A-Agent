"""Long tool results (file lists, search hits, reports) are saved in full as a small markdown file under
data/outputs/results/. On the dashboard they open in the Workspace card; on Telegram they can be sent on request.

How much the chat shows follows the user's words, not a fixed rule:
  - default: the LLM gets a truncated copy plus a note: give a short overview (dashboard: "it's in your workspace";
    Telegram: offer the whole list)
  - "the whole / full / complete list", "all of them", "everything": the LLM gets up to TOOL_OUTPUT_FULL_CHARS and
    is told to give it all (Telegram: as text, or send_last_result for something longer)
Saving needs a turn context with a `published` list (the agent adds one; Telegram turns too).
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from jarvis.core import config

log = logging.getLogger("jarvis.workspace")

_ALL = re.compile(r"\b(?:whole|full|complete|entire|every(?:thing| one| file)|all (?:of )?(?:them|it|the \w+|files|results)|"
                  r"each (?:one|file)|show (?:me )?all|list (?:them )?all|sab|sabai|सबै|सब)\b", re.I)

NOTES = {
    ("dash", False): "\n[The full result ({n} lines) is shown in the user's workspace window. Give a short overview in "
                     "1-2 sentences and say it's in the workspace; don't list or read out paths.]",
    ("dash", True): "\n[The user asked for all of it: the full result ({n} lines) is also in their workspace window. "
                    "Show what they asked for; paths are fine in text but never read them aloud.]",
    ("phone", False): "\n[Full result: {n} lines (saved). Give a short overview with the few most useful items and offer "
                      "to send the whole list.]",
    ("phone", True): "\n[The user asked for all of it ({n} lines). Give the whole list as plain lines; if it doesn't fit, "
                     "call send_last_result to send it as a file.]",
}


def wants_all(text: str) -> bool:
    """The user asked for everything (whole list, all of them...), so don't summarize it away."""
    return bool(_ALL.search(text or ""))


def full_requested() -> bool:
    from jarvis.core import safety
    return bool(safety.context().get("full"))


def worth_it(name: str, text: str) -> bool:
    if name in config.WORKSPACE_SKIP_TOOLS or text.startswith("error"):
        return False
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return len(lines) >= config.WORKSPACE_MIN_LINES or len(text) > config.TOOL_OUTPUT_MAX_CHARS


def publish(title: str, text: str) -> Path | None:
    """Save one result; returns its path (None when saving failed)."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "result"
    path = results_dir() / f"{time.strftime('%Y%m%d-%H%M%S')}-{slug}.md"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {title}\n\n{text.strip()}\n", encoding="utf-8")
        return path
    except OSError as e:
        log.warning("could not save workspace result: %s", e)
        return None


def results_dir() -> Path:
    return Path(config.OUTPUTS_DIR) / "results"


def latest() -> Path | None:
    files = sorted(results_dir().glob("*.md"), key=lambda p: p.stat().st_mtime) if results_dir().is_dir() else []
    return files[-1] if files else None


def offer(name: str, text: str) -> str:
    """Called with a tool's full output: save it when it's long and a turn is running; returns the note for the
    LLM's copy ("" when nothing was saved)."""
    from jarvis.core import safety

    ctx = safety.context()
    shelf = ctx.get("published")
    if shelf is None or not worth_it(name, text):
        return ""
    request = (ctx.get("user_text") or ctx.get("request") or name).strip()
    path = publish(f"{name.replace('_', ' ')}: {request[:60]}", text)
    if path is None:
        return ""
    phone = ctx.get("channel") == "telegram"
    if not phone:
        shelf.append(str(path.relative_to(Path(config.OUTPUTS_DIR))))  # the dashboard opens it in the Workspace
    return NOTES[("phone" if phone else "dash", bool(ctx.get("full")))].format(n=len(text.splitlines()))
