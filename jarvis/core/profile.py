"""Profile memory (P7 tiered memory, tier a): facts about the user as key -> value.

Tiers: (a) PROFILE facts here (replace, not append: a new "favorite editor" overwrites the old),
(b) EPISODIC session summaries (store.sessions, recall_session), (c) SEMANTIC RAG over code and
notes (memory.py), (d) explicit notes (remember/recall, unchanged).

Token rules:
- capture() is regex only (English + romanized/Devanagari Hindi/Nepali): zero LLM tokens per turn.
- extract_llm() is ONE fast-tier call per session END (config.PROFILE_LLM_EXTRACT), never per turn.
- context_line() adds NOTHING to the system prompt unless the turn looks personal/past-referencing,
  then at most config.PROFILE_INJECT_MAX relevant facts in <= config.PROFILE_INJECT_MAX_CHARS.
- Ranking = relevance x recency x hits; prune() keeps <= config.PROFILE_MAX facts.
"""
from __future__ import annotations

import logging
import math
import re
import time
from datetime import datetime

from jarvis.core import config, store

log = logging.getLogger("jarvis.profile")

I = re.I
PROTECTED = {"name", "home_city"}  # never pruned
SECRET = re.compile(r"pass(?:word|code)?|\bpin\b|otp|token|api key|secret|cvv|card number|bank account", I)

# --- key normalisation ---
_SYNONYMS = {
    "favourite": "favorite", "fav": "favorite", "colour": "color", "hometown": "hometown",
    "home town": "hometown", "city": "home_city", "home city": "home_city", "town": "home_city",
    "location": "home_city", "native language": "mother_tongue", "first language": "mother_tongue",
    "mother tongue": "mother_tongue", "job": "job", "profession": "job", "occupation": "job",
    "role": "job", "ide": "favorite_editor", "editor": "favorite_editor", "code editor": "favorite_editor",
    "favorite ide": "favorite_editor", "favorite code editor": "favorite_editor",
    "birth day": "birthday", "date of birth": "birthday", "dob": "birthday", "os": "operating_system",
    "operating system": "operating_system", "languages": "languages", "language": "languages",
}
_ALLOWED_LAST = set("""birthday age job profession occupation role editor ide language languages city hometown
country team company employer university college school laptop os shell browser timezone wife husband
partner girlfriend boyfriend son daughter dog cat pet email github color colour food drink movie song
band book sport game teacher manager boss project projects stack framework distro tongue phone""".split())
_ALLOWED_FIRST = {"favorite", "favourite", "fav", "preferred", "default", "usual", "home", "native",
                  "main", "primary", "first", "mother", "current"}
_STOP_VAL = re.compile(r"^(?:not|what|which|who|this|that|it|a secret|unknown|none|the same)\b", I)


def normalize_key(raw: str) -> str:
    k = re.sub(r"[^\w\s:]", " ", (raw or "").lower())
    k = re.sub(r"\b(?:the|a|an|my|current)\b", " ", k)
    k = " ".join(k.split())
    k = _SYNONYMS.get(k, k)
    parts = k.split()
    if parts and parts[0] in ("favourite", "fav"):
        k = " ".join(["favorite"] + parts[1:])
    k = _SYNONYMS.get(k, k)
    return k.replace(" ", "_")


def _clean_value(v: str, max_words: int = 6) -> str | None:
    v = re.split(r"[.!?;]|,\s| and (?:i|my|you|what|please)\b| but | because ", v.strip(), maxsplit=1)[0]
    v = v.strip(" \"'.,").strip()
    v = re.sub(r"\s+(?:ho|hai|hun|hoon|chha|cha|xa|haina)$", "", v, flags=I)
    if not v or _STOP_VAL.match(v) or len(v.split()) > max_words or len(v) > 60:
        return None
    return v


# --- regex capture (zero tokens) ---
_NAME = r"(?P<v>[^\W\d_][\w'-]*(?: [^\W\d_][\w'-]*){0,2})"
_PLACE = r"(?P<v>[^\W\d_][\w'.-]*(?: [^\W\d_][\w'.-]*){0,3})"
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("name", re.compile(r"\b(?:my name is|my name's|call me|you can call me|i am called|i'm called)\s+" + _NAME + r"(?=\s*(?:$|[,.!;]| and\b| but\b| from\b))", I)),
    ("name", re.compile(r"\b(?:mero|mera) (?:naam|nam|name) " + _NAME + r" (?:ho|hai|hain)\b", I)),
    ("name", re.compile(r"(?:मेरो|मेरा) नाम (?P<v>\S+(?: \S+)?) (?:हो|है)")),
    ("home_city", re.compile(r"\bi (?:live|stay|am living|'m living|am staying|'m staying|am based|'m based) in\s+" + _PLACE, I)),
    ("home_city", re.compile(r"\b(?:ma|main|mai) " + _PLACE + r" (?:ma|mein|me) (?:baschu|basxu|baschhu|bascha|rehta|rehti|rahta|rahti)\b", I)),
    ("home_city", re.compile(r"म (?P<v>\S+(?: \S+)?) मा बस्छु|मैं (?P<v2>\S+(?: \S+)?) में रहता|मैं (?P<v3>\S+(?: \S+)?) में रहती")),
    ("hometown", re.compile(r"\bi(?: am|'m) (?:originally )?from\s+" + _PLACE, I)),
    ("hometown", re.compile(r"\b(?:ma|main|mai) " + _PLACE + r" (?:bata|se) (?:ho|hun|hoon|hu)\b", I)),
    ("employer", re.compile(r"\bi work (?:at|for)\s+(?P<v>.+)", I)),
    ("works_on", re.compile(r"\bi(?:'m| am)? (?:work|working) on\s+(?P<v>.+)", I)),
    ("job", re.compile(r"\bi work as (?:an? )?(?P<v>.+)", I)),
    ("study", re.compile(r"\bi stud(?:y|ying) (?:at|in)\s+(?P<v>.+)", I)),
    ("languages", re.compile(r"\bi (?:can )?speak\s+(?P<v>.+)", I)),
]
_LIKE = re.compile(r"\bi (?:really |also )?(?P<verb>prefer|like|love|enjoy|hate|dislike|can't stand)\s+(?P<v>.+)", I)
_PREFER_FOR = re.compile(r"\bi (?:prefer|use|like) (?P<v>.+?) for (?P<k>[\w ]{2,30})$", I)
_MY_X = re.compile(r"\bmy (?P<k>(?:[a-z]+ ){0,3}?[a-z]+) (?:is|are|=|'s) (?P<v>.+)", I)
_QUESTION = re.compile(r"^\s*(?:what|who|where|when|which|how|why|do|does|did|is|are|can|could|should|would|will)\b|\?\s*$", I)


def capture(text: str) -> list[tuple[str, str]]:
    """(key, value) facts stated in text, by regex only. Questions are ignored."""
    t = " ".join((text or "").split())
    if not t or len(t) > 300 or _QUESTION.search(t):
        return []
    facts: dict[str, str] = {}
    for key, rx in _PATTERNS:
        m = rx.search(t)
        if not m:
            continue
        raw = next((g for g in m.groups() if g), "")
        v = _clean_value(raw, 3 if key == "name" else 6)
        if v and key not in facts:
            facts[key] = v
    if m := _PREFER_FOR.search(t):
        v = _clean_value(m.group("v"))
        if v:
            facts[f"prefers_for_{normalize_key(m.group('k'))}"] = v
    elif m := _LIKE.search(t):
        v = _clean_value(m.group("v"), 5)
        verb = m.group("verb").lower()
        if v and not re.match(r"(?:to |it|that|this|you)\b", v, I):
            verb = {"enjoy": "likes", "dislike": "dislikes", "can't stand": "hates", "prefer": "prefers"}.get(verb, verb + "s")
            facts[f"likes_{normalize_key(v)[:40]}"] = f"{verb} {v}"
    for m in _MY_X.finditer(t):
        raw_k = m.group("k").lower()
        words = raw_k.split()
        if raw_k in ("name",) or not (words[-1] in _ALLOWED_LAST or words[0] in _ALLOWED_FIRST):
            continue
        v = _clean_value(m.group("v"))
        if v:
            facts.setdefault(normalize_key(raw_k), v)
    return [(k, v) for k, v in facts.items() if k and not SECRET.search(k) and not SECRET.search(v)]


def save(key: str, value: str, source: str = "regex") -> bool:
    key = normalize_key(key) if not key.startswith(("likes_", "prefers_for_")) else key
    if not key or not value or SECRET.search(key) or SECRET.search(value):
        return False
    changed = store.profile_set(key, value.strip()[:120], source)
    prune()
    return changed


def capture_and_save(text: str) -> list[tuple[str, str]]:
    """Regex-capture facts from a user turn and store them (replace). Never raises."""
    try:
        facts = capture(text)
        for k, v in facts:
            save(k, v, "regex")
        return facts
    except Exception as e:
        log.warning("profile capture failed: %s", e)
        return []


# --- ranking, decay, prune ---
def importance(f: dict, now: float | None = None) -> float:
    now = now or time.time()
    age_days = max(0.0, (now - (f.get("last_used") or f.get("updated") or now)) / 86400)
    return (1.0 + math.log1p(f.get("hits") or 0)) * math.exp(-age_days / config.PROFILE_DECAY_DAYS)


def prune(max_facts: int | None = None) -> int:
    max_facts = max_facts or config.PROFILE_MAX
    facts = store.profile_all()
    if len(facts) <= max_facts:
        return 0
    now = time.time()
    victims = sorted((f for f in facts if f["key"] not in PROTECTED), key=lambda f: importance(f, now))
    n = len(facts) - max_facts
    for f in victims[:n]:
        store.profile_delete(f["key"])
    return min(n, len(victims))


# --- injection gate ---
_PERSONAL = re.compile(r"\b(?:my|me|i|i'm|i've|i'd|mine|myself|again|usual|usually|favou?rite|last time|"
                       r"yesterday|remember|as always|like before|prefer|mero|mera|meri|mujhe|malai|hamro)\b|"
                       r"मेरो|मेरा|मेरी|मुझे|मलाई|हाम्रो", I)
_ABOUT_ME = re.compile(r"about me|who am i|my profile|know me|ma ko hu|म को हुँ|मैं कौन", I)
_HINTS = {  # query words -> fact keys they make relevant
    "home_city": ("where", "live", "city", "home", "weather", "local", "near", "here", "time", "basch"),
    "name": ("name", "call", "who", "naam"),
    "languages": ("speak", "language", "nepali", "hindi", "english", "translate", "bhasa"),
    "favorite_editor": ("editor", "ide", "code", "vs", "vim", "open"),
    "job": ("job", "work", "career", "office"),
    "employer": ("work", "office", "company", "job"),
    "works_on": ("project", "work", "code", "repo"),
    "hometown": ("from", "hometown", "born", "where"),
}


def is_personal(text: str) -> bool:
    return bool(_PERSONAL.search(text or "") or _ABOUT_ME.search(text or ""))


_STOPW = set("""the and is are am was what who how why when which do does did you your me my mine it its this that
for with from like near about to of in on at be can could would will tell know just or but not so very much
some any have has had please there here""".split())


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-zऀ-ॿ]{2,}", (text or "").lower())) - _STOPW


def relevant(text: str, limit: int | None = None) -> list[dict]:
    """Top facts for text by relevance x recency x hits; [] when the turn isn't personal."""
    limit = limit or config.PROFILE_INJECT_MAX
    if not is_personal(text):
        return []
    facts = store.profile_all()
    if not facts:
        return []
    q = _words(text)
    about_me = bool(_ABOUT_ME.search(text))
    now = time.time()
    scored = []
    for f in facts:
        kw = set(f["key"].replace("likes_", "").replace("prefers_for_", "").split("_"))
        rel = len(q & (kw | _words(f["value"])))
        rel += sum(1 for h in _HINTS.get(f["key"], ()) if any(w.startswith(h) for w in q))
        if rel == 0 and about_me:
            rel = 0.5
        if rel > 0:
            scored.append((rel * importance(f, now), f))
    scored.sort(key=lambda x: -x[0])
    return [f for _, f in scored[:limit]]


_RENDER = {"name": "name {v}", "home_city": "lives in {v}", "hometown": "from {v}",
           "languages": "speaks {v}", "employer": "works at {v}", "works_on": "works on {v}",
           "job": "works as {v}", "study": "studies at {v}", "mother_tongue": "mother tongue {v}"}


def render_fact(f: dict) -> str:
    k, v = f["key"], f["value"]
    if k in _RENDER:
        return _RENDER[k].format(v=v)
    if k.startswith("likes_"):
        return v
    if k.startswith("prefers_for_"):
        return f"prefers {v} for {k[len('prefers_for_'):].replace('_', ' ')}"
    return f"{k.replace('_', ' ')}: {v}"


def context_line(text: str) -> str:
    """'User: lives in Nepalgunj; prefers VS Code.' (<= PROFILE_INJECT_MAX_CHARS) or ''."""
    facts = relevant(text)
    if not facts:
        return ""
    line = "User: "
    used: list[str] = []
    for f in facts:
        part = render_fact(f)
        if len(line) + len(part) + 2 > config.PROFILE_INJECT_MAX_CHARS:
            break
        line += ("; " if used else "") + part
        used.append(f["key"])
    if not used:
        return ""
    store.profile_touch(used)
    tokens = estimate_tokens(line)
    try:
        day = datetime.now().strftime("%Y-%m-%d")
        prev = int(store.kv_get(f"profile_inject_tokens:{day}", "0") or 0)
        store.kv_set(f"profile_inject_tokens:{day}", str(prev + tokens))
    except Exception as e:
        log.debug("inject count failed: %s", e)
    log.info("profile injected %d facts (~%d tokens)", len(used), tokens)
    return line + "."


def estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / 4))


# --- listing / deleting (tools) ---
def describe(limit: int = 12) -> str:
    facts = sorted(store.profile_all(), key=lambda f: -importance(f))[:limit]
    if not facts:
        return "I don't know anything about you yet. Tell me things like 'my name is ...' or 'I live in ...'."
    return "Here's what I know about you: " + "; ".join(render_fact(f) for f in facts) + "."


def find_key(phrase: str) -> str | None:
    """Best profile key for a phrase like 'I live in Pokhara' / 'my favourite editor' / 'editor'."""
    facts = store.profile_all()
    if not facts:
        return None
    if cap := capture(phrase):
        keys = {f["key"] for f in facts}
        for k, _ in cap:
            if k in keys:
                return k
    p = re.sub(r"^(?:that )?(?:i|my)\s+", "", (phrase or "").lower().strip())
    nk = normalize_key(p)
    keys = [f["key"] for f in facts]
    if nk in keys:
        return nk
    q = _words(p)
    best, score = None, 0
    for f in facts:
        s = len(q & (set(f["key"].split("_")) | _words(f["value"])))
        s += sum(1 for h in _HINTS.get(f["key"], ()) if any(w.startswith(h) for w in q))
        if s > score:
            best, score = f["key"], s
    return best


def home_place() -> str:
    """Learned home city, else config.HOME_PLACE (default place for weather)."""
    try:
        return store.profile_get("home_city") or config.HOME_PLACE
    except Exception:
        return config.HOME_PLACE


def user_name() -> str:
    try:
        return store.profile_get("name") or ""
    except Exception:
        return ""


# --- one LLM extraction per session end ---
EXTRACT_PROMPT = ("Extract durable facts about the USER (name, home city, languages, job, projects, tools, "
                  "preferences) from this conversation summary. Only facts the user stated about themselves; "
                  "no secrets, no temporary states. Keys: short snake_case (e.g. home_city, favorite_editor). "
                  "Return an empty list if none.")


def extract_llm(text: str) -> list[tuple[str, str]]:
    """One fast-tier structured call -> saved facts. Never raises."""
    if not config.PROFILE_LLM_EXTRACT or not (text or "").strip():
        return []
    from pydantic import BaseModel, Field

    from jarvis.core import llm

    class Fact(BaseModel):
        key: str = Field(description="snake_case fact name")
        value: str = Field(description="short value, a few words")

    class Facts(BaseModel):
        facts: list[Fact] = Field(description="at most 6 facts")

    try:
        out = llm.structured([{"role": "system", "content": EXTRACT_PROMPT},
                              {"role": "user", "content": text[:800]}], Facts, tier="fast",
                             purpose="profile_extract", max_tokens=config.PROFILE_EXTRACT_MAX_TOKENS,
                             priority="background")
    except Exception as e:
        log.info("profile extraction skipped: %s", e)
        return []
    saved = []
    for f in (out.facts or [])[:6]:
        v = _clean_value(f.value, 8)
        if v and save(f.key, v, "llm"):
            saved.append((normalize_key(f.key), v))
    return saved
