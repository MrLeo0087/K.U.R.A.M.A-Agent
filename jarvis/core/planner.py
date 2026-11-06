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
    "Split the request into separate tasks, one per action (max 8). Each different action is its "
    "own task, even if joined by and/also/then/र/अनि/और. Keep each task in the user's own words and "
    "language (only fix obvious speech-to-text slips), e.g. 'what is the time in Nepal'. kind=long only for "
    "writing long text (essay, article, story, report), generating code, or scanning a whole "
    "project; else quick. depends_on: indices of earlier tasks whose result this task needs (it, this, that, "
    "the folder/file/image/document, then). 'give me the result', 'tell me', 'summarize it' are part of the "
    "previous task, never a task of their own. Leave out words that ask for nothing (let's work, ok so).\n"
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
    dropped: list[str] = field(default_factory=list)  # parts over PLANNER_MAX_TASKS: the reply names them


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


_LATER_CUE = re.compile(r"\b(?:later|tomorrow|tonight|job\s*list|jobs?\s+list|your\s+jobs|(?:a|this|that|as\s+a|the)\s+job\b|"
                        r"add\s+(?:a\s+|this\s+|these\s+)?jobs?|queue|don'?t\s+(?:start|do\s+it|begin)|not\s+now|"
                        r"when\s+i\s+say\s+(?:go|start)|wait\s+for\s+my|keep\s+(?:it|this)\s+for)\b", re.I)


def queue_meant(text: str) -> bool:
    """The request MAY mean 'add this to KURAMA's job list for later' (then the AI, with the jobs tool, decides add vs
    do). Only when the words ask for later at all ('for later', 'job list', 'queue', "don't start", 'tomorrow'):
    by meaning alone 'open youtube and send hello to telegram' scored 'maybe later' (-0.015 vs the -0.04 line), so
    nearly every multi-task request went to the AI as ONE task and only its first part was done (11-03: 1 of 5).
    Held-out check 11-03: later -0.145..0.058 and now -0.245..-0.01 overlap, so the words decide whether to ask."""
    return bool(_LATER_CUE.search(text or ""))


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
        if out and _PATH_TAIL.match(c) and not router.looks_like_command(c):  # "list files in this folder" is a task
            out[-1] = f"{out[-1]} then {c}"
        else:
            out.append(c)
    return _share_verb(out)


_SHARED_VERB = re.compile(r"^(?:please\s+)?(?P<v>open|close|launch|quit)\s+\S", re.I)


def _share_verb(clauses: list[str]) -> list[str]:
    """'Open YouTube, Facebook and Instagram': the parts after the first are bare names that share its verb ->
    'open Facebook', 'open Instagram' (11-02 fa0878a6: 'Open the YouTube and Facebook.' opened only YouTube)."""
    if len(clauses) < 2 or not (m := _SHARED_VERB.match(clauses[0])):
        return clauses
    rest = [c.strip(" .!?,") for c in clauses[1:]]
    if any(not c or len(c.split()) > 3 or router.looks_like_command(c) or re.search(r"\b(?:me|it|this|that)\b", c, re.I)
           for c in rest):
        return clauses
    return [clauses[0], *[f"{m.group('v').lower()} {c}" for c in rest]]


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
    r"(?<![\w'])(?:it|its|that(?=\s*(?:$|[.,!?;]|(?:to|on|in|into|for|with|as|from|and|too|also|again|please|now|"
    r"here|there|folder|file|image|photo|picture|video|link|page|note|text|code|script|song|list|one)\b))|them|those|"
    r"this|these|then|after\s+that|afterwards|the\s+(?:folder|file|directory|poem|"
    r"text|results?|output|note|story|essay|code|script|song|list|summary|answer|message|page|image|photo|"
    r"document|project|repo))(?![\w'])|त्यो|त्यसलाई|त्यसमा|यसलाई|यसमा|उसे|इसे|उसमें|इसमें|फिर|त्यसपछि", re.I)


def is_result_tail(clause: str) -> bool:
    return bool(RESULT_TAIL.match(clause.strip()))


_IMG_TASK = re.compile(r"\b(?:image|picture|photo|drawing|painting|illustration|draw|artwork)\b", re.I)
_WALL_TAIL = re.compile(r"^\s*(?:and\s+|then\s+)?(?:please\s+)?(?:make|set|use|keep|put|apply)\s+(?:it|this|that|"
                        r"the (?:image|picture|photo))?\s*(?:as\s+)?(?:my\s+|the\s+)?(?:desktop\s+)?(?:wallpaper|background)\b",
                        re.I)


# "...and send it to my Telegram": a follow-up of the previous task (sent when its job is done)
_TG_TAIL = re.compile(r"^\s*(?:(?:and|then|also)\s+)*(?:please\s+)?(?:send|share|forward|get|put|drop|deliver)\s+(?:it|this|that|them|"
                      r"the\s+\w+)?\s*(?:image|picture|photo|pic|file)?\s*(?:to|in|on|via|through)\s+(?:my\s+)?"
                      r"(?:telegram|phone|mobile)\b", re.I)


# "...and when the timer completes, send me a message on Telegram": a condition on the previous task, not a new
# task (it was run as a second, duplicate timer)
_WHEN_TAIL = re.compile(r"^\s*(?:(?:and|then|also)\s+)*(?:when|once|after|as\s+soon\s+as|jab|jaba)\b.{0,40}?\b(?:complete[sd]?|"
                        r"finish(?:e[sd])?|done|over|ends?|ended|rings?|goes\s+off|up|ready|sakiyo|sakincha|"
                        r"khatam|ho\s+jaye)\b", re.I)


def is_when_tail(clause: str) -> bool:
    return bool(_WHEN_TAIL.match(clause.strip()))


def merge_tails(tasks: list[dict]) -> list[dict]:
    """Glue "give me the result"-style tasks onto the previous task; remap depends_on indices."""
    out: list[dict] = []
    remap: dict[int, int] = {}
    for i, t in enumerate(tasks):
        if out and _TG_TAIL.match(t["text"]) and is_long_job(out[-1]["text"]):
            out[-1] = {**out[-1], "telegram": True}  # the job's result goes to Telegram when it's done
            remap[i] = len(out) - 1
            continue
        if out and (is_result_tail(t["text"]) or is_when_tail(t["text"]) or (_IMG_TASK.search(out[-1]["text"]) and _WALL_TAIL.match(t["text"]))):
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


# 'it' that points at nothing ('what time is it', 'is it raining'): not a reference to the task before
_DUMMY_IT = re.compile(r"\b(?:what\s+time\s+is\s+it|is\s+it\s+(?:going\s+to\s+)?(?:rain\w*|cold|hot|sunny|late|snow\w*)|"
                       r"(?:when|once|after|as\s+soon\s+as)\s+it(?:'s|\s+is)?\s+(?:finish\w*|done|over|ends?|ended|rings?|"
                       r"goes\s+off|complete[sd]?|ready))\b", re.I)  # 'set a timer and when it finishes...': its own end


def refers_back(text: str) -> bool:
    return bool(_REF.search(_DUMMY_IT.sub(" ", text)))


_ITEM = re.compile(r"(?:^|\s)\(?(\d{1,2})[.)]\s+")


def _items_of(text: str, tasks: list[dict]) -> list[int | None]:
    """Which numbered item ("1. ... 2. ...") of the request each task came from; None when not numbered."""
    marks = [(m.start(), m.end()) for m in _ITEM.finditer(text or "")]
    if len(marks) < 2:
        return [None] * len(tasks)
    low = (text or "").lower()
    bounds = [(e, marks[k + 1][0] if k + 1 < len(marks) else len(low)) for k, (_, e) in enumerate(marks)]
    out: list[int | None] = []
    for t in tasks:
        words = re.findall(r"[a-z0-9]+", t["text"].lower())[:3]
        pos = -1
        for n in range(len(words), 0, -1):  # the task's first words, as they appear in the request
            m = re.search(r"\W+".join(map(re.escape, words[:n])), low)
            if m:
                pos = m.start()
                break
        out.append(next((k for k, (a, b) in enumerate(bounds) if a <= pos < b), None) if pos >= 0 else None)
    return out


_THING_STOP = frozenset("""send open make create write show tell give find search take play save start stop please
about with from into this that them then also some what when your mine have will would could should there their
telegram generate research download upload list check turn read delete remove copy move rename close install build
draw explain summarize summarise translate convert simple short long small large big best more most every each
detail detailed quick latest new good""".split())  # verbs / sizes: 'generate image' and 'generate code' share no thing


def _shares_thing(a: str, b: str) -> bool:
    """Both steps talk about the same thing ('take a screenshot' / 'save the screenshot in the trip folder')."""
    wa = {w.rstrip("s") for w in re.findall(r"[a-z][a-z.]{3,}", a.lower())} - _THING_STOP
    wb = {w.rstrip("s") for w in re.findall(r"[a-z][a-z.]{3,}", b.lower())} - _THING_STOP
    return bool(wa & wb)


def add_dependencies(tasks: list[dict], text: str = "") -> list[dict]:
    """Simple rule on top of the model's depends_on: a task that refers back depends on the previous one. When the
    user NUMBERED the tasks ("1. image 2. essay 3. code"), a dependency the model invents across items is dropped
    (it chained all three, so the essay waited for the image); within one item it stays."""
    items = _items_of(text, tasks)
    for i, t in enumerate(tasks):
        deps = {d for d in t.get("depends_on", []) if isinstance(d, int) and 0 <= d < i}
        back = refers_back(t["text"]) or is_result_tail(t["text"]) or is_when_tail(t["text"])
        if i and back and not deps:
            deps.add(i - 1)
        if deps:  # a step that needs something also waits for every earlier step making a thing it names
            deps |= {d for d in range(i) if _shares_thing(t["text"], tasks[d]["text"])}  # ('the trip folder')
        # HARD = really uses that step's result (points back, or names what it made: 'generate an image' -> 'send the
        # image'); the other links only keep the order. A failed step skips only the steps that hard-need it: the
        # model chained 'tell me the weather in Pokhara' after 'save the screenshot' and one failure skipped the
        # weather (11-03).
        hard = deps if back else {d for d in deps if _shares_thing(t["text"], tasks[d]["text"])}
        if items[i] is not None:  # numbered: only within the same item ("save it" in item 2 is item 2's own essay)
            deps = {d for d in deps if items[d] is None or items[d] == items[i]}
        if deps:
            t["depends_on"] = sorted(deps)
            soft = sorted(deps - hard)
            if soft:
                t["soft"] = soft  # waits for these, but runs even if they fail
            else:
                t.pop("soft", None)
        else:
            t.pop("depends_on", None)
            t.pop("soft", None)
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


_ONE_EDIT = re.compile(r"\b(?:this|the|my)\s+(?:selected|selective|highlighted|whole\s+)?\s*(?:part\s+of\s+(?:the\s+)?)?"
                       r"(?:code|function|text|sentence|paragraph|line|lines|word|selection)\b.*\b(?:replace|put)\s+it\b|"
                       r"\breplace\s+(?:it|this|the\s+\w+)\s+with\b", re.I)


def is_multi(text: str) -> bool:
    """Cheap multi-intent flag: a separator plus at least two command-like clauses."""
    from jarvis.core import fastpath
    if re.match(r"^\s*/[a-z]", text or "", re.I):  # a /command is ONE request: '/claude say <a long message with
        return False  # "..", "also", "make it...">' was split into tasks and only its first part reached Claude Code
    if fastpath.to_file_intent(text):  # "<code description, with ands> ... write it in this file": ONE request
        return False
    if fastpath.app_name_intent(text):  # "when I say open browser, open Brave": two 'open's, ONE name to keep
        return False
    if "Traceback (most recent call last)" in text or re.search(r"^\s*File \"[^\"]+\", line \d+", text, re.M):
        return False  # a pasted traceback is one thing to explain, not several tasks
    if _ONE_EDIT.search(text):
        return False  # "make this selected code better and replace it" is ONE edit of the selection, not two tasks
    clauses = split_clauses(text)
    if len(clauses) < 2:
        return False
    if len(clauses) == 2 and is_when_tail(clauses[1]):
        return False  # "set a timer and when it's done tell me on Telegram" is one request (no planner tokens)
    is_tail = lambda c: bool(_WALL_TAIL.match(c) or _TG_TAIL.match(c))  # noqa: E731
    if _IMG_TASK.search(clauses[0]) and is_tail(clauses[-1]) and not any(
            re.match(r"\s*(?:open|play|send|search|close|start|launch)\b", c, re.I)
            for c in clauses[1:-1] if not is_tail(c)):
        return False  # "draw X (and set it as my wallpaper) (and send it to Telegram)" is ONE generate_image call
    if len(text.split()) > 30 and sum(1 for c in clauses if is_command(" ".join(c.split()[:3]))) < 2:
        return False  # a long description / complaint ("the telegram said it failed and the file has no sound"):
        # ONE request to understand, not several tasks (one was split into 4 tasks, 12 AI calls, 16k tokens)
    return sum(1 for c in clauses if is_command(c)) >= 2


def one_tool(text: str) -> bool:
    """Commas made it look like several tasks, but every part that means something asks for the SAME tool and the
    whole sentence matches it: 'keep this link in read later, I will read this link later' is ONE save."""
    from jarvis.core import fastpath
    try:
        whole = fastpath.match(text)
        if whole is None:
            return False
        tools = set()
        where = str(whole.args.get("path") or "") if isinstance(whole.args, dict) else ""
        for c in split_clauses(text):
            if where and _names_a_place_in(c, where):
                continue  # 'from project1 then new_project and kurama folder': the whole request's path, not a task
            i = fastpath.match(c)
            if i is None:
                if is_command(c) and len(c.split()) >= 2 and not re.match(r"\s*(?:i|we|you|it|this|that)\b", c, re.I):
                    return False  # a real task no shortcut knows ('write a poem about rain', 'make an image for it'):
                continue  # the whole sentence's shortcut would drop it (11-03: 'send both to telegram' sent "both");
                #           'I will read this link later' says something about the other part, it isn't a task
            if not i.tool.startswith("_"):  # 'Okay,' / 'thanks' are not tasks
                tools.add(i.tool)
    except Exception:  # noqa: BLE001 - never break a turn on the check
        return False
    return tools <= {whole.tool}


def _names_a_place_in(clause: str, path: str) -> bool:
    """Every name in this clause is a folder on `path` (only glue words otherwise): it describes where, it is no task."""
    from jarvis.core import fastpath

    def key(x: str) -> str:
        return re.sub(r"[\W_]+", "", x.lower())
    names = [n for n in re.split(r"[|,.;!?]+", fastpath._FOLDER_GLUE.sub("|", clause)) if key(n)]
    return bool(names) and all(key(n) in key(path) for n in names)


_MEDIA_MAKE = re.compile(r"\b(?:image|images|picture|pictures|photo|photos|drawing|painting|illustration|wallpaper|"
                         r"logo|video|reel|short|slideshow|audio|mp3|song|music|chart|graph|diagram)\b", re.I)


def _kind(text: str, llm_kind: str = "quick") -> str:
    if _MEDIA_MAKE.search(text) and not re.search(r"\b(?:essay|poem|story|report|article|code|script|letter)\b", text, re.I):
        return "quick"  # its own tool makes it (and runs in the background itself): the WRITER wrote a text
        #                 'description' of the picture into an .md file instead of making the image (11-04 00:11)
    if is_long_job(text):
        return "long"
    if llm_kind == "long" and (_GEN.search(text) or _NOUNS.search(text)):
        return "long"
    return "quick"


def parts(text: str) -> list[str]:
    """The request's clauses without filler ("let's work ..", "ok so"): what the steps are made of."""
    from jarvis.core import taskgraph
    cl = split_clauses(text)
    kept = [c for c in cl if not taskgraph.filler(c)]
    return kept or cl


def drop_filler(tasks: list[dict]) -> list[dict]:
    """The model's tasks without the ones that ask for nothing; depends_on indices follow."""
    from jarvis.core import taskgraph
    keep = [i for i, t in enumerate(tasks) if not taskgraph.filler(t["text"])]
    if not keep or len(keep) == len(tasks):
        return tasks
    remap = {old: new for new, old in enumerate(keep)}
    out = []
    for old in keep:
        t = dict(tasks[old])
        deps = sorted({remap[d] for d in t.get("depends_on", []) if d in remap})
        t.pop("depends_on", None)
        if deps:
            t["depends_on"] = deps
        out.append(t)
    return out


def _rule_tasks(text: str) -> list[dict]:
    """Fallback split: command clauses; other clauses are glued to the previous command."""
    out: list[str] = []
    for c in parts(text):
        if is_command(c) or not out:
            out.append(c)
        else:
            out[-1] = f"{out[-1]}, {c}"
    return [{"text": t, "kind": _kind(t)} for t in out]  # (the cap and its note: plan())


_FILLER_WORDS = frozenset("""want you the and my now here there then thne than just also please again want need can
could would okay its""".split())  # 'now create a .py file in here' = the plan's 'create a .py file' (11-04 duplicates)


def _covers(task: str, part: str) -> bool:
    words = {w for w in re.findall(r"[a-z0-9]{3,}", part.lower())} - _THING_STOP - _FILLER_WORDS
    if not words:
        return True
    have = {w for w in re.findall(r"[a-z0-9]{3,}", task.lower())}
    return len(words & have) / len(words) >= 0.5


def cover(text: str, tasks: list[dict]) -> list[dict]:
    """Every part of the request is in the plan: a command part no task covers ('turn on the Bluetooth of my laptop',
    'send the status of my RAM in the telegram' were left out of a 10-part plan, 11-04) is added as its own task."""
    out = list(tasks)
    for part in parts(text):
        if is_command(part) and len(part.split()) >= 3 and not any(_covers(t["text"], part) for t in out):
            out.append({"text": part.strip(" ."), "kind": _kind(part)})
            log.info("planner left out %r: added", part)
    return out


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
    return tasks  # (the cap and its note: plan())


def _shortcut_tasks(text: str) -> list[dict]:
    """Independent quick parts that each match an instant shortcut ('weather in Pokhara and what time is it')."""
    from jarvis.core import fastpath
    ps = parts(text)
    if not 1 <= len(ps) <= config.PLANNER_MAX_TASKS:
        return []
    if any(is_long_job(p) or fastpath.match(p) is None for p in ps):
        return []  # a part that refers back ('open it in vs code') is fine: the step gets what the earlier one made
    return [{"text": p, "kind": "quick"} for p in ps]


def plan(text: str) -> Plan:
    if (is_multi(text) or is_long_job(text)) and queue_meant(text):  # "add a job: write an essay ...": the AI (with
        return Plan([{"text": text, "kind": "quick"}], "single")  # the jobs tool) decides add vs do; never auto-start
    if not is_multi(text):
        return Plan([{"text": text, "kind": "long" if is_long_job(text) else "quick"}], "single")
    if quick := _shortcut_tasks(text):  # every part is a 0-token shortcut on its own: no planner call
        return Plan(add_dependencies(merge_tails(quick), text), "rules")  # 'set a timer ... and when it finishes
        #   send me break time on telegram' is ONE timer that messages the phone (it was split: never sent, 11-03)
    from jarvis.core import taskgraph
    if config.TASK_GRAPH and (seen := taskgraph.learned_plan(text, parts(text))):  # planned (and worked) before
        return Plan(add_dependencies(merge_tails(seen), text), "learned")
    try:
        tasks = drop_filler(decompose(text))
        method = "llm"
    except llm.LLMError as e:
        log.info("planner decomposition failed, splitting by rules: %s", e)
        tasks, method = [], "rules"
    if not tasks:
        tasks, method = _rule_tasks(text), "rules"
    tasks = cover(text, tasks)
    tasks = add_dependencies(merge_tails(tasks), text)
    if len(tasks) == 1 and tasks[0]["kind"] == "quick":
        tasks = [{"text": text, "kind": "quick"}]  # really one request: keep the user's wording
    if len(tasks) > config.PLANNER_MAX_TASKS:  # never dropped in silence ('turn on bluetooth' and 'send my RAM
        dropped = [t["text"] for t in tasks[config.PLANNER_MAX_TASKS:]]  # status' vanished at 8 tasks, 11-04)
        tasks = tasks[:config.PLANNER_MAX_TASKS]
        return Plan(tasks, method, dropped)
    return Plan(tasks, method)
