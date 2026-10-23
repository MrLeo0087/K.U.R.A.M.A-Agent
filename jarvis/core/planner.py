"""Multi-intent planner: cheap regex detection first, a tiny fast-tier structured call only when flagged.

plan(text) -> Plan(tasks=[{"text", "kind": "quick"|"long"}], method="single"|"llm"|"rules").
Single-intent requests cost zero extra tokens. The long-job heuristic (big writing/code/scan
requests) also applies to single requests, so "write a 2000-word essay" becomes a background job.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from jarvis.core import config, llm, router

log = logging.getLogger("jarvis.planner")

# Separators (en / hi / ne romanized + Devanagari). Words need whitespace around them.
_SEP = re.compile(
    r"\s*(?:[,;]|[.!?।]\s|(?<!\S)(?:and\s+then|after\s+that|and|then|also|aur|phir|ani|ra|"
    r"अनि|र|और|फिर|तथा|त्यसपछि)(?!\S))\s*", re.I)
# Command verbs that come at the end of the clause in Hindi/Nepali.
_HI_NE_VERBS = re.compile(
    r"(?<![\w])(?:kholo|khol|kholdo|kholdeu|kholnus|kholideu|bajao|bajau|chalao|chalau|likho|"
    r"lekh\w*|batao|bataau|dekhao|dekhau|band\s+karo|kar\s+do|garnus|gara)(?![\w])|"
    r"(?:खोल|बजा|लिख|लेख|चला|बता|दिखा|देखा|गर्नु|करो|कर\s+दो)", re.I)
_NOUNS = re.compile(
    r"(?<![\w])(?:essays?|articles?|stor(?:y|ies)|reports?|blog\s+posts?|blogs?|papers?|thesis|"
    r"novels?|chapters?|speech|documents?|nibandha?|kahani|katha)(?![\w])|"
    r"(?:निबंध|निबन्ध|लेख|कथा|कहानी|रिपोर्ट|प्रतिवेदन)", re.I)
_GEN = re.compile(
    r"(?<![\w])(?:write|generate|draft|compose|create|prepare|produce|make|likho|likh\w*|lekh\w*)"
    r"(?![\w])|(?:लिख|लेख)", re.I)
_SHORT = re.compile(r"(?<![\w])(?:short|brief|small|quick|tiny|one[- ]line|few\s+lines|sentence|"
                    r"chhoto|chhota)(?![\w])|(?:छोटो|छोटा|छोटी)", re.I)
_CODE = re.compile(r"(?<![\w])(?:write|generate|create|build|make|code)(?![\w]).{0,40}?(?<![\w])"
                   r"(?:code|script|program|app|application|project|website|game|module)(?![\w])", re.I)
_SCAN = re.compile(r"(?<![\w])(?:scan|analy[sz]e|review|audit)(?![\w]).{0,30}?(?<![\w])"
                   r"(?:whole|entire|full|all)(?![\w]).{0,20}?(?<![\w])"
                   r"(?:repo|repository|codebase|project|code)(?![\w])", re.I)
_NUM_WORDS = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
              "eight": 8, "nine": 9, "ten": 10, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
              "hundred": 100, "thousand": 1000, "hazar": 1000, "hajar": 1000, "sau": 100,
              "हजार": 1000, "सौ": 100, "सय": 100}
_NUM = r"(?:\d[\d,]*(?:\.\d+)?k?|(?:(?:a|one|two|three|four|five|six|seven|eight|nine|ten|twenty|" \
       r"thirty|forty|fifty)[\s-]+)?(?:hundred|thousand|hazar|hajar|sau|हजार|सौ|सय)|" \
       r"twenty|thirty|forty|fifty)"
_UNITS = {"word": 1, "words": 1, "shabd": 1, "शब्द": 1, "line": 0, "lines": 0, "पंक्ति": 0,
          "page": 400, "pages": 400, "paragraph": 100, "paragraphs": 100}
_LEN = re.compile(r"(?:of\s+)?(?:about\s+|around\s+|~)?(" + _NUM + r")[\s-]*(" +
                  "|".join(sorted(map(re.escape, _UNITS), key=len, reverse=True)) +
                  r")(?:[\s-]+long)?", re.I)
_LEAD = re.compile(r"^\s*(?:(?:hey\s+)?jarvis[\s,]+)?(?:please\s+)?(?:(?:can|could|would|will)\s+you\s+"
                   r"(?:please\s+)?)?(?:write|generate|draft|compose|create|prepare|produce|make)"
                   r"\s+(?:me\s+)?(?:an?\s+|the\s+)?", re.I)

PLAN_PROMPT = (
    "Split the user's request into independent tasks (at most 4), each a self-contained command "
    "in the user's own words and language. kind=long for writing long text (essay, article, story, "
    "report), generating code, or scanning a whole project; otherwise quick. If it is really one "
    "request, return one task."
)


class Task(BaseModel):
    text: str = Field(description="one self-contained task")
    kind: Literal["quick", "long"] = "quick"


class TaskPlan(BaseModel):
    """Independent tasks in the user's request."""
    tasks: list[Task] = Field(default_factory=list)


@dataclass
class Plan:
    tasks: list[dict] = field(default_factory=list)
    method: str = "single"  # single | llm | rules


# --- heuristics ---
def _num(tok: str) -> int:
    t = tok.lower().replace(",", "").strip()
    if t.endswith("k") and t[:-1].replace(".", "").isdigit():
        return int(float(t[:-1]) * 1000)
    if t.replace(".", "").isdigit():
        return int(float(t))
    total = 1
    for w in re.split(r"[\s-]+", t):
        total *= _NUM_WORDS.get(w, 1)
    return total


def target_words(text: str) -> int | None:
    """Requested length in words (lines/pages/paragraphs converted), or None."""
    m = _LEN.search(text)
    if not m:
        return None
    n, unit = _num(m.group(1)), m.group(2).lower()
    per = _UNITS.get(unit, 1) or config.WORDS_PER_LINE
    return max(1, n * per)


def job_kind(text: str) -> str:
    """write | code | scan."""
    if _SCAN.search(text):
        return "scan"
    if _CODE.search(text) and not _NOUNS.search(text):
        return "code"
    return "write"


def is_long_job(text: str) -> bool:
    if _SCAN.search(text) or _CODE.search(text):
        return True
    words = target_words(text)
    gen, noun = bool(_GEN.search(text)), bool(_NOUNS.search(text))
    if words is not None and (gen or noun):
        return words >= config.LONG_JOB_MIN_WORDS
    if noun and gen:
        return not _SHORT.search(text)
    return False


def title_of(text: str) -> str:
    """Short job title: 'write a 300-word essay about Nepal' -> 'essay about Nepal'."""
    t = _LEN.sub(" ", text)
    t = _LEAD.sub("", t)
    t = re.sub(r"\s+", " ", t).strip(" .,!?;:।-")
    t = re.sub(r"^(?:an?|the)\s+", "", t, flags=re.I)
    return (t[:60].rsplit(" ", 1)[0] if len(t) > 60 else t) or "document"


def detect_lang(text: str) -> str:
    """en | hi | ne (Devanagari only; romanized text counts as English for templates)."""
    if not re.search(r"[ऀ-ॿ]", text):
        return "en"
    ne = len(re.findall(r"छ|अनि|मलाई|तिमी|गर्नु|बज्यो|हुन्छ|देऊ|दिनु|लेख्नु|खोल्नु|कति", text))
    hi = len(re.findall(r"है|और|करो|मुझे|क्या|दो|लिखो|खोलो|कितने|मैं", text))
    return "ne" if ne > hi else "hi"


def split_clauses(text: str) -> list[str]:
    return [c.strip() for c in _SEP.split(text) if c and c.strip()]


def is_command(clause: str) -> bool:
    return bool(router.looks_like_command(clause) or router.rule_groups(clause)
                or _HI_NE_VERBS.search(clause) or is_long_job(clause))


def is_multi(text: str) -> bool:
    """Cheap multi-intent flag: a separator plus at least two command-like clauses."""
    clauses = split_clauses(text)
    if len(clauses) < 2:
        return False
    return sum(1 for c in clauses if is_command(c)) >= 2


def _kind(text: str, llm_kind: str = "quick") -> str:
    if is_long_job(text):
        return "long"
    if llm_kind == "long" and (_GEN.search(text) or _NOUNS.search(text)):
        return "long"
    return "quick"


def _rule_tasks(text: str) -> list[dict]:
    """Fallback split: command clauses; other clauses are glued to the previous command."""
    out: list[str] = []
    for c in split_clauses(text):
        if is_command(c) or not out:
            out.append(c)
        else:
            out[-1] = f"{out[-1]}, {c}"
    return [{"text": t, "kind": _kind(t)} for t in out[: config.PLANNER_MAX_TASKS]]


def decompose(text: str) -> list[dict]:
    """Fast tier with_structured_output(TaskPlan). Raises llm.LLMError on failure."""
    msgs = [{"role": "system", "content": PLAN_PROMPT}, {"role": "user", "content": text}]
    tp = llm.structured(msgs, TaskPlan, tier="fast", purpose="planner",
                        max_tokens=config.PLANNER_MAX_TOKENS, priority="interactive")
    tasks = [{"text": t.text.strip(), "kind": _kind(t.text, t.kind)}
             for t in tp.tasks if t.text and t.text.strip()]
    return tasks[: config.PLANNER_MAX_TASKS]


def plan(text: str) -> Plan:
    if not is_multi(text):
        return Plan([{"text": text, "kind": "long" if is_long_job(text) else "quick"}], "single")
    try:
        tasks = decompose(text)
        method = "llm"
    except llm.LLMError as e:
        log.warning("planner decomposition failed, splitting by rules: %s", e)
        tasks, method = [], "rules"
    if not tasks:
        tasks, method = _rule_tasks(text), "rules"
    if len(tasks) == 1 and tasks[0]["kind"] == "quick":
        tasks = [{"text": text, "kind": "quick"}]  # really one request: keep the user's wording
    return Plan(tasks, method)
