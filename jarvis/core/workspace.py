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


_NOTE_RE = re.compile(r"\n\[(?:The full result|Full result|The user asked for all)[^\]]*\]\s*$")


def strip_note(text: str) -> str:
    """Remove the note offer() adds for the LLM (the fast path shows tool output to the user directly)."""
    return _NOTE_RE.sub("", text or "")


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
    return len(lines) >= config.WORKSPACE_MIN_LINES or len(text) > config.WORKSPACE_MIN_CHARS


def publish(title: str, text: str, folder: str = "results") -> Path | None:
    """Save one result; returns its path (None when saving failed). answers/ = long chat answers (always shown
    in the workspace); results/ = raw tool output (small ones are not listed)."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "result"
    path = Path(config.OUTPUTS_DIR) / folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{slug}.md"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {title}\n\n{text.strip()}\n", encoding="utf-8")
        return path
    except OSError as e:
        log.warning("could not save workspace result: %s", e)
        return None


# --- long answers: the chat (and the voice) get one short line, the full answer goes to the workspace -------------
_CODEY = re.compile(r"[{};=]\s*$|^\s{4,}\S|^\s*(?:def|class|import|return|for|if)\b")
_ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*•]|[A-Za-z][\w ]{0,30}:)\s+\S")


def too_long(text: str) -> bool:
    """Lists, several paragraphs, code or anything over ~3 lines of text belongs in the workspace, not the chat."""
    text = (text or "").strip()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    codey = sum(1 for ln in lines if _CODEY.search(ln))
    return len(text) > config.CHAT_MAX_CHARS or len(lines) > config.CHAT_MAX_LINES or "```" in text or codey >= 3


def short_line(text: str, lang: str = "en") -> str:
    """What the chat shows instead: a list -> its heading + how many items; prose -> its first sentence or two."""
    tail = {"ne": "पूरा उत्तर workspace मा छ।", "hi": "पूरा जवाब workspace में है।"}.get(lang, "The full answer is in the workspace.")
    lines = [ln.strip() for ln in re.sub(r"```.*?```", "\n", text.strip(), flags=re.S).splitlines() if ln.strip()]
    items = [ln for ln in lines[1:] if _ITEM.match(ln)]
    if lines and lines[0].endswith(":") and len(lines[0]) <= 120 and len(items) >= 2 \
            and len(items) >= (len(lines) - 1) // 2:  # "Latest news:" + items -> heading + how many
        # "The 2026 Ballon d'Or top-10 rankings are (source: X, 27 Oct):" -> "I found the 2026 Ballon d'Or top-10
        # rankings (10 items). It's in the workspace." (owner: one tidy line, no findings in the chat)
        head = re.sub(r"\s*\([^)]*\)", "", lines[0].rstrip(":").strip())
        head = re.sub(r"\s+(?:are|is|were|was)(?:\s+as\s+follows)?$", "", head, flags=re.I).strip(" ,-–")
        head = re.sub(r"^(?:here\s+(?:are|is)\s+)", "", head, flags=re.I)
        if head[:1].isupper() and not head[:2].isupper() and head.split()[0].lower() in ("the", "latest", "top", "your", "my", "all", "recent", "today's", "current"):
            head = head[0].lower() + head[1:]
        return {"ne": f"भेटियो: {head} ({len(items)} वटा) workspace मा छ।", "hi": f"मिल गया: {head} ({len(items)} आइटम) workspace में है।"}.get(
            lang, f"I found {head} ({len(items)} items). It's in the workspace.")
    if "```" in text:  # code: never read code lines out; say what was made (owner: 'test_calculator.py. python. from ...')
        fname = re.search(r"\*\*`?([\w.-]+\.\w{1,6})`?\*\*|#\s*(?:file:\s*)?([\w.-]+\.\w{1,6})\b", text)
        fname = (fname.group(1) or fname.group(2)) if fname else ""
        tests = bool(re.search(r"\bdef\s+test_\w+|\bimport\s+pytest\b|\bunittest\b", text))
        what = "the tests" if tests else "the code"
        run = re.search(r"^\s*(pytest[^\n`]*|python3?\s+[\w./-]+\.py[^\n`]*)$", text, re.M)
        line = f"I wrote {what}" + (f" ({fname})" if fname else "") + ". It's in the workspace, you can check it there."
        if run:
            line += f" Run {'them' if tests else 'it'} with: {run.group(1).strip()}"
        return {"ne": "कोड workspace मा राखेँ, त्यहाँ हेर्नुहोस्।", "hi": "कोड workspace में रख दिया, वहाँ देखिए।"}.get(lang, line)
    plain = " ".join(re.sub(r"(?<=[^\s.!?:;।])$", ".", ln.strip(" -*•#"))  # each line ends like a sentence
                     for ln in lines if not _CODEY.search(ln) and not re.search(r"/[\w.-]+/", ln))
    if not plain and lines:  # only code / paths: the first line, cut short
        plain = lines[0][:160]
    head = ""
    for sn in re.split(r"(?<=[.!?।])\s+", plain):
        if head and len(head) + len(sn) > 200:
            break
        head += (" " if head else "") + sn
    if len(head) > 240:
        head = head[:220].rsplit(" ", 1)[0] + "…"
    return (head.strip() + " " if head.strip() else "") + tail


def to_workspace(title: str, text: str, lang: str = "en") -> tuple[str, Path | None]:
    """(chat line, saved file) for a long answer; the text itself and None when it is short or saving failed."""
    if not too_long(text):
        return text, None
    path = publish(title or "Answer", text, folder="answers")
    return (short_line(text, lang), path) if path else (text, None)


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
    path = publish(f"{name.replace('_', ' ')}: {request[:60]}", text, folder="answers")  # always listed
    if path is None:
        return ""
    phone = ctx.get("channel") == "telegram"
    full = bool(ctx.get("full")) or name in config.WORKSPACE_SHOW_ALL
    if not phone:
        shelf.append(str(path.relative_to(Path(config.OUTPUTS_DIR))))  # the dashboard opens it in the Workspace
    return NOTES[("phone" if phone else "dash", full)].format(n=len(text.splitlines()))
