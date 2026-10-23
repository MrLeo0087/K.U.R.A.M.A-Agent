"""Zero-token fast path: high-confidence regex intents that call one tool directly and answer
from a template, with no LLM call. Anything not matched exactly returns None (normal LLM path).

Intents: local/world time, weather, remember <x>, recall all/last, open <app or site>, and (P5b)
volume, mute, mic mute, media play/pause/next/previous, brightness, screenshot, lock screen.
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
    name: str  # time | weather | remember | recall | open | volume | brightness | mute | mic | media | screenshot | lock
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
    r"(?:(?:tell me|give me|provide|show me|check|get|find|say) |what(?:'s| is) )?(?:the )?(?:current |local )?"
    r"time (?:right now |now )?(?:in|at|of|for) (?P<place>.+)",
    r"what time is it (?:now |right now )?(?:in|at) (?P<place>.+)",
    r"(?P<place>.+?) (?:ma|mein|me|मा|में) (?:abhi |ahile )?(?:kati bajyo|kitne baje(?: hain| hai)?|"
    r"कति बज्यो|कितने बजे (?:हैं|है)|time kya hai)",
)

# --- weather ---
_PRE = r"(?:(?:tell me|show me|check|get|give me|provide|find|say) )?(?:what(?:'s| is) |how(?:'s| is) )?(?:the )?(?:current |today'?s |todays )?"
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


# --- desktop controls (P5b) ---
_N = r"(?P<n>\d{1,3})"
_PCT = r"(?: ?%| percent| pratishat| प्रतिशत)?"
_BY = r"(?: by (?P<n>\d{1,2})(?: ?%| percent)?)?"
_UP_HI = r"(?:badhao|badha do|badhau|badhaunu|barhao|बढ़ाओ|बढाओ|बढ़ा दो|बढाउ|बढाऊ|बढाइदेउ)"
_DOWN_HI = r"(?:kam karo|kam kar do|ghatao|ghatau|ghataunu|कम करो|कम कर दो|घटाओ|घटाउ|घटाऊ|घटाइदेउ)"
_DO_HI = r"(?:karo|kar do|gara|garnu|garideu|करो|कर दो|गर|गर्नु|गरिदेउ)"
_VOL = r"(?:the )?(?:volume|sound)"
_VOL_HI = r"(?:awaz|awaaz|awaj|awaaj|volume|आवाज़|आवाज|भोल्युम)"
_BRI = r"(?:the )?(?:screen )?brightness"
_BRI_HI = r"(?:brightness|ब्राइटनेस|चमक)"
LEVELS = {  # name -> (tool, group, {action: patterns})
    "volume": ("volume", "audio", {
        "set": _rx(r"(?:set|change|put|turn) " + _VOL + r"(?: level)? (?:to|at) " + _N + _PCT,
                   r"(?:volume|sound)(?: level)? (?:to |at )?" + _N + _PCT,
                   _VOL_HI + " " + _N + _PCT + " " + _DO_HI),
        "up": _rx(r"(?:turn|bump|crank) up " + _VOL + _BY, r"(?:turn|bump|crank) " + _VOL + " up" + _BY,
                  r"(?:increase|raise) " + _VOL + _BY, r"(?:volume|sound) up" + _BY, r"(?:make it )?louder",
                  _VOL_HI + " " + _UP_HI),
        "down": _rx(r"turn down " + _VOL + _BY, r"turn " + _VOL + " down" + _BY,
                    r"(?:decrease|lower|reduce) " + _VOL + _BY, r"(?:volume|sound) down" + _BY,
                    r"(?:make it )?(?:quieter|softer)", _VOL_HI + " " + _DOWN_HI),
        "get": _rx(r"what(?:'s| is) the (?:current )?volume(?: level)?(?: now)?", r"(?:current )?volume level"),
    }),
    "brightness": ("brightness", "display", {
        "set": _rx(r"(?:set|change|put|turn) " + _BRI + r"(?: level)? (?:to|at) " + _N + _PCT,
                   r"(?:screen )?brightness(?: level)? (?:to |at )?" + _N + _PCT,
                   _BRI_HI + " " + _N + _PCT + " " + _DO_HI),
        "up": _rx(r"(?:turn|bump) up " + _BRI + _BY, r"(?:turn|bump) " + _BRI + " up" + _BY,
                  r"(?:increase|raise) " + _BRI + _BY, r"(?:screen )?brightness up" + _BY,
                  r"(?:make (?:the |my )?screen brighter|brighten (?:the |my )?screen)", _BRI_HI + " " + _UP_HI),
        "down": _rx(r"turn down " + _BRI + _BY, r"turn " + _BRI + " down" + _BY,
                    r"(?:decrease|lower|reduce) " + _BRI + _BY, r"(?:screen )?brightness down" + _BY,
                    r"(?:make (?:the |my )?screen dimmer|dim (?:the |my )?screen)", _BRI_HI + " " + _DOWN_HI),
        "get": _rx(r"what(?:'s| is) the (?:current |screen )?brightness(?: level)?(?: now)?"),
    }),
}
_MEDIA_OBJ = r"(?: (?:the |my )?(?:music|song|video|playback|track|player|media|it))?"
_SONG = r"(?:song|track|video)"
_SONG_HI = r"(?:gaana|gana|geet|song|track|गाना|गीत)"
SWITCHES = [  # (intent name, tool, group, args, patterns); first full match wins
    ("mic", "mic_mute", "audio", {"action": "mute"}, _rx(
        r"(?:mute|turn off|switch off|disable) (?:the |my )?(?:mic|microphone)", r"(?:mic|microphone) (?:off|mute)",
        r"(?:mic|माइक) (?:band karo|band kar do|बंद करो|बन्द गर|बन्द गरिदेउ)")),
    ("mic", "mic_mute", "audio", {"action": "unmute"}, _rx(
        r"(?:unmute|turn on|switch on|enable) (?:the |my )?(?:mic|microphone)", r"(?:mic|microphone) on",
        r"(?:mic|माइक) (?:chalu karo|on karo|चालू करो|खोल)")),
    ("mute", "mute_audio", "audio", {"action": "mute"}, _rx(
        r"mute(?: (?:the |my )?(?:sound|audio|volume|speakers?|computer|pc|laptop|everything))?",
        r"(?:awaz|awaaz|आवाज़|आवाज) (?:band karo|band kar do|बंद करो|बन्द गर|बन्द गरिदेउ)")),
    ("mute", "mute_audio", "audio", {"action": "unmute"}, _rx(
        r"unmute(?: (?:the |my )?(?:sound|audio|volume|speakers?|computer|pc|laptop|everything))?",
        r"(?:awaz|awaaz|आवाज़|आवाज) (?:chalu karo|wapas lao|चालू करो|फेरि चालू गर)")),
    ("media", "media_control", "media", {"action": "pause"}, _rx(
        r"pause" + _MEDIA_OBJ, r"stop (?:the |my )?(?:music|song|playback|video)",
        _SONG_HI + r" (?:roko|rok do|रोको|रोक दो|रोक|रोकिदेउ)")),
    ("media", "media_control", "media", {"action": "play"}, _rx(
        r"play", r"(?:resume|unpause)" + _MEDIA_OBJ, r"continue (?:playing|the (?:music|song|video))")),
    ("media", "media_control", "media", {"action": "next"}, _rx(
        r"(?:play |go to |skip to )?(?:the )?next " + _SONG, r"skip(?: this| the)? " + _SONG,
        r"(?:agla|agla wala|arko|aarko|अगला|अर्को) " + _SONG_HI)),
    ("media", "media_control", "media", {"action": "previous"}, _rx(
        r"(?:play |go to |go back to )?(?:the )?previous " + _SONG, r"go back (?:a|one) " + _SONG,
        r"(?:pichla|pichhla|aghillo|पिछला|अघिल्लो) " + _SONG_HI)),
    ("media", "media_control", "media", {"action": "status"}, _rx(
        r"what(?:'s| is) (?:playing|this song)(?: now| right now)?", r"what song is (?:this|playing)(?: now)?")),
    ("screenshot", "screenshot", "screen", {"mode": "window"}, _rx(
        r"(?:take|grab|capture) (?:a )?(?:screenshot|screen shot) of (?:this|the|my)(?: current| active)? window",
        r"(?:screenshot|screen shot) (?:of )?(?:this|the)(?: current| active)? window")),
    ("screenshot", "screenshot", "screen", {"mode": "full"}, _rx(
        r"(?:take|grab|capture) (?:a |the )?(?:screenshot|screen shot|screen capture)"
        r"(?: of (?:the |my )?(?:whole |entire |full )?screen)?(?: now)?",
        r"screenshot(?: now)?", r"capture (?:the |my )?(?:whole |entire |full )?screen",
        r"(?:ek )?(?:screenshot|स्क्रीनशॉट|स्क्रिनसट) (?:lo|le lo|lelo|khicho|kheecho|kheech lo|liu|linu|"
        r"लो|ले लो|लेलो|खिचो|खिच्नु|लिनु|लेउ)")),
    ("lock", "lock_screen", "power", {}, _rx(
        r"lock (?:the |my |this )?(?:screen|computer|pc|laptop|desktop|system|machine)(?: now)?",
        r"(?:screen|computer|laptop|स्क्रीन|स्क्रिन|कम्प्युटर|कंप्यूटर) (?:lock|लॉक|लक) " + _DO_HI)),
]


def _system_intent(t: str) -> Intent | None:
    for name, (tool, group, actions) in LEVELS.items():
        for action, pats in actions.items():
            if m := _full(pats, t):
                n = m.groupdict().get("n")
                args: dict = {"action": action}
                if action == "set":
                    if n is None or not 0 <= int(n) <= 100:
                        return None  # "volume to 150": let the LLM ask
                    args["level"] = int(n)
                elif n is not None:
                    args["step"] = int(n)
                return Intent(name, tool, group, args, name)
    for name, tool, group, args, pats in SWITCHES:
        if _full(pats, t):
            return Intent(name, tool, group, dict(args), name)
    return None


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
        want_date = bool(re.search(r"\b(?:date|day|today)\b|गते|तारीख|बार", t, I))
        return Intent("time", "get_time", "general", {"_date": True} if want_date else {})
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
    if sysi := _system_intent(t):
        return sysi
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
    "volume": {"en": "Volume is at {x}%.", "hi": "आवाज़ {x}% पर है।", "ne": "भोल्युम {x}% मा छ।"},
    "brightness": {"en": "Brightness is at {x}%.", "hi": "ब्राइटनेस {x}% पर है।", "ne": "ब्राइटनेस {x}% मा छ।"},
    "muted": {"en": "Sound muted.", "hi": "आवाज़ बंद कर दी।", "ne": "आवाज बन्द गरें।"},
    "unmuted": {"en": "Sound is back on.", "hi": "आवाज़ चालू कर दी।", "ne": "आवाज फेरि चालू भयो।"},
    "mic_muted": {"en": "Microphone muted.", "hi": "माइक बंद कर दिया।", "ne": "माइक बन्द गरें।"},
    "mic_unmuted": {"en": "Microphone is on.", "hi": "माइक चालू कर दिया।", "ne": "माइक चालू गरें।"},
    "paused": {"en": "Paused.", "hi": "रोक दिया।", "ne": "रोकें।"},
    "playing": {"en": "Playing.", "hi": "चला रहा हूँ।", "ne": "बजाउँदैछु।"},
    "next": {"en": "Next track.", "hi": "अगला गाना।", "ne": "अर्को गीत।"},
    "previous": {"en": "Previous track.", "hi": "पिछला गाना।", "ne": "अघिल्लो गीत।"},
    "screenshot": {"en": "Screenshot saved in your Screenshots folder.",
                   "hi": "स्क्रीनशॉट Screenshots फ़ोल्डर में सेव हो गया।", "ne": "स्क्रिनसट Screenshots फोल्डरमा सेभ भयो।"},
    "lock": {"en": "Locking the screen.", "hi": "स्क्रीन लॉक कर रहा हूँ।", "ne": "स्क्रिन लक गर्दैछु।"},
}
_SYSTEM = {"volume", "brightness", "mute", "mic", "media", "screenshot", "lock"}


def _render_system(intent: Intent, out: str, lang: str) -> str:
    if intent.name in ("volume", "brightness"):
        m = re.search(r"(\d+)%", out)
        return _say(intent.name, lang, m.group(1)) if m else out
    if intent.name in ("mute", "mic"):
        key = "unmuted" if "unmuted" in out else "muted"
        return _say(key if intent.name == "mute" else "mic_" + key, lang, "")
    if intent.name == "media":
        action = intent.args.get("action")
        if action == "status":
            return out[:1].upper() + out[1:].rstrip(".") + "."
        return _say({"pause": "paused", "play": "playing"}.get(action, action), lang, "")
    return _say(intent.name, lang, "")  # screenshot / lock
_TIME_OUT = re.compile(r"^It's (?P<h12>\d+:\d\d) (?P<ampm>AM|PM) on (?P<day>\w+), (?P<date>\d+ \w+ \d+)"
                       r"(?: in (?P<where>.+?))?\.$")


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
        where, h12, ampm = m.group("where"), m.group("h12"), m.group("ampm")
        date_txt = f"{m.group('day')}, {m.group('date')}" if intent.args.get("_date") else ""
        if lang == "hi":
            return f"{where + ' में ' if where else ''}अभी {h12} बजे हैं{', ' + date_txt if date_txt else ''}।"
        if lang == "ne":
            return f"{where + 'मा ' if where else ''}अहिले {h12} बज्यो{', ' + date_txt if date_txt else ''}।"
        return f"It's {h12} {ampm}{' in ' + where if where else ''}{', ' + date_txt if date_txt else ''}."
    if intent.name in _SYSTEM:
        return _render_system(intent, out, lang)
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
    res = safety.execute(intent.tool, {k: v for k, v in intent.args.items() if not k.startswith("_")},
                          confirm=confirm)
    if intent.name in ("time", "weather") and "couldn't find a place" in (res.output or ""):
        return None  # unknown place: let the LLM path try (it can fix spelling)
    answer = render(intent, res.ok, res.output, lang or "en")
    ms = int((time.monotonic() - t0) * 1000)
    try:
        store.log_routing(text, [intent.group], "fastpath", ms)
    except Exception as e:
        log.warning("could not log routing: %s", e)
    return FastResult(answer, intent, res.ok, ms)
