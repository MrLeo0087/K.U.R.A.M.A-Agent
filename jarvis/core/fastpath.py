"""Zero-token fast path: high-confidence regex intents that call one tool directly and answer
from a template, with no LLM call. Anything not matched exactly returns None (normal LLM path).

Intents: local/world time, weather, remember <x>, recall all/last, open <app or site>, and (P5b)
volume, mute, mic mute, media play/pause/next/previous, brightness, screenshot, lock screen, and (P7)
daily digest, token usage, "what did we talk about yesterday", "what do you know about me" and
"my name is X" / "call me X" (acknowledged; the agent's regex capture stores the fact).
English plus common romanized/Devanagari Hindi and Nepali. Disable with config.FASTPATH=False.
"""
from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from jarvis.core import config, safety, store
from jarvis.core import notes as notes_mod
from jarvis.core import study as study_mod

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
    workspace: list[str] = field(default_factory=list)  # results saved for the dashboard's Workspace card


# --- normalisation ---
def refresh_names() -> None:
    """(Re)build the patterns that strip the assistant's name (called again after a rename)."""
    global _NAMES, _LEAD, _TRAIL
    from jarvis.core import identity
    _NAMES = "|".join(map(re.escape, identity.names()))
    _LEAD = re.compile(r"^\s*(?:(?:hey|hi|ok|okay|yo|so|now|then|alright|well|um+|uh+|hmm+|and|also|actually|just|"
                       r"kindly)\b[\s,.!]*)*(?:(?:" + _NAMES + r")\b[\s,!.:]*)?(?:(?:now|so|okay|ok)\b[\s,]*)*"
                       r"(?:please\s+)?(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?(?:just\s+)?)?", I)
    _TRAIL = re.compile(r"(?:[\s,]+(?:please|" + _NAMES + r"))*[\s?.!।॥]*$", I)


refresh_names()


_DEVICE_TAIL = re.compile(r"\s+(?:of|in|from|for)\s+(?:my|the|this)\s+(?:laptop|computer|pc|system|display|"
                          r"screen|monitor|device)(?=[\s,?.!।]*$)", I)


def normalize(text: str) -> str:
    t = " ".join((text or "").split())
    for pat, rep in config.STT_FIXES.items():  # the same mishearing fixes as voice ("tone of" -> "turn off")
        t = re.sub(pat, rep, t, flags=I)
    t = _LEAD.sub("", t, count=1)
    t = _DEVICE_TAIL.sub("", t)  # "take the screenshot of my display" = "take the screenshot"
    return _TRAIL.sub("", t).strip(" ,")


def _rx(*alts: str) -> list[re.Pattern]:
    return [re.compile(a, I) for a in alts]


# --- time ---
_TQ = r"(?:(?:tell me|do you know|let me know|say|check|give me|any idea) )?"  # "can you tell me what is time right now"
TIME_LOCAL = _rx(
    _TQ + r"(?:what(?:'s| is) )?(?:the )?(?:current |local )?time(?: (?:now|right now|is it|it is))?(?: now| right now)?",
    _TQ + r"what time (?:is it|it is)(?: now| right now)?",
    r"what(?:'s| is) (?:the |today'?s )?date(?: today)?",
    r"(?:abhi |aba |ahile )?(?:kitne|kitna) baje(?: hain| hai| he)?",
    r"(?:ahile |aba )?kati bajyo(?: ho)?", r"(?:samay|time) kya (?:hua|hai)(?: abhi)?",
    r"time kati bhayo", r"(?:अहिले )?कति बज्यो(?: ?हो)?", r"(?:अभी )?कितने बजे (?:हैं|है)",
    r"समय क्या (?:हुआ|है)", r"के समय भयो",
)
TIME_PLACE = _rx(
    r"(?:(?:tell me|give me|provide|show me|check|get|find|say) |what(?:'s| is) )?(?:the )?(?:current |local )?"
    r"time (?:right now |now )?(?:in|at|of|for) (?P<place>.+)",
    _TQ + r"what time (?:is it|it is) (?:now |right now )?(?:in|at) (?P<place>.+)",
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
# --- "search X" means SHOW the results page (P7c); asking for the answer goes to the LLM + web tools ---
_ENG = r"(?P<eng>google|youtube|you tube|wikipedia|wiki)"
_HI_DO = r"(?: (?:gara|garnu|garnus|garideu|gardeu|karo|kar do|kijiye|करो|गर|गर्नु|गरिदेउ))?"
_HI_ON = r"(?: (?:ma|maa|pe|par|mein|me|मा|पर|में))?"
SEARCH = _rx(
    _ENG + _HI_ON + r" (?P<q>.+?) (?:search|khoj|सर्च|खोज)" + _HI_DO,
    r"(?P<q>.+?) " + _ENG + _HI_ON + r" (?:search|khoj|सर्च|खोज)" + _HI_DO,
    r"(?:search|look up|lookup)(?: (?:on |in )?" + _ENG + r")?(?: for| about)? (?P<q>.+?)"
    r"(?: (?:on|in|using|with) " + _ENG.replace("eng", "eng2") + r")?",
    r"(?P<eng>google) (?:for )?(?P<q>.+)",
)
_SEARCH_ANSWER = re.compile(
    r"\b(?:give me|tell me|let me know|what|who|whom|whose|when|where|why|how|which|results?|answers?|"
    r"summar\w*|explain|latest|score|batao|bhana)\b|बताओ|भन", I)
_SEARCH_LOCAL = re.compile(r"\b(?:my|files?|folders?|director(?:y|ies)|code|notes?|repo|project\d*|computer|"
                           r"laptop|pc|drive|clipboard|emails?|history|memory|downloads|desktop|documents)\b|"
                           r"\w\.[A-Za-z0-9]{1,6}\b|/", I)  # "main.py", paths: search the laptop, not Google
SEARCH_URLS = {"google": "https://www.google.com/search?q={q}",
               "youtube": "https://www.youtube.com/results?search_query={q}",
               "wikipedia": "https://en.wikipedia.org/w/index.php?search={q}"}
SEARCH_NAMES = {"google": "Google", "youtube": "YouTube", "wikipedia": "Wikipedia"}


# "give me a list of all files in project1 and tara folder", "what's in my downloads folder", "list the music folder"
_LISTDIR = _rx(
    r"(?:(?:give|show|tell|send)(?: me)? |list |get(?: me)? )?(?:a |the )?(?:full |complete )?(?:list(?:ing)? of )?(?:all )?"
    r"(?:the )?(?:files?|folders?|contents?|everything|items?)(?: and (?:files?|folders?))? (?:in|inside|of|from|under) "
    r"(?:the |my )?(?P<path>.+?)(?: folders?| directory| directories| drive)?",
    r"what(?:'s| is| are)(?: there)? (?:in|inside) (?:the |my )?(?P<path>.+?) (?:folders?|directory|drive)",
    r"list (?:the |my )?(?P<path>.+?) (?:folders?|directory|drive)(?:'s)?(?: contents| files)?")


def listdir_intent(t: str) -> Intent | None:
    m = _full(_LISTDIR, t)
    if not m:
        return None
    path = m.group("path").strip(" ,")
    if not path or len(path.split()) > 8 or re.search(r"\b(?:web|internet|google|youtube|news)\b", path, I):
        return None
    return Intent("listdir", "list_folder", "filesearch", {"path": path}, path)


def search_intent(t: str) -> Intent | None:
    if _SEARCH_ANSWER.search(t):
        return None  # they want the answer: LLM path with web_search / wikipedia
    m = _full(SEARCH, t)
    if not m:
        return None
    gd = m.groupdict()
    q = (gd.get("q") or "").strip(" ,.?!\"'")
    eng = (gd.get("eng") or gd.get("eng2") or "google").lower().replace("you tube", "youtube")
    eng = "wikipedia" if eng == "wiki" else eng
    if not q or len(q) > 120 or _SEARCH_LOCAL.search(q) or q.lower() in SEARCH_NAMES:
        return None
    from urllib.parse import quote_plus

    url = SEARCH_URLS[eng].format(q=quote_plus(q))
    return Intent("search", "open_url", "browser", {"target": url}, f"{SEARCH_NAMES[eng]}|{q}")


OPEN = _rx(
    r"(?P<verb>open|launch|start|run|fire up|bring up|go to)(?: up)? (?:the |my )?(?P<target>.+?)"
    r"(?: (?:app|application|for me))?",
    r"(?P<target>.+?) (?P<verb>kholo|khol|kholdo|khola|kholnu|kholdeu|chalao|chala|खोलो|खोल|खोल्नु|खोलदेउ|खोल्देउ|चलाओ)",
)
CLOSE = _rx(r"(?P<verb>close|quit|exit) (?:the |my )?(?P<target>.+?)(?: (?:app|application|window|windows))?")
_BAD_TARGET = re.compile(r"(?:\band\b|\bthen\b|,|\bnew\b|\btab\b|\bfile\b(?! manager)|\bfolder\b|\bdoor\b|\btests?\b|"
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
    ("find_phone", "find_my_phone", "system", {"phone": "iphone"}, _rx(
        r"(?:find|locate|where(?:'s| is)|track|ring) (?:my |the )?(?:lost |missing )?iphone(?: now)?",
        r"find my (?:phone|mobile) \(?iphone\)?")),
    ("find_phone", "find_my_phone", "system", {"phone": "android"}, _rx(
        r"(?:find|locate|track|ring) (?:my |the )?(?:lost |missing )?(?:phone|mobile|android|cell\s*phone)(?: now)?",
        r"where(?:'s| is) (?:my |the )?(?:phone|mobile|android|cell\s*phone)(?: now)?",
        r"(?:open |launch )?(?:google )?find my (?:device|phone|mobile|android)",
        r"(?:phone|mobile|मोबाइल|फोन) (?:kaha|kahan|khoj|कहाँ|कहां|खोज)(?:\s\w+)?")),
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
    ("theme", "set_theme", "display", {"mode": "light"}, _rx(
        r"(?:switch|change|turn|set|put|go)(?: (?:on|to|the|my|laptop|desktop|computer|theme|it|into|of))* (?:to |into )?"
        r"(?:the )?light (?:mode|theme)(?: now| please)?",
        r"(?:enable|use|activate) (?:the )?light (?:mode|theme)(?: now)?", r"light (?:mode|theme)(?: on| please| now)?",
        r"(?:make it|make the (?:screen|laptop|desktop)) light")),
    ("theme", "set_theme", "display", {"mode": "dark"}, _rx(
        r"(?:switch|change|turn|set|put|go)(?: (?:on|to|the|my|laptop|desktop|computer|theme|it|into|of))* (?:to |into )?"
        r"(?:the )?dark (?:mode|theme)(?: now| please)?",
        r"(?:enable|use|activate) (?:the )?dark (?:mode|theme)(?: now)?", r"dark (?:mode|theme)(?: on| please| now)?",
        r"(?:make it|make the (?:screen|laptop|desktop)) dark", r"night mode(?: on)?")),
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


# --- P9a desktop extras (DND, night light, wallpaper, battery, focus, YouTube) ---
_ONW = r"(?P<on>on|chalu karo|chalu kar do|on karo|on gara|chalu gara|चालू करो|चालू गर|अन गर)"
_OFFW = r"(?P<off>off|band karo|band kar do|off karo|off gara|banda gara|बंद करो|बन्द गर|अफ गर)"
_DND = r"(?:the )?(?:do not disturb|do-not-disturb|dnd|डु नट डिस्टर्ब)(?: mode)?"
_NL = r"(?:the )?(?:night light|night-light|nightlight|blue light filter|नाइट लाइट)"


def _onoff(obj: str) -> list[re.Pattern]:
    return _rx(r"(?:turn|switch|put) (?:(?P<on>on)|(?P<off>off)) " + obj + r"(?: now)?",
               r"(?:turn|switch) " + obj + r" (?:(?P<on>on)|(?P<off>off))(?: now)?",
               r"(?:(?P<on>enable|activate|start)|(?P<off>disable|deactivate|stop)) " + obj + r"(?: now)?",
               obj + r" (?:" + _ONW + "|" + _OFFW + ")")


DND_PATS, NL_PATS = _onoff(_DND), _onoff(_NL)
WALL_NEXT = _rx(r"(?:next|another|new|different) (?:desktop )?(?:wallpaper|background)",
                r"(?:change|switch|swap) (?:the |my )?(?:desktop )?(?:wallpaper|background)(?: image)?",
                r"(?:wallpaper|वालपेपर) (?:badlo|badal do|fera|ferdeu|बदलो|बदल दो|फेर|फेरिदेउ)")
WALL_RANDOM = _rx(r"(?:set |pick |give me )?(?:a )?random (?:desktop )?wallpaper",
                  r"shuffle (?:the |my )?wallpapers?")
BATTERY = _rx(r"(?:what(?:'s| is) (?:my |the )?|check (?:my |the )?|show (?:me )?(?:my |the )?)?"
              r"battery(?: status| level| percentage| percent| life| health)?(?: now)?",
              r"how much (?:battery|charge)(?: (?:is )?(?:left|remaining|do i have|have i got))?(?: now)?",
              r"is (?:my |the )?(?:laptop|battery|computer) charging",
              r"(?:battery|बैटरी|ब्याट्री) (?:kitni hai|kitna hai|kati cha|kati chha|कितनी है|कति छ|कति बाँकी छ)")
_MIN = r"(?: for (?P<n>\d{1,3}) ?(?:minutes?|mins?|min|m))?"
FOCUS_START = _rx(r"(?:start|begin|enable|turn on|activate)(?: a| the| my)? (?:focus(?: mode| session)?|pomodoro)" + _MIN,
                  r"(?:focus mode|pomodoro)(?: on)?" + _MIN, r"(?:i want to |let me |help me )?focus" + _MIN)
FOCUS_STOP = _rx(r"(?:stop|end|cancel|turn off|finish|disable)(?: the| my)? (?:focus(?: mode| session)?|pomodoro)",
                 r"(?:focus mode|pomodoro) off")
_YT = r"(?:youtube|you tube|यूट्यूब|युट्युब)"
_YT_DO = r"(?:play|bajao|chalao|chalau|laga do|lagao|बजाओ|चलाओ|चलाउ|लगाओ)(?: (?:karo|gara|garnu|kar do|करो|गर|गर्नु))?"
YOUTUBE = _rx(r"(?:play|put on|watch) (?P<q>.+?) (?:on|in|from) " + _YT,
              _YT + r"(?: (?:ma|maa|pe|par|mein|me|मा|पर|में))? (?P<q>.+?) " + _YT_DO,
              r"(?P<q>.+?) " + _YT + r"(?: (?:ma|maa|pe|par|mein|me|मा|पर|में))? " + _YT_DO)


def _p9a_intent(t: str) -> Intent | None:
    for name, tool, pats in (("dnd", "do_not_disturb", DND_PATS), ("night_light", "night_light", NL_PATS)):
        if m := _full(pats, t):
            on = m.groupdict().get("on") is not None
            return Intent(name, tool, "desktop", {"action": "on" if on else "off"})
    if _full(WALL_RANDOM, t):
        return Intent("wallpaper", "set_wallpaper", "desktop", {"mode": "random"})
    if _full(WALL_NEXT, t):
        return Intent("wallpaper", "set_wallpaper", "desktop", {"mode": "next"})
    if _full(BATTERY, t):
        return Intent("battery", "battery_status", "power", {})
    if _full(FOCUS_STOP, t):
        return Intent("focus", "focus_mode", "desktop", {"action": "stop"})
    if m := _full(FOCUS_START, t):
        n = m.groupdict().get("n")
        return Intent("focus", "focus_mode", "desktop", {"action": "start", "minutes": int(n) if n else 25})
    if m := _full(YOUTUBE, t):
        q = m.group("q").strip(" ,.\"'")
        if q and len(q) <= 120 and not re.fullmatch(r"(?:it|this|that|something|anything|music|a video)", q, I):
            return Intent("youtube", "youtube", "media", {"query": q, "action": "play"}, q)
    return None


# --- P7 memory / usage ---
DIGEST = _rx(
    r"(?:(?:give|show|tell|read) me |what(?:'s| is) |send me )?(?:my |the |today'?s |todays )?(?:daily )?digest"
    r"(?: for (?P<date>today|yesterday))?(?: today)?",
    r"(?:summari[sz]e|recap) my day", r"(?:give me |show me )?(?:my |a |the )?(?:daily|day'?s) (?:summary|recap)",
    r"(?:summari[sz]e|recap)(?: the| my)? (?:today(?:'?s)?(?: day)?|the day|this day|day)(?: so far)?",
    r"(?:give me |show me |tell me )?(?:a |the )?(?:summary|recap) of (?:today|the day|my day)(?: so far)?",
    r"what (?:did|have) (?:we|i|you) (?:do|done|did) today(?: so far)?", r"how was (?:my|our) day(?: today)?",
)
TOKENS = _rx(
    r"how many tokens (?:did|have) (?:i|we|you) (?:use|used|spend|spent|burn|burned)"
    r"(?: (?P<period>today|this week|this month))?(?: so far)?(?: (?P<period2>today|this week|this month))?",
    r"(?:show |tell me |what(?:'s| is) )?(?:my |the )?(?:token|api|groq) (?:usage|use|spend|cost)"
    r"(?: (?P<period3>today|this week|this month))?",
    r"how much (?:of my )?(?:token )?budget (?:is left|have i used|did i use)(?: today)?",
)
SESSION = _rx(
    r"what (?:did|have) (?:we|i) (?:talk|chat|speak|discuss|talked|chatted|discussed)(?: about)?"
    r"(?: (?P<when>yesterday|today|last time|earlier|before|this morning|on \w+))?",
    r"what (?:were|was) (?:we|i) (?:talking|chatting|discussing)(?: about)?(?: (?P<when2>yesterday|today|last time|earlier|before))?",
    r"(?:what was|recap) (?:our|my) (?:last|previous) (?:conversation|chat|session)",
)
ABOUT_ME = _rx(
    r"what (?:do|else do|all do) you know about me", r"what have you learn(?:ed|t) about me",
    r"who am i", r"tell me (?:what you know )?about (?:me|myself)", r"(?:show |what(?:'s| is) )?my profile",
    r"(?:timilai|tapai lai|tumhe|aapko) mero (?:barema|bare ma) (?:ke|kya) thaha (?:cha|xa|chha)",
)
NAME = _rx(
    r"(?:my name is|my name's|call me|you can call me|mero naam|mera naam|mero nam)\s+"
    r"(?P<name>[^\W\d_][\w'-]*(?: [^\W\d_][\w'-]*)?)(?: (?:ho|hai))?",
    r"(?:मेरो|मेरा) नाम (?P<name>\S+(?: \S+)?) (?:हो|है)",
)
_NAME_BAD = re.compile(r"\b(?:not|and|what|is|the|a|an|back|later|tomorrow|when|if|now|again|maybe|soon|please)\b", I)


def _p7_intent(t: str) -> Intent | None:
    if m := _full(DIGEST, t):
        return Intent("digest", "daily_digest", "usage", {"date": (m.groupdict().get("date") or "today").lower()})
    if m := _full(TOKENS, t):
        per = next((v for k, v in m.groupdict().items() if k.startswith("period") and v), "today").lower()
        return Intent("tokens", "token_usage", "usage", {"period": per.replace("this ", "")})
    if m := _full(SESSION, t):
        when = next((v for v in m.groupdict().values() if v), "last").lower()
        when = "last" if when in ("last time", "earlier", "before") else when
        return Intent("session", "recall_session", "memory", {"query": re.sub(r"^on ", "", when)})
    if _full(ABOUT_ME, t):
        return Intent("about_me", "recall", "memory", {"which": "profile"})
    if (m := _full(NAME, t)) and not _NAME_BAD.search(m.group("name")):
        name = m.group("name").strip()
        return Intent("name", "_profile", "memory", {"key": "name", "value": name}, name)
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


_IMAGE = re.compile(r"^(?:can you\s+|could you\s+)?(?:generate|create|make|draw|paint|design|render)\s+(?:me\s+)?"
                    r"(?:an?\s+|the\s+)?(?:ai\s+)?(?:image|picture|photo|pic|drawing|painting|illustration|artwork)s?\s+"
                    r"(?:of|about|showing|with|for)\s+(?P<p>.{3,})$", I)
_DRAW = re.compile(r"^(?:can you\s+)?draw\s+(?:me\s+)?(?P<p>.{3,})$", I)


WALL_TAIL = re.compile(r"[\s,]*(?:\band\b|\bthen\b)?\s*(?:please\s+)?(?:make|set|use|keep|put|apply)\s+"
                       r"(?:it|this|that|the (?:image|picture|photo))?\s*(?:as\s+)?(?:my\s+|the\s+)?(?:desktop\s+)?"
                       r"(?:wallpaper|background)\b.*$", I)


TG_TAIL = re.compile(r"[\s,]*(?:\b(?:and|then)\b\s*)?(?:also\s+)?(?:please\s+)?(?:send|share|forward)\s+"
                     r"(?:it|this|that|them|the (?:image|picture|photo|pic|file))?\s*(?:image|picture|photo|pic)?\s*"
                     r"(?:to|in|on|via|through)\s+(?:my\s+)?(?:telegram|phone|mobile)\b.*$", I)


def image_intent(t: str) -> Intent | None:
    wall = bool(WALL_TAIL.search(t))
    t = WALL_TAIL.sub("", t) if wall else t
    tg = bool(TG_TAIL.search(t))
    t = TG_TAIL.sub("", t) if tg else t
    m = _IMAGE.match(t) or _DRAW.match(t)
    if not m or re.search(r"\b(?:and|then)\s+(?:send|open|set)\b", t, I):  # multi-step: let the planner split it
        return None
    prompt = m.group("p").strip(" .,!?")
    args = {"prompt": prompt, **({"set_as_wallpaper": True} if wall else {}), **({"send_to_telegram": True} if tg else {})}
    return Intent("image", "generate_image", "image", args, prompt)


_RENAME = re.compile(r"^(?:(?:from now on|now)\s+)?(?:change|set)\s+your\s+name\s+(?:to|as)\s+(?P<n>.+)$|"
                     r"^(?:(?:from now on|now)\s+)?(?:call yourself|your (?:new )?name (?:is|will be))\s+(?P<n2>.+)$|"
                     r"^(?:from now on\s+)?i(?:'ll| will) call you\s+(?P<n3>.+)$", I)
_WHOAMI = re.compile(r"^(?:what(?:'s| is) your name|who are you|what are you|tell me about yourself|"
                     r"introduce yourself)$", I)
_CANDO = re.compile(r"^(?:what (?:all )?can you do|what are your (?:features|abilities|skills)|what do you do)$", I)
_OUT_WHERE = re.compile(r"^where (?:do|did|will) you (?:store|save|keep|put) (?:the |my |your |all )?"
                        r"(?:outputs?|output folder|files|results|images|pictures|essays|poems|work)(?: folder)?$|"
                        r"^where (?:is|are) (?:the |my |your )?(?:outputs?|output folder|results)$", I)
_DATA_WHERE = re.compile(r"^where (?:do|did) you (?:store|save|keep) (?:the |my |your |all )?"
                         r"(?:data|memory|memories|conversations?|chats?|personal info\w*|database|notes)$", I)
_LIMITS = re.compile(r"^what are your (?:limits|limitations|weaknesses)$|^what can'?t you do$", I)
_ARCH = re.compile(r"^(?:how do you work|how are you (?:built|made)|(?:what is|explain|tell me) your architecture|"
                   r"your architecture)$", I)
_HAVE_TOOL = re.compile(r"^do you have (?:a |any )?(?:tool|feature|way|option)s? (?:for|to|that can)\s+(?P<need>.+)$", I)


_GESTURE = re.compile(r"\b(?:gesture|hand (?:control|gesture|sign)s?|(?:youtube |media )?vision control|"
                      # Whisper mishears "gesture control system": jesture, geauster, jigsaw, jaxxor, adjector...
                      r"(?:[jg]e[as]?[su]?t[eu]?(?:r|re|rer|or)|geauster|jigsaw|jaxx?or|jackser|handset|adjector|ajector|digester)s? "
                      r"(?:control|system)|hand \w+ (?:control|system)|control system|"
                      r"(?:youtube|media) (?:media )?controll?er|"
                      r"media control (?:through|with|by|using) (?:my |the )?hands?|control (?:media|youtube|music|it) "
                      r"(?:through|with|by|using) (?:my |the )?hands?)\b", I)
_GEST_ON = re.compile(r"^(?:please\s+)?(?:enable|enabel|enble|inable|start|turn on|switch on|open|activate|launch|run|on)\b", I)
_GEST_OFF = re.compile(r"^(?:please\s+)?(?:disable|stop|turn off|switch off|close|deactivate|kill|end|off)\b", I)
_MATH = re.compile(r"^(?:what(?:'s| is)\s+|calculate\s+|compute\s+)?(?P<e>[\d(][\d\s.+\-*/×÷^()%,]*(?:\s*%\s*of\s*[\d.,]+)?|"
                   r"[\d.]+\s*%\s*of\s*[\d.,]+|sqrt\s*\(?[\d.]+\)?|[\d.]+\s*°?\s*[a-z]+\s+(?:to|in|into)\s+°?[a-z]+)$", I)
_NEWS = re.compile(r"^(?:(?:show|tell|give|read)\s+me\s+)?(?:the\s+)?(?:latest\s+|today'?s\s+|top\s+)?"
                   r"(?:news|headlines)(?:\s+(?:about|on|of|for|in)\s+(?P<topic>.+))?(?:\s+today)?$", I)


_TRAIN_STATUS = re.compile(r"^(?:(?:how(?:'s| is| are)|what(?:'s| is)|is|are|check|show(?: me)?|give me)\s+)?"
                           r"(?:the |my )?(?:model |ml )?(?:training|train(?:ing)? runs?|runs?)(?: going| doing| status|"
                           r" progress| still running| done| finished| over)*(?: now)?$", I)
_COLAB = re.compile(r"^(?:set ?up|connect|link|add|give me|show me)\s+(?:the |my )?(?:google )?colab"
                    r"(?: notebook| cell| snippet| code| training| ping)*$", I)


_CMD_ALERTS = re.compile(r"^(?:(?:turn|switch|put)\s+)?(?P<a>on|off|enable|disable|stop)?\s*(?:the\s+)?"
                         r"(?:long[- ])?command alerts?(?:\s+(?P<b>on|off|status))?$", I)


_WHERE = re.compile(r"^(?:so |ok |okay )?(?:where (?:was|were) (?:i|we)(?: (?:on|with|in)(?: (?P<p>.+?))?)?|what was i "
                    r"(?:working on|doing)(?: (?:in|on|with) (?:the |my )?(?P<p2>.+?)(?: project)?)?|(?:resume|continue) (?:my )?(?:work|project|coding)"
                    r"(?: on (?P<p3>.+?))?)$", I)
_CHANGED = re.compile(r"^what (?:did i|have i) change(?:d)?(?: in (?P<p>(?!the last)\S.*?))?(?: (?:since|in the last|during the "
                      r"last|over the last) (?P<w>.+?))?$", I)


_DOCTOR = re.compile(r"^(?:why is|why's) (?:my |the )?(?:laptop|computer|pc|system|machine)(?: so| very| really)? "
                     r"(?:slow|laggy|lagging|hanging|stuck|hot|heating)(?: now| today)?$|^(?:check|diagnose) "
                     r"(?:my |the )?(?:laptop|computer|pc|system)(?: health| speed)?$", I)
_FREE_RAM = re.compile(r"^(?:free|clean|clear)(?: up)? (?:some )?(?:ram|memory)$", I)
_PORT = re.compile(r"^(?:what(?:'s| is)|who(?:'s| is)) (?:running |listening )?(?:on|using) port (?P<p>\d{2,5})$", I)


_WEBWATCH = re.compile(r"^(?:watch|monitor|keep an eye on|track|tell me when|tell me when (?:this|the) (?:page|site|"
                       r"website) changes:?) (?:the (?:page|site|website) )?"
                       r"(?P<url>https?://\S+|[\w-]+(?:\.[\w-]+)+(?:/\S*)?)(?: (?:changes|updates))?"
                       r"(?: (?:for|and tell me when it (?:says|mentions|shows)|when it (?:says|mentions|shows)) "
                       r"(?P<w>.+?))?$", I)


_DATASET = re.compile(r"^(?:check|inspect|analy[sz]e|look at|examine|validate)\s+(?:my |the |this )?(?:data(?:set)?|"
                      r"csv|images?)\s+(?:at |in |file |folder )?(?P<p>\S.*?)(?: (?:before|for) training)?$", I)


_INSTALL = re.compile(r"^(?:please )?(?:pip )?install (?:the )?(?:package |module |library )?(?P<p>[\w.\-\[\]=<>]+)"
                      r"(?: (?:in|into|for) (?:the |my )?(?P<f>.+?)(?: project| venv)?)?$", I)


_NET = re.compile(r"^(?:why is |is )?(?:my |the )?(?:internet|wifi|wi-fi|net|connection|network)(?: connection)? "
                  r"(?:so |very |really )?(?:slow|not working|down|broken|bad|off|working|ok|fine)(?: now| today)?$|"
                  r"^(?:check|test|diagnose) (?:my |the )?(?:internet|wifi|wi-fi|network|connection)(?: connection)?$|"
                  r"^(?:i have )?no internet$", I)
_NET_SPEED = re.compile(r"^(?:check |test |run (?:a )?)?(?:my |the )?(?:internet|wifi|download) speed(?: test)?$|"
                        r"^speed ?test$|^how fast is (?:my |the )?(?:internet|wifi)$", I)
_NET_BACK = re.compile(r"^(?:tell|notify|ping|message) me when (?:the )?(?:internet|wifi|net|connection) "
                       r"(?:is|comes) back(?: on)?$", I)


_NOTES_SHOW = re.compile(r"^(?:show|give|read|open)(?: me)? (?:my |the )?(?:(?P<s>[\w+#. ]{1,30}?) )?notes?"
                         r"(?: (?:from|for|of) (?P<w>today|yesterday|this week|last week|this month|the last \d+ days))?$",
                         I)
_LECTURE_START = re.compile(r"^(?:start )?record(?:ing)? (?:the |this |my |today'?s )?(?P<on1>online )?(?:lecture|class)"
                            r"(?: (?:called|on|about) (?P<t>(?!zoom|meet|google meet|youtube|teams|the laptop|laptop)\S.*?))?"
                            r"(?P<online> (?:from|on|in) (?:the |my )?"
                            r"(?:laptop|computer|zoom|meet|google meet|youtube|teams))?$", I)
_LECTURE_STOP = re.compile(r"^stop (?:the |my )?(?:recording|lecture recording|lecture|class recording)$", I)
_LECTURE_SUM = re.compile(r"^summari[sz]e (?:my |the |today'?s |last )?(?:lecture|class)$", I)
_TT = re.compile(r"^(?:what (?:classes )?do i have|what(?:'s| is) on|my classes|(?:show )?(?:my )?(?:time ?table|class "
                 r"schedule))(?: for| on)? ?(?P<w>today|tomorrow|this week|the week|week)?$", I)
_NEXT_CLASS = re.compile(r"^(?:when(?:'s| is) )?(?:my )?next class$|^what(?:'s| is) (?:my )?next class$", I)
_QUIZ = re.compile(r"^(?:quiz|test) me(?: on (?P<s>.+?))?$|^(?P<m>make|create|generate) (?:a )?(?:quiz|questions|flash ?cards)"
                   r" (?:from|for|on) (?:my )?(?P<s2>.+?)(?: notes)?$", I)
_QUIZ_MOVES = {"show the answer": "answer", "show answer": "answer", "what is the answer": "answer", "i got it": "right",
               "i got it right": "right", "got it": "right", "correct": "right", "i got it wrong": "wrong",
               "wrong": "wrong", "i didn't know": "wrong", "i did not know": "wrong", "quiz stats": "stats"}
_DAYS = {"today": 1, "yesterday": 2, "this week": 7, "last week": 14, "this month": 31}


_STATUS = re.compile(r"^(?:(?:what(?:'s|s| is) the )?(?:current )?status|what(?:'s|s| is) going on|what(?:'s|s| is) happening|"
                     r"any (?:updates?|news)|give me (?:an |the )?(?:update|status)|how(?:'s| is) everything(?: going)?|"
                     r"status (?:update|report)|update me)(?: now)?$", I)
_TRAIN_Q = re.compile(r"^(?:what(?:'s| is) the |how many |which )?(?:current |latest )?(?:accuracy|acc|loss|epochs?|val(?:idation)? "
                      r"(?:accuracy|loss))(?: (?:now|so far|is it(?: on)?|done|completed|finished|are done|of (?:my |the )?"
                      r"(?:model|training)))*$", I)
_TRAIN_STOP = re.compile(r"^(?:please )?(?:stop|end|cancel|kill|halt) (?:the |my )?(?:model )?(?:training|train(?:ing)? run|"
                         r"colab(?: training| run)?)(?P<now> (?:right )?now| immediately| at once)?$", I)


def _study_intent(t: str) -> Intent | None:
    if _STATUS.match(t):
        return Intent("status", "status_now", "usage", {})
    if _TRAIN_Q.match(t):
        return Intent("training", "training", "watch", {"action": "status"})
    if m := _TRAIN_STOP.match(t):
        return Intent("training", "training", "watch", {"action": "stop_now" if m.group("now") else "stop"})
    if m := _TT.match(t):
        w = (m.group("w") or "today").lower()
        return Intent("study", "timetable", "study", {"action": "week" if "week" in w else w})
    if _NEXT_CLASS.match(t):
        return Intent("study", "timetable", "study", {"action": "next"})
    if m := _QUIZ.match(t):
        if m.group("m"):
            return Intent("study", "quiz", "study", {"action": "make", "subject": m.group("s2").strip()})
        return Intent("study", "quiz", "study", {"action": "ask", "subject": (m.group("s") or "").strip()})
    if (move := _QUIZ_MOVES.get(t.lower().strip(" .!"))) and store.kv_get("quiz_current"):
        return Intent("study", "quiz", "study", {"action": move})
    return None


_DL = re.compile(r"^download (?P<u>https?://\S+)(?: (?:to|into|in) (?P<f>.+?))?(?P<n> tonight| at night| overnight)?$", I)
_CLEAN = re.compile(r"^(?:clean|clear|empty|delete|remove|free)(?: up)? (?:the |my |all )?(?P<c>pip cache|hugging ?face "
                    r"cache|hf cache|torch cache|trash|old checkpoints|checkpoints|duplicates|duplicate files|old "
                    r"downloads|pycache|old venvs|venvs)$", I)
_CLEAN_CAT = {"pip cache": "pip_cache", "huggingface cache": "hf_cache", "hugging face cache": "hf_cache",
              "hf cache": "hf_cache", "torch cache": "torch_cache", "trash": "trash", "old checkpoints": "checkpoints",
              "checkpoints": "checkpoints", "duplicates": "duplicates", "duplicate files": "duplicates",
              "old downloads": "old_downloads", "pycache": "pycache", "old venvs": "dead_venvs", "venvs": "dead_venvs"}
_TIDY = re.compile(r"^(?:sort|tidy|clean|organi[sz]e)(?: up)? (?:my |the )?downloads?(?: folder)?$", I)
_BACKUP = re.compile(r"^(?:back ?up|backup) (?:my (?:projects|files|work|code)|everything|now)$", I)


_JOT = re.compile(r"^(?:jot|note|write|put) (?:this |it )?down (?:for|in|under) (?P<s>[\w+#.]+)[:,]? (?P<t>.+)$", I)


def _daily_intent(t: str) -> Intent | None:
    if m := _JOT.match(t):  # "jot down for physics newton's third law": a study note (one-word subject)
        return Intent("note", "study_notes", "study", {"action": "add", "text": m.group("t"), "subject": m.group("s")})
    if m := _DL.match(t):
        return Intent("auto", "download_file", "automation", {"action": "add", "url": m.group("u"),
                                                              "folder": m.group("f") or "",
                                                              "when": "tonight" if m.group("n") else "now"})
    if m := _CLEAN.match(t):
        return Intent("auto", "disk_cleaner", "daily", {"action": "clean",
                                                        "category": _CLEAN_CAT[m.group("c").lower()]})
    if _TIDY.match(t):
        return Intent("auto", "tidy_downloads", "automation", {"action": "run"})
    if _BACKUP.match(t):
        return Intent("auto", "backup", "automation", {"action": "run"})
    if si := _study_intent(t):
        return si
    if (m := notes_mod.NOTE.match(t)) and not t.lower().startswith(("note that", "remember")):
        return Intent("note", "study_notes", "study", {"action": "add", "text": m.group("t").strip(),
                                                       "subject": (m.group("s1") or m.group("s2") or "").strip()})
    if m := _NOTES_SHOW.match(t):
        w = (m.group("w") or "this week").lower()
        days = int(re.search(r"\d+", w).group()) if re.search(r"\d+", w) else _DAYS.get(w, 7)
        subj = (m.group("s") or "").strip()
        return Intent("notes", "study_notes", "study", {"action": "show", "subject": "" if subj.lower() in (
            "all", "study", "my", "the") else subj, "days": days})
    if m := _LECTURE_START.match(t):
        return Intent("lecture", "lecture", "study", {"action": "start", "title": (m.group("t") or "").strip(),
                                                      "source": "laptop" if m.group("online") or m.group("on1") else "mic"})
    if _LECTURE_STOP.match(t):
        return Intent("lecture", "lecture", "study", {"action": "stop"})
    if _LECTURE_SUM.match(t):
        return Intent("lecture", "lecture", "study", {"action": "summarize"})
    if _NET.match(t):
        return Intent("net", "internet_doctor", "system", {"action": "check"})
    if _NET_SPEED.match(t):
        return Intent("net", "internet_doctor", "system", {"action": "speed"})
    if _NET_BACK.match(t):
        return Intent("net", "internet_doctor", "system", {"action": "notify_when_back"})
    if m := _INSTALL.match(t):
        pkg = m.group("p")
        if pkg.lower() in ("it", "this", "that", "them"):  # "install it" right after a ModuleNotFoundError
            last = store._exec("SELECT error FROM errors WHERE sig=?", (store.kv_get("errmem_last") or "",))
            pkg = last[0][0] if last and "No module named" in last[0][0] else ""
        if pkg and pkg.lower() not in ("app", "the"):
            return Intent("install", "python_env", "dev", {"action": "install", "package": pkg,
                                                           "folder": m.group("f") or "."})
    if m := _DATASET.match(t):
        return Intent("dataset", "check_dataset", "dev", {"path": m.group("p").strip(" '\"")})
    if m := _WEBWATCH.match(t):
        return Intent("webwatch", "web_watch", "web", {"action": "add", "url": m.group("url"),
                                                        "word": (m.group("w") or "").strip(" '\"")})
    if _DOCTOR.match(t):
        return Intent("doctor", "laptop_doctor", "system", {"action": "check"})
    if _FREE_RAM.match(t):
        return Intent("doctor", "laptop_doctor", "system", {"action": "free_ram"})
    if m := _PORT.match(t):
        return Intent("doctor", "laptop_doctor", "system", {"action": "port", "target": m.group("p")})
    if m := _WHERE.match(t):
        return Intent("where", "where_was_i", "git", {"project": m.group("p") or m.group("p2") or m.group("p3") or ""})
    if m := _CHANGED.match(t):
        w = (m.group("w") or "1 hour").strip()
        if re.fullmatch(r"(?:\d+|an?|one|two|few)\s+(?:min(?:ute)?s?|hours?|days?)", w, I):
            w = re.sub(r"^(?:an?|one)\b", "1", w, flags=I) + " ago"
        return Intent("changes", "time_machine", "git", {"action": "changes", "project": m.group("p") or "", "when": w})
    if re.fullmatch(r"undo (?:the |that )?restore", t, I):
        return Intent("changes", "time_machine", "git", {"action": "undo"})
    if (m := _CMD_ALERTS.match(t)) and (m.group("a") or m.group("b")):
        a = (m.group("a") or m.group("b")).lower()
        return Intent("cmdalerts", "command_alerts", "watch",
                      {"action": {"enable": "on", "disable": "off", "stop": "off"}.get(a, a)})
    if _TRAIN_STATUS.match(t) and re.search(r"train|run", t, I):
        return Intent("training", "training", "watch", {"action": "status"})
    if _COLAB.match(t):
        return Intent("training", "training", "watch", {"action": "colab"})
    if _GESTURE.search(t):
        if _GEST_OFF.match(t):
            return Intent("gesture", "gesture_control", "media", {"action": "off"})
        if _GEST_ON.match(t) or re.match(r"^(?:i want|can you|could you)\b", t, I):
            return Intent("gesture", "gesture_control", "media", {"action": "on"})
    if (m := _MATH.match(t)) and re.search(r"\d", t) and (re.search(r"[+\-*/×÷^%]|sqrt|\bto\b|\bin\b|into", t)):
        return Intent("calc", "calculate", "daily", {"expression": m.group("e")})
    if m := _NEWS.match(t):
        topic = (m.group("topic") or "").strip()
        return Intent("news", "web_search", "web", {"query": f"latest news {topic or 'Nepal'}"})
    return None


def _self_intent(t: str) -> Intent | None:
    from jarvis.core import selfknow
    if selfknow.looks_like_password_try(t):
        return Intent("unlock", "_unlock", "self", {"text": t})
    if m := _RENAME.match(t):
        new = (m.group("n") or m.group("n2") or m.group("n3") or "").strip(" .!")
        return Intent("rename", "set_my_name", "self", {"name": new}, new)
    if _WHOAMI.match(t):
        return Intent("whoami", "about_me", "self", {"topic": "overview"})
    if _CANDO.match(t):
        return Intent("cando", "about_me", "self", {"topic": "overview"})
    if _OUT_WHERE.match(t):
        return Intent("selfinfo", "about_me", "self", {"topic": "outputs"})
    if _DATA_WHERE.match(t):
        return Intent("selfinfo", "about_me", "self", {"topic": "storage"})
    if _LIMITS.match(t):
        return Intent("selfinfo", "about_me", "self", {"topic": "limits"})
    if _ARCH.match(t):
        return Intent("selfinfo", "about_me", "self", {"topic": "architecture"})
    if m := _HAVE_TOOL.match(t):
        return Intent("havetool", "find_capability", "self", {"need": m.group("need")}, m.group("need"))
    return None


_ERR_ASK = re.compile(r"^(?:(?:can you |please )?(?:explain|fix|solve|debug|check)|what(?:'s| is| does))\s+(?:this |the |my "
                      r"|that )?(?:error|traceback|exception|bug)(?: mean| means| say| on my clipboard)?$", I)
_ERR_FIXED = re.compile(r"^i (?:fixed|solved) (?:it|that|this|the error|that error)(?: by| with|:)\s+(?P<fix>.+)$", I)


def error_intent(text: str) -> Intent | None:
    """A pasted traceback, 'explain this error' (clipboard) or 'I fixed it by ...' -> fix_error (0 routing tokens)."""
    raw = text.strip()
    if "Traceback (most recent call last)" in raw or (len(raw.splitlines()) >= 2 and re.search(
            r"^\s*\w*(?:Error|Exception):", raw, re.M)):
        return Intent("error", "fix_error", "dev", {"action": "explain", "text": raw[-4000:]})
    t = normalize(raw)
    if _ERR_ASK.match(t):
        return Intent("error", "fix_error", "dev", {"action": "explain"})
    if m := _ERR_FIXED.match(t):
        return Intent("error", "fix_error", "dev", {"action": "fixed", "text": m.group("fix")})
    return None


def match(text: str) -> Intent | None:
    """The single high-confidence intent for text, or None."""
    from jarvis.core import selfknow
    if selfknow.looks_like_password_try(text):  # raw text: the password answer is checked before anything else
        return Intent("unlock", "_unlock", "self", {"text": text})
    if ei := error_intent(text):
        return ei
    if len(study_mod.parse(text)) >= 2:  # a pasted timetable
        return Intent("study", "timetable", "study", {"action": "set", "text": text})
    t = normalize(text)
    if not t or len(t) > 200:
        return None
    if si := _self_intent(t):
        return si
    if di := _daily_intent(t):
        return di
    if ci := _control_intent(t):  # shutdown/restart/sleep, timers, alarms, stopwatch, Wi-Fi...
        return ci
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
    if p9b := _p9b_intent(t):  # P9b reminders
        return p9b
    if p7 := _p7_intent(t):
        return p7
    if _full(RECALL_LAST, t):
        return Intent("recall", "recall", "memory", {"which": "last"})
    if _full(RECALL_ALL, t):
        return Intent("recall", "recall", "memory", {"which": "all"})
    if m := _full(REMEMBER, t):
        note = m.group("text").strip(" ,:-")
        if not note or text.rstrip().endswith("?") or _CHATTY.match(note):
            return None
        return Intent("remember", "remember", "memory", {"text": note}, note)
    if p9 := _p9a_intent(t):  # P9a
        return p9
    if sysi := _system_intent(t):
        return sysi
    if ii := image_intent(t):
        return ii
    if li := listdir_intent(t):
        return li
    if si := search_intent(t):
        return si
    if m := _full(OPEN, t):
        return _open_intent(m.group("target").strip(" ,"), m.group("verb").lower())
    if m := _full(CLOSE, t):
        return _close_intent(m.group("target").strip(" ,"))
    return None


def _close_intent(target: str) -> Intent | None:
    if not target or len(target.split()) > 4 or _BAD_TARGET.search(target):
        return None
    from jarvis.tools.general import _apps

    entry, score = _apps.find_app(target)
    if entry is None or score < _apps.FASTPATH_MIN_SCORE:
        return None
    return Intent("close", "close_app", "apps", {"name": target}, target)  # say it the way the user did


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
    "open": {"en": "Sure, opening {x}.", "hi": "ज़रूर, {x} खोल रहा हूँ।", "ne": "हुन्छ, {x} खोल्दैछु।"},
    "search": {"en": "Sure, opening {e} results for {q}.", "hi": "ज़रूर, {e} पर {q} के नतीजे खोल रहा हूँ।",
               "ne": "हुन्छ, {e} मा {q} को नतिजा खोल्दैछु।"},
    "close": {"en": "Done, I closed {x}.", "hi": "{x} बंद कर दिया।", "ne": "{x} बन्द गरें।"},
    "not_open": {"en": "{x} isn't open.", "hi": "{x} खुला नहीं है।", "ne": "{x} खुलेको छैन।"},
    "open_fail": {"en": "Sorry, I couldn't open {x}.", "hi": "माफ़ कीजिए, {x} नहीं खुल सका।",
                  "ne": "माफ गर्नुहोस्, {x} खोल्न सकिनँ।"},
    "no_place": {"en": "Sorry, I couldn't find a place called {x}.", "hi": "माफ़ कीजिए, {x} नाम की जगह नहीं मिली।",
                 "ne": "माफ गर्नुहोस्, {x} नामको ठाउँ भेटिएन।"},
    "failed": {"en": "Sorry, that didn't work: {x}", "hi": "माफ़ कीजिए, यह नहीं हुआ: {x}",
               "ne": "माफ गर्नुहोस्, भएन: {x}"},
    "volume": {"en": ("Done, the volume is at {x}%.", "Volume set to {x}%.", "Okay, {x}% volume."),
               "hi": "आवाज़ {x}% पर है।", "ne": "भोल्युम {x}% मा छ।"},
    "brightness": {"en": ("Done, brightness is at {x}%.", "Brightness set to {x}%.", "Okay, {x}% brightness."),
                   "hi": "ब्राइटनेस {x}% पर है।", "ne": "ब्राइटनेस {x}% मा छ।"},
    # answers to a question ("what is the volume?"): no "Done", just the fact
    "volume_now": {"en": ("The volume is at {x}%.", "It's at {x}% right now."), "hi": "आवाज़ अभी {x}% पर है।",
                   "ne": "भोल्युम अहिले {x}% मा छ।"},
    "brightness_now": {"en": ("Brightness is at {x}%.", "The screen is at {x}% brightness."),
                       "hi": "ब्राइटनेस अभी {x}% पर है।", "ne": "ब्राइटनेस अहिले {x}% मा छ।"},
    "sound_state": {"en": "The sound is {x}.", "hi": "आवाज़ {x} है।", "ne": "आवाज {x} छ।"},
    "mic_state": {"en": "Your microphone is {x}.", "hi": "माइक {x} है।", "ne": "माइक {x} छ।"},
    "muted": {"en": "Okay, sound is muted.", "hi": "आवाज़ बंद कर दी।", "ne": "आवाज बन्द गरें।"},
    "unmuted": {"en": "Sound is back on.", "hi": "आवाज़ चालू कर दी।", "ne": "आवाज फेरि चालू भयो।"},
    "mic_muted": {"en": "Okay, your microphone is muted.", "hi": "माइक बंद कर दिया।", "ne": "माइक बन्द गरें।"},
    "mic_unmuted": {"en": "Okay, your microphone is on.", "hi": "माइक चालू कर दिया।", "ne": "माइक चालू गरें।"},
    "paused": {"en": "Okay, paused.", "hi": "रोक दिया।", "ne": "रोकें।"},
    "playing": {"en": "Okay, playing.", "hi": "चला रहा हूँ।", "ne": "बजाउँदैछु।"},
    "next": {"en": "Okay, next track.", "hi": "अगला गाना।", "ne": "अर्को गीत।"},
    "previous": {"en": "Okay, previous track.", "hi": "पिछला गाना।", "ne": "अघिल्लो गीत।"},
    "screenshot": {"en": "Done! Your screenshot is saved in the Screenshots folder.",
                   "hi": "स्क्रीनशॉट Screenshots फ़ोल्डर में सेव हो गया।", "ne": "स्क्रिनसट Screenshots फोल्डरमा सेभ भयो।"},
    "lock": {"en": "Sure, locking the screen.", "hi": "स्क्रीन लॉक कर रहा हूँ।", "ne": "स्क्रिन लक गर्दैछु।"},
    "name": {"en": "Nice to meet you, {x}. I'll remember your name.", "hi": "आपसे मिलकर अच्छा लगा, {x}। मैं आपका नाम याद रखूँगा।",
             "ne": "भेटेर खुसी लाग्यो, {x}। म तपाईंको नाम सम्झिराख्छु।"},
}
_SYSTEM = {"volume", "brightness", "mute", "mic", "media", "screenshot", "lock", "theme"}


def _render_system(intent: Intent, out: str, lang: str) -> str:
    asked = intent.args.get("action") in ("get", "status")  # a question, not a command
    if intent.name in ("volume", "brightness"):
        m = re.search(r"(\d+)%", out)
        if not m:
            return out
        reply = _say(intent.name + ("_now" if asked else ""), lang, m.group(1))
        return reply + (" Sound is muted, though." if asked and "muted" in out and lang == "en" else "")
    if intent.name in ("mute", "mic") and asked:
        state = "unmuted" if "unmuted" in out else "muted"
        return _say("sound_state" if intent.name == "mute" else "mic_state", lang,
                    {"unmuted": "on", "muted": "muted"}[state] if lang == "en" else state)
    if intent.name in ("mute", "mic"):
        key = "unmuted" if "unmuted" in out else "muted"
        return _say(key if intent.name == "mute" else "mic_" + key, lang, "")
    if intent.name == "media":
        action = intent.args.get("action")
        if action == "status":
            return out[:1].upper() + out[1:].rstrip(".") + "."
        return _say({"pause": "paused", "play": "playing"}.get(action, action), lang, "")
    if intent.name == "theme":
        return out if not out.lower().startswith("error") else out
    return _say(intent.name, lang, "")  # screenshot / lock
_TIME_OUT = re.compile(r"^It's (?P<h12>\d+:\d\d) (?P<ampm>AM|PM) on (?P<day>\w+), (?P<date>\d+ \w+ \d+)"
                       r"(?: in (?P<where>.+?))?\.$")


def _say(key: str, lang: str, x: str) -> str:
    t = _T[key]
    v = t.get(lang, t["en"])
    return (random.choice(v) if isinstance(v, tuple) else v).format(x=x)  # a few wordings: less robotic


def render(intent: Intent, ok: bool, output: str, lang: str) -> str:
    out = output.strip()
    err = (not ok) or out.lower().startswith("error")
    if intent.name in ("time", "weather") and err and "couldn't find a place" in out:
        return _say("no_place", lang, intent.label)
    if err:
        if intent.name in ("open", "search"):
            return _say("open_fail", lang, intent.label.split("|")[0])
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
    if intent.name == "close":
        if out.startswith("no open window"):
            return _say("not_open", lang, intent.label[:1].upper() + intent.label[1:])
        return _say("close", lang, intent.label)
    if intent.name == "search":
        eng, q = intent.label.split("|", 1)
        return _T["search"].get(lang, _T["search"]["en"]).format(e=eng, q=q)
    if intent.name == "name":
        return _say("name", lang, intent.label)
    if intent.name == "selfinfo" and out.startswith("LOCKED"):
        return "That's protected information. Please tell me the password first."
    if intent.name == "whoami":
        from jarvis.core import identity
        return f"I'm {identity.name()}, your personal assistant on this laptop. " + out.split(". ", 2)[-1].split(". ")[0] + "."
    if intent.name == "havetool":
        lines = [ln[2:].split(" (", 1)[0].replace("_", " ") for ln in out.splitlines() if ln.startswith("- ")]
        if not lines:
            return ("I don't have a tool for that yet. I can search the web for the steps, or build a small new "
                    "tool for it if you like.")
        return f"Yes, I can help with {intent.label}. These of my tools fit: {', '.join(lines[:4])}. Shall I start?"
    if intent.name == "listdir":
        return _render_listdir(intent, out)
    return out  # weather / recall / digest / tokens / session: the tool output is already text


def _render_listdir(intent: Intent, out: str) -> str:
    """Short folder listings are said as they are; long ones get a one-line overview and go to the Workspace."""
    lines = out.splitlines()
    if len(lines) < 8:  # "/media/.../Tara : 6 folders, 0 files" -> "Tara has 6 folders, 0 files."
        return "\n".join(re.sub(r"^(/\S.*?) : (\d.*)$", lambda m: f"{Path(m.group(1)).name} has {m.group(2)}.", ln)
                         for ln in lines)
    from jarvis.core import workspace

    path = workspace.publish(f"folder: {intent.label[:60]}", out)
    if path is not None:
        intent.args["_published"] = str(path.relative_to(Path(config.OUTPUTS_DIR)))
    heads = [ln.split(" : ", 1) for ln in lines if " : " in ln and ln.split(" : ", 1)[1][:1].isdigit()]
    said = "; ".join(f"{Path(p).name} has {n}" for p, n in heads[:3]) or "Here's the list"
    return f"{said}. The full numbered list is in your workspace; say 'send 3' to get one."


_AND = {"en": " and ", "hi": " और ", "ne": " र "}


def merge_opens(answers: list[str]) -> list[str]:
    """["Sure, opening YouTube.", "Sure, opening Facebook."] -> ["Sure, opening YouTube and Facebook."]."""
    out: list[str] = []
    run: tuple[str, list[str]] | None = None  # (lang, names)
    pats = {lg: re.compile("^" + re.escape(tpl).replace(re.escape("{x}"), "(.+?)") + "$")
            for lg, tpl in _T["open"].items()}

    def flush():
        if run:
            lg, names = run
            joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + _AND.get(lg, " and ") + names[-1]
            out.append(_T["open"][lg].format(x=joined))
    for a in answers:
        hit = next(((lg, m.group(1)) for lg, p in pats.items() if (m := p.match(a.strip()))), None)
        if hit and run and run[0] == hit[0]:
            run[1].append(re.sub(r"\s+(?:website|web site|site)$", "", hit[1], flags=I))
            continue
        flush()
        run = (hit[0], [re.sub(r"\s+(?:website|web site|site)$", "", hit[1], flags=I)]) if hit else None
        if not hit:
            out.append(a)
    flush()
    return out


def _internal(intent: Intent) -> tuple[bool, str]:
    """Intents handled without a registered tool (P7 profile acknowledgement)."""
    if intent.tool == "_unlock":
        from jarvis.core import selfknow
        return True, selfknow.try_unlock(intent.args["text"])
    if intent.tool == "_profile":
        from jarvis.core import profile
        profile.save(intent.args["key"], intent.args["value"], "fastpath")
        return True, "ok"
    return False, f"error: unknown internal intent {intent.tool}"


_VOICE_FIRST_LINE = {"digest", "tokens"}  # long reports: voice speaks the first (summary) line only


def try_answer(text: str, lang: str | None = None, confirm=None, mode: str = "text", ctx: dict | None = None) -> FastResult | None:
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
    if intent.tool.startswith("_"):
        ok, output = _internal(intent)
    else:
        shelf: list[str] = []  # files the tool put in the Workspace
        res = safety.execute(intent.tool, {k: v for k, v in intent.args.items() if not k.startswith("_")},
                              confirm=confirm, ctx={**(ctx or {}), "user_text": text, "published": shelf})
        ok, output = res.ok, res.output
        if shelf:
            intent.args.setdefault("_published", shelf[-1])
    if intent.name in ("time", "weather") and "couldn't find a place" in (output or ""):
        return None  # unknown place: let the LLM path try (it can fix spelling)
    answer = render(intent, ok, output, lang or "en")
    published = [intent.args.pop("_published")] if "_published" in intent.args else []
    if mode == "voice" and intent.name in _VOICE_FIRST_LINE:
        answer = answer.split("\n", 1)[0]
    ms = int((time.monotonic() - t0) * 1000)
    try:
        store.log_routing(text, [intent.group], "fastpath", ms)
    except Exception as e:
        log.warning("could not log routing: %s", e)
    return FastResult(answer, intent, ok, ms, published)


# --- P9b --- reminders: "remind me to X at/in ...", "remind me at ... to X", list, cancel
REMIND = _rx(r"(?:remind me|set (?:a |an |the |my )?(?:reminder|alarm)|add (?:a )?reminder|create (?:a )?reminder)"
             r"(?: for me)?(?: to| that| about| for)?\s+(?P<rest>.+)")
# "3:02 PM of today for reading book": time first, then the task
_WHEN_FIRST = re.compile(r"^(?P<d1>(?:today|tomorrow)\s+)?(?:at\s+)?(?P<t>\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.))"
                         r"(?:\s+(?:of\s+)?(?P<d2>today|tomorrow))?\s+(?:for|to|about)\s+(?P<x>.+)$", I)
REMIND_LIST = _rx(
    r"(?:what|which|any) (?:reminders|schedules|scheduled (?:commands|tasks)) (?:do i have|are there|are set|"
    r"have i set)(?: today)?",
    r"(?:list|show|tell)(?: me)?(?: all)?(?: of)?(?: my)? (?:reminders|schedules|scheduled (?:commands|tasks))",
    r"(?:my|all) reminders", r"do i have any reminders")
REMIND_CANCEL = _rx(r"(?:cancel|delete|remove|stop) (?:the )?(?:reminder|schedule|scheduled command)"
                    r"(?: number| no\.?)? ?#?(?P<id>\d+)")


# --- laptop control + clock (0 tokens) ---
_DEV = r"(?:\s+(?:the|my|this))?\s*(?:laptop|computer|pc|system|machine|device)"
_SHUTDOWN = re.compile(r"^(?:shut\s*down|power\s*off)(?:" + _DEV + r")?(?:\s+now)?$|^(?:turn|switch)\s+off" + _DEV + r"(?:\s+now)?$", I)
_RESTART = re.compile(r"^(?:restart|reboot)(?:" + _DEV + r")?(?:\s+now)?$", I)
_SUSPEND = re.compile(r"^(?:(?:sleep|suspend|hibernate)" + _DEV + r"|suspend|put" + _DEV + r"\s+to\s+sleep|"
                      r"make" + _DEV + r"\s+sleep)(?:\s+now)?$", I)
_LOGOUT = re.compile(r"^(?:log\s*out|logout|sign\s*out)(?:\s+(?:of\s+)?(?:the|my)?\s*(?:session|account|laptop|computer))?$", I)
_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
        "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "forty five": 45, "half an": 0.5}
_AMOUNT = r"(?P<n>\d+(?:\.\d+)?|a|an|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|thirty|forty(?: five)?|half an)"
_UNIT = r"(?P<u>sec(?:ond)?s?|min(?:ute)?s?|hours?|hrs?)"
_TIMER = [re.compile(r"^(?:set|start|put|make)\s+(?:\w+\s+)?(?:timer|countdown|count\s*down)\s+(?:for|of)\s+" + _AMOUNT + r"\s*" + _UNIT + r"$", I),
          re.compile(r"^(?:set|start)?\s*(?:a|an)?\s*" + _AMOUNT + r"[\s-]*" + _UNIT + r"\s+(?:timer|countdown)$", I),
          re.compile(r"^(?:timer|countdown)\s+(?:for\s+)?" + _AMOUNT + r"\s*" + _UNIT + r"$", I)]
_ALARM = re.compile(r"^(?:set|put|create|add)\s+(?:an?\s+|the\s+)?alarm\s+(?:for|at)\s+(?P<w>.+)$|"
                    r"^wake\s+me\s+(?:up\s+)?(?:at|by|in)\s+(?P<w2>.+)$|^alarm\s+(?:for|at)\s+(?P<w3>.+)$", I)
_STOPWATCH = re.compile(r"^(?P<a>start|begin|stop|pause|reset|restart|resume|check|lap)?\s*(?:the\s+|a\s+)?stop\s?watch"
                        r"(?:\s+(?P<b>start|stop|status|time|lap|reset))?(?:\s+now)?$|^(?P<c>lap)$", I)
_DEVICES = (("airplane", r"(?:air|aero)plane(?:\s+mode)?|flight\s+mode"), ("wifi", r"wi[\s-]?fi|wireless|internet"),
            ("bluetooth", r"blue\s?tooth"), ("power_mode", r"(?:battery|power)\s+saver"), ("screen", r"screen|display"))
_SW_VERB = re.compile(r"\b(?:turn|switch|put|make|set|enable|disable|activate|deactivate|start|stop|kill)\b", I)
_SW_FILL = re.compile(r"\b(?:the|my|this|that|it|please|bro|man|dude|now|again|then|also|just|for me|kurama|"
                      r"can you|could you|would you|will you)\b", I)
_SW_FOLLOW = re.compile(r"^(?:(?:turn|switch|put)\s+)?(?:it|this|that|them)?\s*(?:on|off|back on|back off)"
                        r"(?:\s+(?:it|this|that|them))?$|^(?:turn|switch|put)\s+(?:it|this|that|them)\s+(?:on|off)$", I)
SWITCH_TTL_S = 600  # "turn it off" refers to the device switched in the last 10 minutes


def switch_intent(t: str) -> Intent | None:
    """"turn off bluetooth", "bluetooth off bro", "disable wifi", and the follow-up "turn it off" (0 tokens)."""
    low = t.lower()
    device = next((name for name, rx in _DEVICES if re.search(r"\b(?:" + rx + r")\b", low)), None)
    question = re.match(r"^(?:is|are|was|check|what(?:'s| is)|tell me|show me|can you (?:tell|check|give))\b", low) \
        or re.search(r"\b(?:status|whether)\b", low)
    if question and not _SW_VERB.search(low) and "password" not in low:
        # "is bluetooth on?", "bluetooth status": a question, answered by reading the switch
        return Intent("control", "laptop_toggle", "system", {"setting": device, "state": "status"}) \
            if device in ("wifi", "bluetooth", "airplane", "power_mode") else None
    st = "off" if re.search(r"\b(?:off|down|disable|deactivate|kill|stop)\b", low) else \
        "on" if re.search(r"\b(?:on|up|enable|activate|start)\b", low) else None
    if st is None:
        return None
    rest = _SW_FILL.sub(" ", low)
    if device is None:  # follow-up: "turn it off", "then turn off this", "off"
        if not _SW_FOLLOW.match(" ".join(re.sub(r"\b(?:then|now|please|bro|kurama)\b", " ", low).split())):
            return None
        try:
            import json
            from jarvis.core import store
            last = json.loads(store.kv_get("last_switch", "") or "{}")
        except Exception:
            last = {}
        if time.time() - last.get("t", 0) > SWITCH_TTL_S or not last.get("device"):
            return None
        device = last["device"]
    elif not (_SW_VERB.search(rest) or len(rest.split()) <= 3):  # "my bluetooth is off" is a statement, not an order
        return None
    if device == "screen":
        return Intent("control", "laptop_toggle", "system", {"setting": "screen", "state": "off"}) if st == "off" else None
    if device == "power_mode":
        return Intent("control", "laptop_toggle", "system", {"setting": "power_mode", "state": "saver" if st == "on" else "balanced"})
    return Intent("control", "laptop_toggle", "system", {"setting": device, "state": st})


_POWERMODE = re.compile(r"^(?:switch\s+to\s+|set\s+|use\s+|enable\s+)?(?P<m>power saver|battery saver|saver|balanced|"
                        r"performance|high performance)\s+mode$", I)


def _amount(m: re.Match) -> dict | None:
    n = m.group("n").lower()
    v = float(n) if n[0].isdigit() else _NUM.get(n)
    u = m.group("u").lower()
    key = "seconds" if u.startswith("s") else "hours" if u.startswith("h") else "minutes"
    return {key: v} if v else None


_PHONE_TAIL = re.compile(r"[\s,]+(?:and\s+)?(?:(?:when|once|after)\b[^,]{0,40}?[\s,]+)?(?:also\s+)?(?:send|message|text|"
                         r"notify|tell|ping|alert|inform)\b.{0,40}?\b(?:telegram|telegra|phone|mobile)\b.*$", I)


def _control_intent(t: str) -> Intent | None:
    if _SHUTDOWN.match(t):
        return Intent("control", "power_off", "power", {"action": "shutdown"})
    if _RESTART.match(t):
        return Intent("control", "power_off", "power", {"action": "restart"})
    if _SUSPEND.match(t):
        return Intent("control", "suspend_computer", "power", {})
    if _LOGOUT.match(t):
        return Intent("control", "power_off", "power", {"action": "logout"})
    t2 = _PHONE_TAIL.sub("", t)  # "set a timer for 40 seconds and when it's done message me on Telegram"
    for rx in _TIMER:
        if (m := rx.match(t2)) and (args := _amount(m)):
            return Intent("control", "set_timer", "clock", {**args, "phone": True} if t2 != t else args)
    if m := _ALARM.match(t):
        w = (m.group("w") or m.group("w2") or m.group("w3")).strip(" .")
        return Intent("control", "set_alarm", "clock", {"when": w if not t.lower().startswith("wake me up in") else f"in {w}"})
    if m := _STOPWATCH.match(t):
        a = (m.group("a") or m.group("b") or m.group("c") or "status").lower()
        a = {"begin": "start", "resume": "start", "restart": "reset", "pause": "stop", "check": "status",
             "time": "status"}.get(a, a)
        return Intent("control", "stopwatch", "clock", {"action": a})
    if si := switch_intent(t):
        return si
    if m := _POWERMODE.match(t):
        mode = m.group("m").lower()
        return Intent("control", "laptop_toggle", "system",
                      {"setting": "power_mode", "state": "saver" if "saver" in mode else "performance" if "perf" in mode else "balanced"})
    return None


def _p9b_intent(t: str) -> Intent | None:
    if _full(REMIND_LIST, t):
        return Intent("schedules", "list_schedules", "schedule")
    if m := _full(REMIND_CANCEL, t):
        return Intent("schedules", "cancel_schedule", "schedule", {"item": m.group("id")})
    if m := _full(REMIND, t):
        from jarvis.core import when

        got = when.split(m.group("rest"))
        if not got and (w := _WHEN_FIRST.match(m.group("rest"))):
            day = (w.group("d1") or w.group("d2") or "").strip()
            got = when.split(f"{w.group('x')} at {w.group('t')} {day}".strip())
        if got:
            what, when_text, _ = got
            return Intent("remind", "add_reminder", "schedule", {"text": what, "when": when_text}, what)
    return None
