"""Zero-token fast path: high-confidence regex intents that call one tool directly and answer
from a template, with no LLM call. Anything not matched exactly returns None (normal LLM path).

Intents: local/world time, weather, remember <x>, recall all/last, open <app or site>.
English plus common romanized/Devanagari Hindi and Nepali. Disable with config.FASTPATH=False.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

from jarvis.core import config, safety, store

log = logging.getLogger("jarvis.fastpath")

I = re.I


@dataclass
class Intent:
    name: str  # time | weather | remember | recall | open
    tool: str
    group: str
    args: dict = field(default_factory=dict)
    label: str = ""  # display name (app/site/place)


@dataclass
class FastResult:
    answer: str
    intent: Intent
    ok: bool
    latency_ms: int


# --- normalisation ---
_LEAD = re.compile(r"^\s*(?:(?:hey|hi|ok|okay|yo)\s+)?(?:jarvis\b[\s,!.:]*)?(?:please\s+)?"
                   r"(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?)?", I)
_TRAIL = re.compile(r"(?:[\s,]+(?:please|jarvis))*[\s?.!।॥]*$", I)


def normalize(text: str) -> str:
    t = " ".join((text or "").split())
    t = _LEAD.sub("", t, count=1)
    return _TRAIL.sub("", t).strip(" ,")


def _rx(*alts: str) -> list[re.Pattern]:
    return [re.compile(a, I) for a in alts]


# --- time ---
TIME_LOCAL = _rx(
    r"(?:tell me |what(?:'s| is) )?(?:the )?(?:current |local )?time(?: (?:now|right now|is it))?",
    r"what time is it(?: now| right now)?",
    r"what(?:'s| is) (?:the |today'?s )?date(?: today)?",
    r"(?:abhi |aba |ahile )?(?:kitne|kitna) baje(?: hain| hai| he)?",
    r"(?:ahile |aba )?kati bajyo(?: ho)?", r"(?:samay|time) kya (?:hua|hai)(?: abhi)?",
    r"time kati bhayo", r"(?:अहिले )?कति बज्यो(?: ?हो)?", r"(?:अभी )?कितने बजे (?:हैं|है)",
    r"समय क्या (?:हुआ|है)", r"के समय भयो",
)
TIME_PLACE = _rx(
    r"(?:tell me |what(?:'s| is) )?(?:the )?(?:current |local )?time (?:right now |now )?(?:in|at|of) (?P<place>.+)",
    r"what time is it (?:now |right now )?(?:in|at) (?P<place>.+)",
    r"(?P<place>.+?) (?:ma|mein|me|मा|में) (?:abhi |ahile )?(?:kati bajyo|kitne baje(?: hain| hai)?|"
    r"कति बज्यो|कितने बजे (?:हैं|है)|time kya hai)",
)

# --- weather ---
_PRE = r"(?:(?:tell me|show me|check|get|give me) )?(?:what(?:'s| is) |how(?:'s| is) )?(?:the )?(?:current |today'?s |todays )?"
_WHEN = r"(?: (?P<when>today|now|right now|tomorrow|this week|next 3 days|for the next 3 days|outside))?"
WEATHER = _rx(
    _PRE + r"weather(?: (?:like|report|update|forecast|today|now|outside))*"
           r"(?: (?P<prep>in|of|at|for|on) (?P<place>.+?))?" + _WHEN,
    _PRE + r"forecast(?: (?:in|of|at|for) (?P<place>.+?))?" + _WHEN,
    _PRE + r"temperature(?: (?:outside|today|now))?(?: (?:in|of|at) (?P<place>.+?))?" + _WHEN,
    r"(?:will|is) it (?:going to )?rain(?: (?P<when>today|tomorrow))?(?: in (?P<place>.+?))?",
    r"(?:(?:aaj|aaja|today)(?: ko| ka)? |(?P<place>.+?) (?:ko|ka|mein|me|ma) )?(?:mausam|weather)"
    r"(?: (?:kasto|kaisa|kesa|kesto) (?:cha|xa|chha|hai|he)| kya hai| batao| bata)?",
    r"(?:आज(?:को| का)? |(?P<place>.+?) (?:को|का|मा|में) )?मौसम(?: (?:कस्तो छ|कैसा है|क्या है|बताओ))?",
    r"(?:आज |(?P<when>भोलि) )?पानी पर्छ(?: कि)?", r"(?:aaj |(?P<when>kal) )?barsat hogi(?: kya)?",
)
_HOME_WORDS = {"here", "home", "my area", "my city", "my location", "my place", "outside", "today"}
_BAD_PLACE_START = {"my", "your", "our", "his", "her", "their", "this", "that", "it", "me", "us",
                    "general", "bed", "morning", "evening", "night", "office", "work", "a", "an",
                    "tell", "show", "give", "get", "what", "how"}

# --- memory ---
REMEMBER = _rx(
    r"(?:remember|memori[sz]e|note down|jot down|make a note(?: of)?|take a note(?: of)?|"
    r"save (?:a |this )?note)(?: that)?\s*[:,-]?\s+(?P<text>.+)",
    r"(?:yaad|yad) (?:rakh|rakho|rakhna|rakhiye|rakhnu)(?: ki)?\s*[:,-]?\s+(?P<text>.+)",
    r"(?P<text>.+?) (?:yaad|yad) (?:rakh|rakho|rakhna|rakhiye|rakhnu|gara|garnu|rakha)",
    r"(?P<text>.+?) samjhi (?:rakha|rakh|rakhnu)",
    r"याद (?:रखो|रखना|राख)\s*[:,-]?\s+(?P<text>.+)",
    r"(?P<text>.+?) (?:याद (?:रख|रखो|रखना|राख|राख्नु)|सम्झि ?(?:राख|राख्नु|राखे))",
)
_CHATTY = re.compile(r"^(?:when|what|how|why|who|where|whether|if|me|us|you|him|her|them|it|this|that|"
                     r"the time|that time|those|back|anything|everything|down|this down)\b", I)
RECALL_LAST = _rx(
    r"what (?:was|is) the (?:last|latest|most recent) (?:thing|note|one)(?: (?:that )?i (?:told|asked) you"
    r"(?: to remember)?)?",
    r"what did i (?:last )?(?:tell|ask) you to remember last(?: time)?",
    r"what did i last (?:tell|ask) you to remember",
    r"(?:what(?:'s| is| was) )?(?:my |the )?(?:last|latest) (?:note|reminder|memory)",
    r"recall (?:the |my )?last(?: one| note| thing)?",
    r"आखिरी (?:बात|चीज़|चीज) क्या (?:थी|याद है)", r"अन्तिम कुरा के (?:थियो|हो)",
)
RECALL_ALL = _rx(
    r"what (?:do|did|else do) you remember(?: so far| for me)?",
    r"what (?:all )?(?:did|have) i (?:told|tell|asked|ask) you to remember(?: so far)?",
    r"what are (?:my|the|your) notes", r"(?:show|list|read|tell)(?: me)? (?:all )?(?:my |the )?notes",
    r"recall(?: all| everything)?(?: (?:my )?notes)?", r"tell me what you remember",
    r"what all do you remember", r"do you remember anything",
    r"(?:tumhe |tumhein |tapai lai |timilai )?(?:kya|ke) (?:yaad|yad) (?:hai|cha|xa|chha)",
    r"(?:तुम्हें |तिमीलाई |तपाईंलाई )?(?:क्या|के) याद (?:है|छ)",
)

# --- open ---
OPEN = _rx(
    r"(?P<verb>open|launch|start|run|fire up|bring up|go to)(?: up)? (?:the |my )?(?P<target>.+?)"
    r"(?: (?:app|application|for me))?",
    r"(?P<target>.+?) (?P<verb>kholo|khol|kholdo|khola|kholnu|kholdeu|chalao|chala|खोलो|खोल|खोल्नु|खोलदेउ|खोल्देउ|चलाओ)",
)
_BAD_TARGET = re.compile(r"(?:\band\b|\bthen\b|,|\bnew\b|\btab\b|\bfile\b|\bfolder\b|\bdoor\b|\btests?\b|"
                         r"\bcommand\b|\bscript\b|^(?:a|an|it|this|that)\b)", I)


def _full(patterns: list[re.Pattern], text: str) -> re.Match | None:
    for p in patterns:
        if m := p.fullmatch(text):
            return m
    return None


_WHEN_TAIL = re.compile(r"(?:\s+(?:today|tonight|now|right now|tomorrow|this week|this weekend|"
                        r"next 3 days|aaja?|aaj|bholi|bhol[ie]?|kal|आज|भोलि|कल))+$", I)


def _place(raw: str | None) -> str | None:
    """'' for home/none, the place for a plausible name, None to reject (fall through)."""
    if raw is None:
        return ""
    p = _WHEN_TAIL.sub("", raw.strip(" ,?.!")).strip(" ,")  # "Pokhara tomorrow" -> "Pokhara"
    if p.lower() in _HOME_WORDS:
        return ""
    words = p.split()
    if not 1 <= len(words) <= 4 or len(p) > 40 or words[0].lower() in _BAD_PLACE_START:
        return None
    if re.search(r"\b(?:and|then|or)\b|\d", p, I) or not re.fullmatch(r"[^\W\d_][\w .,'-]*", p):
        return None
    return p


def _days(m: re.Match, text: str) -> int:
    when = (m.groupdict().get("when") or "").lower()
    low = text.lower()
    if "forecast" in low or "week" in when or "3 days" in when:
        return 3
    if when in ("tomorrow", "kal", "भोलि") or re.search(r"\b(?:tomorrow|bholi|bhole)\b|भोलि", low):
        return 2
    return 1


def match(text: str) -> Intent | None:
    """The single high-confidence intent for text, or None."""
    t = normalize(text)
    if not t or len(t) > 200:
        return None
    if m := _full(TIME_LOCAL, t):
        return Intent("time", "get_time", "general")
    if m := _full(TIME_PLACE, t):
        place = _place(m.group("place"))
        if place:
            return Intent("time", "get_time", "general", {"place": place}, place)
        return None
    if m := _full(WEATHER, t):
        place = _place(m.groupdict().get("place"))
        if place is None or (m.groupdict().get("prep") in ("for", "on") and place.islower()
                             and place.endswith("ing")):  # "weather for running"
            return None
        return Intent("weather", "weather", "weather", {"place": place, "days": _days(m, t)}, place)
    if _full(RECALL_LAST, t):
        return Intent("recall", "recall", "memory", {"which": "last"})
    if _full(RECALL_ALL, t):
        return Intent("recall", "recall", "memory", {"which": "all"})
    if m := _full(REMEMBER, t):
        note = m.group("text").strip(" ,:-")
        if not note or text.rstrip().endswith("?") or _CHATTY.match(note):
            return None
        return Intent("remember", "remember", "memory", {"text": note}, note)
    if m := _full(OPEN, t):
        return _open_intent(m.group("target").strip(" ,"), m.group("verb").lower())
    return None


def _open_intent(target: str, verb: str) -> Intent | None:
    if not target or len(target.split()) > 4 or _BAD_TARGET.search(target):
        return None
    from jarvis.tools.general import _apps, open_url  # lazy: desktop index only when needed

    url = open_url.resolve(target)
    if url:
        return Intent("open", "open_url", "browser", {"target": target}, target)
    if verb == "go to":
        return None
    entry, score = _apps.find_app(target)
    need = 100 if verb in ("start", "run") else _apps.FASTPATH_MIN_SCORE
    if entry is None or score < need:
        return None
    return Intent("open", "open_app", "apps", {"name": target}, entry["name"])


# --- templates ---
_T = {
    "remember": {"en": "Okay, I'll remember: {x}.", "hi": "ठीक है, मैं याद रखूँगा: {x}।",
                 "ne": "हुन्छ, म सम्झिराख्छु: {x}।"},
    "open": {"en": "Opening {x}.", "hi": "{x} खोल रहा हूँ।", "ne": "{x} खोल्दैछु।"},
    "open_fail": {"en": "Sorry, I couldn't open {x}.", "hi": "माफ़ कीजिए, {x} नहीं खुल सका।",
                  "ne": "माफ गर्नुहोस्, {x} खोल्न सकिनँ।"},
    "no_place": {"en": "Sorry, I couldn't find a place called {x}.", "hi": "माफ़ कीजिए, {x} नाम की जगह नहीं मिली।",
                 "ne": "माफ गर्नुहोस्, {x} नामको ठाउँ भेटिएन।"},
    "failed": {"en": "Sorry, that didn't work: {x}", "hi": "माफ़ कीजिए, यह नहीं हुआ: {x}",
               "ne": "माफ गर्नुहोस्, भएन: {x}"},
}
_TIME_OUT = re.compile(r"^(?:(?P<where>.+?): )?(?P<day>\w+), (?P<date>\d+ \w+ \d+), (?P<hm>\d\d:\d\d)")


def _say(key: str, lang: str, x: str) -> str:
    t = _T[key]
    return t.get(lang, t["en"]).format(x=x)


def render(intent: Intent, ok: bool, output: str, lang: str) -> str:
    out = output.strip()
    err = (not ok) or out.lower().startswith("error")
    if intent.name in ("time", "weather") and err and "couldn't find a place" in out:
        return _say("no_place", lang, intent.label)
    if err:
        if intent.name == "open":
            return _say("open_fail", lang, intent.label)
        return _say("failed", lang, re.sub(r"^error:\s*", "", out))
    if intent.name == "time" and (m := _TIME_OUT.match(out)):
        where, hm = m.group("where"), m.group("hm")
        if lang == "hi":
            return f"{where + ' में ' if where else ''}अभी {hm} बजे हैं, {m.group('day')}, {m.group('date')}।"
        if lang == "ne":
            return f"{where + 'मा ' if where else ''}अहिले {hm} बज्यो, {m.group('day')}, {m.group('date')}।"
        return f"It's {hm} on {m.group('day')}, {m.group('date')}{' in ' + where if where else ''}."
    if intent.name == "remember":
        return _say("remember", lang, intent.label)
    if intent.name == "open":
        return _say("open", lang, intent.label)
    return out  # weather / recall: the tool output is already a sentence


def try_answer(text: str, lang: str | None = None, confirm=None) -> FastResult | None:
    """Run the matched tool and return a templated answer, or None to use the LLM path."""
    if not config.FASTPATH:
        return None
    t0 = time.monotonic()
    try:
        intent = match(text)
    except Exception as e:  # a fast-path bug must never break a turn
        log.warning("fastpath match failed: %s", e)
        return None
    if intent is None:
        return None
    if lang is None:
        from jarvis.core.planner import detect_lang
        lang = detect_lang(text)
    res = safety.execute(intent.tool, intent.args, confirm=confirm)
    if intent.name in ("time", "weather") and "couldn't find a place" in (res.output or ""):
        return None  # unknown place: let the LLM path try (it can fix spelling)
    answer = render(intent, res.ok, res.output, lang or "en")
    ms = int((time.monotonic() - t0) * 1000)
    try:
        store.log_routing(text, [intent.group], "fastpath", ms)
    except Exception as e:
        log.warning("could not log routing: %s", e)
    return FastResult(answer, intent, res.ok, ms)
