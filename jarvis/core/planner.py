"""Multi-intent planner: cheap regex detection first, a tiny fast-tier structured call only when flagged.

plan(text) -> Plan(tasks=[{"text", "kind": "quick"|"long", "depends_on"?: [i, ...]}], method=...).
P7c: a task that refers back ("it", "that", "the folder", "then", ...) depends on the previous one;
chains() groups dependent tasks so the agent runs them in order (independent ones still fan out).
Trailing "and give me the result / tell me / summarize it" clauses belong to the previous task.
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
    "Split the request into separate tasks, one per action (max 4). Each different action is its "
    "own task, even if joined by and/also/then/र/अनि/और. Keep each task in the user's own words and "
    "language (only fix obvious speech-to-text slips), e.g. 'what is the time in Nepal'. kind=long only for "
    "writing long text (essay, article, story, report), generating code, or scanning a whole "
    "project; else quick. depends_on: indices of earlier tasks whose result this task needs (it, that, "
    "the folder/file/poem, then). 'give me the result', 'tell me', 'summarize it' are part of the "
    "previous task, never a task of their own.\n"
    "Example: 'open google and tell me the time' -> [open Google (quick), tell me the time (quick)]"
)


class Task(BaseModel):
    text: str = Field(description="one self-contained task")
    kind: Literal["quick", "long"] = "quick"
    depends_on: list[int] = Field(default_factory=list, description="indices of earlier tasks it needs")


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


_APP_CODE = re.compile(r"(?<![\w])(?:vs|bs|visual\s+studio)\s+code(?![\w])", re.I)
_CONTROL = re.compile(r"(?<![\w])(?:full\s?screen|maximi[sz]e|minimi[sz]e|snap|split|side\s+by\s+side|"
                      r"window|open|close|focus|switch\s+to|launch|quit)(?![\w])", re.I)


# "create a new python project called X" = the scaffold_project tool, not a writing job
_SCAFFOLD = re.compile(r"(?<![\w])(?:create|make|start|scaffold|set\s*up|init(?:iali[sz]e)?|bana\w*)\s+(?:a\s+|an\s+)?"
                       r"(?:new\s+)?(?:python|fastapi|langgraph|data[- ]science|cli|flask|django)?\s*"
                       r"(?:project|app\s+skeleton|boilerplate|template)(?![\w])", re.I)


def is_long_job(text: str) -> bool:
    if _SCAFFOLD.search(text) and target_words(text) is None:
        return False
    text = _APP_CODE.sub("vscode", text)  # "VS Code" is an app, not "write code"
    if _CONTROL.search(text) and target_words(text) is None and not _NOUNS.search(text):
        return False  # window/app control ("make VS Code full screen")
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


# A clause that is only a folder name ("tara folder", "the src directory") continues a spoken path
# ("search main.py in project1 then tara folder"), it is not a separate task.
_PATH_TAIL = re.compile(r"^(?:(?:and|then)\s+)?(?:(?:in|inside|into)\s+)?(?:the\s+|my\s+)?[\w .-]{1,40}?\s+"
                        r"(?:folder|directory|dir|subfolder|फोल्डर)\s*[.?!]*$", re.I)


def split_clauses(text: str) -> list[str]:
    out: list[str] = []
    for c in (c.strip() for c in _SEP.split(text) if c and c.strip()):
        if out and _PATH_TAIL.match(c):
            out[-1] = f"{out[-1]} then {c}"
        else:
            out.append(c)
    return out


# "...and give me the result": asks for the previous task's answer -> part of that task (P7c).
RESULT_TAIL = re.compile(
    r"^(?:(?:and|then|also|aur|ani)\s+)*(?:please\s+)?(?:(?:can|could)\s+you\s+)?(?:"
    r"(?:give|tell|show|bring|send)\s+(?:me|us)(?:\s+(?:the|its|their|all)?\s*(?:results?|answers?|summary|"
    r"details|scores?|output|it|that|them|what\s+you\s+(?:find|found)|top\s+results?))?|let\s+me\s+know|"
    r"summari[sz]e\s+(?:it|that|them|the\s+results?)|read\s+(?:it|that|them)(?:\s+(?:out|aloud))?(?:\s+to\s+me)?|"
    r"explain\s+(?:it|that|them)|(?:mujhe\s+)?(?:result\s+)?batao|malai\s+(?:bhana|bhannu|dekhau)|"
    r"(?:मुझे\s+)?बताओ|मलाई\s+भन\S*|नतिजा\s+देखाउ\S*)\s*[.!?।]*$", re.I)
# Refers back to an earlier task's result -> depends on the previous task (P7c).
_REF = re.compile(
    r"(?<![\w'])(?:it|its|that|them|those|then|after\s+that|afterwards|the\s+(?:folder|file|directory|poem|"
    r"text|results?|output|note|story|essay|code|script|song|list|summary|answer|message|page|image|photo|"
    r"document|project|repo))(?![\w'])|त्यो|त्यसलाई|त्यसमा|यसलाई|यसमा|उसे|इसे|उसमें|इसमें|फिर|त्यसपछि", re.I)


def is_result_tail(clause: str) -> bool:
    return bool(RESULT_TAIL.match(clause.strip()))


_IMG_TASK = re.compile(r"\b(?:image|picture|photo|drawing|painting|illustration|draw|artwork)\b", re.I)
_WALL_TAIL = re.compile(r"^\s*(?:and\s+|then\s+)?(?:please\s+)?(?:make|set|use|keep|put|apply)\s+(?:it|this|that|"
                        r"the (?:image|picture|photo))?\s*(?:as\s+)?(?:my\s+|the\s+)?(?:desktop\s+)?(?:wallpaper|background)\b",
                        re.I)


# "...and send it to my Telegram": a follow-up of the previous task (sent when its job is done)
_TG_TAIL = re.compile(r"^\s*(?:(?:and|then|also)\s+)*(?:please\s+)?(?:send|share|forward)\s+(?:it|this|that|them|"
                      r"the\s+\w+)?\s*(?:image|picture|photo|pic|file)?\s*(?:to|in|on|via|through)\s+(?:my\s+)?"
                      r"(?:telegram|phone|mobile)\b", re.I)


def merge_tails(tasks: list[dict]) -> list[dict]:
    """Glue "give me the result"-style tasks onto the previous task; remap depends_on indices."""
    out: list[dict] = []
    remap: dict[int, int] = {}
    for i, t in enumerate(tasks):
        if out and _TG_TAIL.match(t["text"]) and is_long_job(out[-1]["text"]):
            out[-1] = {**out[-1], "telegram": True}  # the job's result goes to Telegram when it's done
            remap[i] = len(out) - 1
            continue
        if out and (is_result_tail(t["text"]) or (_IMG_TASK.search(out[-1]["text"]) and _WALL_TAIL.match(t["text"]))):
            out[-1] = {**out[-1], "text": f"{out[-1]['text'].rstrip(' .,')} and {t['text'].strip()}"}
            remap[i] = len(out) - 1
            continue
        remap[i] = len(out)
        out.append(dict(t))
    for j, t in enumerate(out):
        deps = sorted({remap[d] for d in t.get("depends_on", []) if d in remap and remap[d] < j})
        if deps:
            t["depends_on"] = deps
        else:
            t.pop("depends_on", None)
    return out


def add_dependencies(tasks: list[dict]) -> list[dict]:
    """Simple rule on top of the model's depends_on: a task that refers back depends on the previous one."""
    for i, t in enumerate(tasks):
        deps = {d for d in t.get("depends_on", []) if isinstance(d, int) and 0 <= d < i}
        if i and _REF.search(t["text"]):
            deps.add(i - 1)
        if deps:
            t["depends_on"] = sorted(deps)
        else:
            t.pop("depends_on", None)
    return tasks


def chains(tasks: list[dict]) -> list[list[int]]:
    """Connected groups of task indices (in order). Single-index groups are independent tasks."""
    parent = list(range(len(tasks)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, t in enumerate(tasks):
        for d in t.get("depends_on", []):
            if 0 <= d < len(tasks):
                parent[find(i)] = find(d)
    groups: dict[int, list[int]] = {}
    for i in range(len(tasks)):
        groups.setdefault(find(i), []).append(i)
    return sorted(groups.values(), key=lambda g: g[0])


def is_command(clause: str) -> bool:
    if is_result_tail(clause):
        return False
    return bool(router.looks_like_command(clause) or router.rule_groups(clause)
                or _HI_NE_VERBS.search(clause) or is_long_job(clause))


def is_multi(text: str) -> bool:
    """Cheap multi-intent flag: a separator plus at least two command-like clauses."""
    if "Traceback (most recent call last)" in text or re.search(r"^\s*File \"[^\"]+\", line \d+", text, re.M):
        return False  # a pasted traceback is one thing to explain, not several tasks
    clauses = split_clauses(text)
    if len(clauses) < 2:
        return False
    is_tail = lambda c: bool(_WALL_TAIL.match(c) or _TG_TAIL.match(c))  # noqa: E731
    if _IMG_TASK.search(clauses[0]) and is_tail(clauses[-1]) and not any(
            re.match(r"\s*(?:open|play|send|search|close|start|launch)\b", c, re.I)
            for c in clauses[1:-1] if not is_tail(c)):
        return False  # "draw X (and set it as my wallpaper) (and send it to Telegram)" is ONE generate_image call
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
    tasks = []
    for t in tp.tasks:
        if t.text and t.text.strip():
            d = {"text": t.text.strip(), "kind": _kind(t.text, t.kind)}
            if t.depends_on:
                d["depends_on"] = list(t.depends_on)
            tasks.append(d)
    return tasks[: config.PLANNER_MAX_TASKS]


def plan(text: str) -> Plan:
    if not is_multi(text):
        return Plan([{"text": text, "kind": "long" if is_long_job(text) else "quick"}], "single")
    try:
        tasks = decompose(text)
        method = "llm"
    except llm.LLMError as e:
        log.info("planner decomposition failed, splitting by rules: %s", e)
        tasks, method = [], "rules"
    if not tasks:
        tasks, method = _rule_tasks(text), "rules"
    tasks = add_dependencies(merge_tails(tasks))
    if len(tasks) == 1 and tasks[0]["kind"] == "quick":
        tasks = [{"text": text, "kind": "quick"}]  # really one request: keep the user's wording
    return Plan(tasks, method)
