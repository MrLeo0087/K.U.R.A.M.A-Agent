"""Long-document writer job: outline (1 structured call) -> sections (max ~1500 tokens each),
appended progressively to data/outputs/<YYYYmmdd-HHMM>-<slug>.md. Smart model only
(config.WRITER_TIER), every call paced by the rate limiter at background priority. Respects cancel.
"""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from jarvis.core import config, llm, planner, store

log = logging.getLogger("jarvis.writer")

LANG_NAMES = {"en": "English", "hi": "Hindi (Devanagari script)", "ne": "Nepali (Devanagari script)"}
OUTLINE_PROMPT = ("Plan a {what} for the user's request. Return a short title and exactly {n} "
                  "section headings, all in {lang}.")
SECTION_PROMPT = ("You are a skilled writer. Write in {lang}. Output only the body of the requested "
                  "section as Markdown paragraphs: no heading, no preamble, no closing remarks.")
MULTI_FILE = re.compile(r"\b(?:project|app|application|website|game|files|several\s+modules|full[- ]stack)\b", re.I)
FILE_PROMPT = ("You are an expert programmer. Write the COMPLETE, working code file that is asked for: imports, type "
               "hints, docstrings, error handling and logging when asked, and a short `if __name__ == \"__main__\":` "
               "example when it helps. Reply with ONE Markdown fenced code block and nothing else: no explanation, "
               "no headings, no text before or after.")


def code_only(text: str) -> str:
    """The code inside Markdown fences (joined), or the text itself when it has none."""
    blocks = re.findall(r"```[\w+.-]*\n(.*?)```", text or "", re.S)
    return ("\n\n".join(b.rstrip() for b in blocks) if blocks else (text or "")).strip() + "\n"


def _write_one_file(ctx, request: str) -> str:
    """'Write a Python module that...': ONE call writes the whole file, saved as code only (no essay sections)."""
    ctx.progress("writing the code")
    m = re.search(r"\b([\w-]+\.(py|js|ts|sh|go|rs|java|cpp|c|rb|php|html|css|sql))\b", request)
    ext = m.group(2) if m else "py"
    path = output_path(ctx.job.title).with_suffix("." + ext)
    reply = llm.chat([{"role": "system", "content": FILE_PROMPT}, {"role": "user", "content": request}],
                     tier=config.WRITER_TIER, purpose=ctx.purpose("code"), max_tokens=config.CODE_FILE_MAX_TOKENS,
                     priority="background")
    path.write_text(code_only(str(reply)), encoding="utf-8")
    ctx.set_output(path)
    ctx.progress(f"done ({len(path.read_text(encoding='utf-8').splitlines())} lines)")
    return str(path)


CODE_PROMPT = ("You are an expert programmer. Write the requested part of the code: complete, working, "
               "with short comments, in Markdown fenced code blocks plus a one-line explanation. "
               "No heading, no preamble.")


class Outline(BaseModel):
    """Title and section headings of a document."""
    title: str = Field(description="short title")
    sections: list[str] = Field(description="section headings, in order")


def slugify(text: str, n: int = 40) -> str:
    s = re.sub(r"[^\w]+", "-", text.lower(), flags=re.UNICODE).strip("-_")
    return (s[:n].rstrip("-") or "document")


def output_path(title: str) -> Path:
    config.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    base = f"{datetime.now():%Y%m%d-%H%M}-{slugify(title)}"
    path, i = config.OUTPUTS_DIR / f"{base}.md", 2
    while path.exists():
        path, i = config.OUTPUTS_DIR / f"{base}-{i}.md", i + 1
    return path


def _tokens_per_word(lang: str) -> float:
    return 3.0 if lang in ("hi", "ne") else 1.5


def plan_sections(words: int, lang: str) -> tuple[int, int]:
    """(number of sections, max_tokens per section) for a target length."""
    room = config.WRITER_SECTION_MAX_TOKENS - 300  # leave room for hidden reasoning
    by_tokens = math.ceil(words * _tokens_per_word(lang) / room)
    n = max(1 if words < 250 else 2, math.ceil(words / config.WRITER_WORDS_PER_SECTION), by_tokens)
    per = words / n
    max_tok = min(config.WRITER_SECTION_MAX_TOKENS, int(per * _tokens_per_word(lang)) + 300)
    return n, max_tok


def _outline(ctx, request: str, n: int, lang: str, kind: str) -> Outline:
    what = "program (sections = parts/files of the code)" if kind == "code" else "document"
    msgs = [{"role": "system", "content": OUTLINE_PROMPT.format(what=what, n=n, lang=LANG_NAMES.get(lang, "English"))},
            {"role": "user", "content": request}]
    try:
        o = llm.structured(msgs, Outline, tier=config.WRITER_TIER, purpose=ctx.purpose("outline"),
                           max_tokens=600, priority="background")
        heads = [h.strip() for h in o.sections if h and h.strip()][:n]
        if heads:
            return Outline(title=o.title.strip() or planner.title_of(request), sections=heads)
    except llm.LLMError as e:
        log.warning("outline failed, using generic sections: %s", e)
    ctx.check()
    return Outline(title=planner.title_of(request).capitalize(),
                   sections=[f"Part {i + 1}" for i in range(n)])


def run(ctx, request: str, lang: str = "en", kind: str = "write") -> str:
    """Job body (ctx: jobs.JobContext). Returns the output file path."""
    lang = lang if lang in LANG_NAMES else planner.detect_lang(request)
    if kind == "code" and not MULTI_FILE.search(request):
        return _write_one_file(ctx, request)
    words = min(planner.target_words(request) or config.WRITER_DEFAULT_WORDS, config.WRITER_MAX_WORDS)
    n, max_tok = plan_sections(words, lang)
    ctx.progress(f"outlining ({n} sections, ~{words} words)")
    outline = _outline(ctx, request, n, lang, kind)
    n = len(outline.sections)
    per = max(30, round(words / n))
    path = output_path(ctx.job.title)
    path.write_text(f"# {outline.title}\n\n", encoding="utf-8")
    ctx.set_output(path)
    state = {"request": request, "lang": lang, "kind": kind, "title": outline.title,
             "sections": list(outline.sections), "done": 0, "path": str(path), "per": per, "max_tok": max_tok}
    return _write_sections(ctx, state)


# --- P9b resume: kv "job_resume:<job id>" holds the outline and how many sections are written ---
RESUME_PREFIX = "job_resume:"


def _save_state(ctx, state: dict) -> None:
    try:
        store.kv_set(f"{RESUME_PREFIX}{ctx.job.id}", json.dumps(state, ensure_ascii=False))
    except Exception as e:
        log.debug("resume state not saved: %s", e)


def resume(ctx, state: dict) -> str:
    """Job body that continues a previous job's document from its next section."""
    path = Path(state["path"])
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {state['title']}\n\n", encoding="utf-8")
    ctx.set_output(path)
    return _write_sections(ctx, state)


def _write_sections(ctx, state: dict) -> str:
    request, lang, kind = state["request"], state["lang"], state["kind"]
    title, sections, per, max_tok = state["title"], state["sections"], state["per"], state["max_tok"]
    path, n = Path(state["path"]), len(state["sections"])
    system = CODE_PROMPT if kind == "code" else SECTION_PROMPT.format(lang=LANG_NAMES.get(lang, "English"))
    text = path.read_text(encoding="utf-8") if state.get("done") else ""
    tail = text[-300:] if text else ""
    _save_state(ctx, state)
    for i in range(int(state.get("done") or 0) + 1, n + 1):
        head = sections[i - 1]
        ctx.check()
        ctx.progress(f"section {i}/{n}")
        msgs = [{"role": "system", "content": system},
                {"role": "user", "content":
                    f"Request: {request}\nTitle: {title}\nOutline: {'; '.join(sections)}\n"
                    + (f"The previous section ended: ...{tail}\n" if tail else "")
                    + f"Write section {i} of {n}, \"{head}\", in about {per} words."}]
        reply = llm.chat(msgs, tier=config.WRITER_TIER, purpose=ctx.purpose(f"section{i}"),
                         max_tokens=max_tok, priority="background")
        body = str(reply).strip()
        with path.open("a", encoding="utf-8") as f:
            f.write(f"## {head}\n\n{body}\n\n")
        tail = body[-300:]
        state["done"] = i
        _save_state(ctx, state)
    ctx.progress(f"done ({count_words(path.read_text(encoding='utf-8'))} words)")
    try:
        store.kv_delete(f"{RESUME_PREFIX}{ctx.job.id}")
    except Exception as e:
        log.debug("resume state not cleared: %s", e)
    return str(path)


def count_words(text: str) -> int:
    return len(re.findall(r"[^\s#*`>-]+", text))
