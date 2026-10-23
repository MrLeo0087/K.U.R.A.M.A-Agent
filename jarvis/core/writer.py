"""Long-document writer job: outline (1 structured call) -> sections (max ~1500 tokens each),
appended progressively to data/outputs/<YYYYmmdd-HHMM>-<slug>.md. Smart model only
(config.WRITER_TIER), every call paced by the rate limiter at background priority. Respects cancel.
"""
from __future__ import annotations

import logging
import math
import re
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from jarvis.core import config, llm, planner

log = logging.getLogger("jarvis.writer")

LANG_NAMES = {"en": "English", "hi": "Hindi (Devanagari script)", "ne": "Nepali (Devanagari script)"}
OUTLINE_PROMPT = ("Plan a {what} for the user's request. Return a short title and exactly {n} "
                  "section headings, all in {lang}.")
SECTION_PROMPT = ("You are a skilled writer. Write in {lang}. Output only the body of the requested "
                  "section as Markdown paragraphs: no heading, no preamble, no closing remarks.")
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
    words = min(planner.target_words(request) or config.WRITER_DEFAULT_WORDS, config.WRITER_MAX_WORDS)
    n, max_tok = plan_sections(words, lang)
    ctx.progress(f"outlining ({n} sections, ~{words} words)")
    outline = _outline(ctx, request, n, lang, kind)
    n = len(outline.sections)
    per = max(30, round(words / n))
    path = output_path(ctx.job.title)
    path.write_text(f"# {outline.title}\n\n", encoding="utf-8")
    ctx.set_output(path)
    system = CODE_PROMPT if kind == "code" else SECTION_PROMPT.format(lang=LANG_NAMES[lang])
    tail = ""
    for i, head in enumerate(outline.sections, 1):
        ctx.check()
        ctx.progress(f"section {i}/{n}")
        msgs = [{"role": "system", "content": system},
                {"role": "user", "content":
                    f"Request: {request}\nTitle: {outline.title}\nOutline: {'; '.join(outline.sections)}\n"
                    + (f"The previous section ended: ...{tail}\n" if tail else "")
                    + f"Write section {i} of {n}, \"{head}\", in about {per} words."}]
        reply = llm.chat(msgs, tier=config.WRITER_TIER, purpose=ctx.purpose(f"section{i}"),
                         max_tokens=max_tok, priority="background")
        body = str(reply).strip()
        with path.open("a", encoding="utf-8") as f:
            f.write(f"## {head}\n\n{body}\n\n")
        tail = body[-300:]
    ctx.progress(f"done ({count_words(path.read_text(encoding='utf-8'))} words)")
    return str(path)


def count_words(text: str) -> int:
    return len(re.findall(r"[^\s#*`>-]+", text))
