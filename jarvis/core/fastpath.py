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
from jarvis.core.assist import LANG_ALT as _LANG_ALT  # any language: nepali, hindi, english, japanese, french...
from jarvis.core.assist import WHOLE_CODE

log = logging.getLogger("jarvis.fastpath")

I = re.I


@dataclass
class Intent:
    name: str  # time | weather | remember | recall | open | volume | brightness | mute | mic | media | screenshot | lock
    tool: str
    group: str
    args: dict = field(default_factory=dict)
    label: str = ""  # display name (app/site/place)
    known: str = ""  # the request's words that were CHECKED against the laptop (an installed app, a known site): the
    #                  meaning gate judges the action without them ('open settings' is an app, not window settings)


@dataclass
class FastResult:
    answer: str
    intent: Intent
    ok: bool
    latency_ms: int
    workspace: list[str] = field(default_factory=list)  # results saved for the dashboard's Workspace card
    jobs: list[int] = field(default_factory=list)  # background jobs the tool started (the UI watches them)


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


_TYPO_RX = re.compile(r"(?<![\w.])(?:" + "|".join(re.escape(k) for k in sorted(config.TYPO_FIXES, key=len, reverse=True))
                      + r")(?![\w])", re.I)


def normalize(text: str) -> str:
    t = " ".join((text or "").split())
    urls: list[str] = []  # links are kept exactly: typo fixes must never touch them ('?list=PLz' is not 'please')

    def hide(m: re.Match) -> str:
        urls.append(m.group(0))
        return f"\x00{len(urls) - 1}\x00"
    t = re.sub(r"https?://\S+", hide, t)
    t = _TYPO_RX.sub(lambda m: config.TYPO_FIXES[m.group(0).lower()], t) if config.TYPO_FIXES else t
    t = re.sub(r"\s*\.{2,}\s*", " ", t)  # "show me X .. send it" -> one sentence
    for pat, rep in config.STT_FIXES.items():  # the same mishearing fixes as voice ("tone of" -> "turn off")
        t = re.sub(pat, rep, t, flags=I)
    t = _LEAD.sub("", t, count=1)
    t = _DEVICE_TAIL.sub("", t)  # "take the screenshot of my display" = "take the screenshot"
    t = _TRAIL.sub("", t).strip(" ,")
    return re.sub(r"\x00(\d+)\x00", lambda m: urls[int(m.group(1))], t)


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

# --- date (separate from time: full date + weekday, Bikram Sambat by default) ---
# calendar tail, incl. common STT mishearings: "bikram samad/sambad", "vikram samvat", bare "sambat"
_CAL = (r"(?:(?: in| according to| as per| on)? (?:a\.?d\.?|b\.?s\.?|english|gregorian|international|"
        r"nepali|nepalese|hindu|(?:bikram|vikram) ?sam\w*|sam(?:bat|bad|vat|aad|ad)|angreji|"
        r"अंग्रेजी|अङ्ग्रेजी|(?:विक्रम|बिक्रम) ?सम्वत|ईस्वी|नेपाली))?")
_D = r"(?:date|day|weekday|din|gate|miti|tithi|baar)"
DATE_LOCAL = _rx(
    # "what is (the) date/day (today/of today/right now/is it) ...", "tell me the date", "say today's date"
    _TQ + r"(?:(?:can you |could you )?(?:tell|say|give)(?: me)? )?(?:what(?:'s| is| was| are)?|which)?\s*"
          r"(?:the |today'?s |todays |me the )*" + _D +
          r"(?:\s+(?:today|now|right now|of today|is it|is today|of the day|is this|of the week|is it today))?" + _CAL,
    # "which week is this", "what day of the week"
    _TQ + r"(?:what|which) (?:week|day of the week)(?: is (?:it|this|today|it today))?",
    r"(?:today'?s date|date today|what day today)" + _CAL,
    # Nepali / Hindi romanized + script
    r"(?:aaja?|आज)(?: ko| ka)? (?:kati gate|kun din|kun baar|kaun din|kya (?:din|tarikh|taarikh))(?: ho| hai| hun)?" + _CAL,
    r"(?:aajako|आजको) (?:miti|miti k ho|din)" + _CAL,
    r"आज (?:कति गते|कुन दिन|कुन बार|कौन सा दिन|क्या (?:दिन|तारीख))(?: हो| है)?" + _CAL,
    r"आजको मिति(?: के हो)?", r"मिति (?:कति|के हो)",
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


_HERE_LIST = re.compile(r"^(?:please\s+)?(?:(?:list|show(?:\s+me)?|give\s+me(?:\s+the)?(?:\s+list\s+of)?)\s+(?:all\s+)?(?:the\s+)?"
                        r"(?:files?|folders?|contents?|everything|items?)(?:\s+and\s+(?:files?|folders?))?\s+"
                        r"(?:here|in\s+(?:it|here|there|this(?:\s+folder)?|that(?:\s+folder)?|the\s+(?:previous|parent)\s+folder))|"
                        r"what(?:'s|\s+is)\s+(?:in\s+)?(?:here|inside(?:\s+it)?|in\s+it))\s*[.?!]*$", I)
_OPEN_REF = re.compile(r"^(?:please\s+)?(?:open|go\s+(?:back\s+)?to|show)\s+(?:me\s+)?(?P<r>it|this|that|this\s+folder|that\s+folder|"
                       r"the\s+folder|(?:the\s+)?previous\s+folder|(?:the\s+)?last\s+folder|(?:the\s+)?parent\s+folder)"
                       r"(?:\s+in\s+(?:the\s+)?(?:file\s+manager|files|laptop))?\s*[.?!]*$", I)
_IS_THERE = re.compile(r"^(?:(?:hello|hi|hey|ok|okay)\s+)?(?:please\s+)?(?:is\s+there|do\s+i\s+have|does)\s+(?:a\s+|an\s+|the\s+|any\s+)?(?P<q>.+?)\s+"
                       r"(?P<kind>folder|file|directory)(?:\s+(?:in|inside|under)\s+(?:the\s+|my\s+)?(?P<p>.+?))?(?:\s+exists?)?\s*[.?!]*$", I)


def here_intent(t: str) -> Intent | None:
    """Follow-ups on the CURRENT folder: 'list files here', 'what is in it', 'open it', 'go to the previous folder',
    'is there X folder (in Y)'."""
    if _HERE_LIST.match(t):
        ref = re.search(r"previous|parent", t, I)
        return Intent("listdir", "list_folder", "filesearch", {"path": f"{ref.group(0)} folder" if ref else "this"},
                      "this")
    if m := re.match(r"^(?:what(?:'s|\s+is)(?:\s+there)?\s+(?:in|inside)|(?:list|show)(?:\s+me)?|open)\s+(?:the\s+)?"
                     r"(?P<p>[\w .-]{2,40}?)(?:\s+(?:folder|directory))?\s*[?.!]*$", t, I):
        from jarvis.core import focus  # a sub-folder of the current folder named on its own: "what is in data"
        cur, want = focus.cwd(), m.group("p").strip()
        if cur is not None:
            from jarvis.core.paths import norm
            try:
                hit = next((e.name for e in cur.iterdir() if e.is_dir() and norm(e.name) == norm(want)), None)
            except OSError:
                hit = None
            if hit:
                tool = "open_folder" if t.lower().startswith("open") else "list_folder"
                return Intent("openfolder" if tool == "open_folder" else "listdir", tool, "filesearch",
                              {"name" if tool == "open_folder" else "path": str(cur / hit)}, hit)
    if re.search(r"\b(?:locked|encrypted|password[\s-]*protected)\b", t, I) and re.match(r"^(?:please\s+)?(?:open|unlock)\b", t, I):
        name = re.sub(r"^(?:please\s+)?(?:open|unlock)\s+(?:the\s+|my\s+)?|\b(?:locked|encrypted|password[\s-]*protected)\b|"
                      r"\s+(?:folder|file)$", "", t, flags=I).strip()
        return Intent("lock", "folder_lock", "filesearch", {"action": "unlock", "path": name or "this"}, name)
    if m := _OPEN_REF.match(t):
        r = m.group("r").lower()
        r = "previous folder" if re.search(r"previous|last", r) else "parent folder" if "parent" in r else "this"
        return Intent("openfolder", "open_folder", "filesearch", {"name": r}, r)
    if m := _IS_THERE.match(t):
        q = re.sub(r"^(?:my|the)\s+", "", m.group("q").strip(), flags=I)
        kind = "folder" if m.group("kind").lower() in ("folder", "directory") else "name"
        if "/" in q and not m.group("p"):
            path, q = q.rsplit("/", 1)
            return Intent("findfile", "find_files", "filesearch", {"query": q, "path": path, "kind": kind}, q)
        return Intent("findfile", "find_files", "filesearch",
                      {"query": q, "path": (m.group("p") or "").strip(), "kind": kind}, q)
    return None


def listdir_intent(t: str) -> Intent | None:
    if hi := here_intent(t):
        return hi
    m = _full(_LISTDIR, t)
    if not m:
        return None
    path = m.group("path").strip(" ,")
    if not path or len(path.split()) > 8 or re.search(r"\b(?:web|internet|google|youtube|news)\b", path, I):
        return None
    return Intent("listdir", "list_folder", "filesearch", {"path": path}, path)


# "send [me] [the] X folder/file [in Y] [to telegram]" — send a file/folder to Telegram (0 tokens)
_DEST = r"(?:telegram|telegra|phone|mobile)"
_TGDEST = r"(?:\s+(?:to|in|on|via|through)\s+(?:my\s+)?" + _DEST + r")"
_SENDLEAD = r"(?:(?:ok|okay|nice|yes|yeah|now|please|hey|fine|good)\s+)*(?:send|share|forward|upload)(?:\s+(?:me|us|the|my))*\s+"
# a location that is NOT the telegram destination, so "in telegram" is never read as the folder's location
_LOCP = r"(?!(?:my\s+)?" + _DEST + r"\b)(?P<loc>[\w /.\-]+?)"
SENDFILE = _rx(
    _SENDLEAD + r"(?P<target>.+?)\s+(?:folder|directory|file|document|zip|pdf|image|photo|video)s?"
    + r"(?:\s+(?:in|from|inside)\s+" + _LOCP + r")?" + _TGDEST + r"?",
    _SENDLEAD + r"(?P<target>[\w.\-]+(?:\s+[\w.\-]+){0,3}?)\s+(?:in|from|inside)\s+" + _LOCP + _TGDEST,
)
# "send this / send it / send that folder [to telegram]" -> whatever we were just talking about
_ANAPHORA_SEND = re.compile(
    r"^\s*(?:(?:ok|okay|nice|yes|yeah|now|please|hey|fine|good)\s+)*(?:send|share|forward|upload)"
    r"(?:\s+(?:me|us|it|this|that|the|them|my))*(?:\s+(?:folder|file|one|document|zip|essay|report|notes?|pdf|doc|"
    r"md\s+file|image|photo|picture|pic|screenshot|video|clip|song|audio|script|code))?"
    r"(?:\s+(?:again|also|too))?" + _TGDEST + r"?\s*[.!?]*$", I)


# "find/search/locate X [folder/file] [anywhere/in my laptop/on all disks]" -> search the whole laptop (0 tokens)
_FINDFILE = re.compile(
    r"^(?:please\s+)?(?:(?:can|could)\s+you\s+)?(?:find|search(?:\s+for)?|locate|look\s+for|where(?:'s| is| are)|"
    r"source|sarch|serch|serach)\s+(?:me\s+)?(?:the\s+|a\s+|my\s+|all\s+)?"
    r"(?P<q>.+?)"
    r"(?:\s+(?P<kind>folder|directory|dir|file|document)s?)?"
    # the ONLY trailing location allowed is the whole laptop; a scoped "X in <some folder>" is left to the LLM
    r"(?:\s+(?:(?:in|on|across|inside|throughout|from)\s+)?(?:my\s+|the\s+|this\s+|all\s+|entire\s+|whole\s+)*"
    r"(?:laptop|computer|pc|system|machine|disks?|drives?|storage|everywhere|anywhere))?\s*[.!?]*$", re.I)
# things that are NOT a file search even though they start with find/search/where
_NOT_FINDFILE = re.compile(r"^(?:my\s+)?(?:phone|mobile|iphone|android|laptop|computer|pc|it|this|that)$"
                           r"|\b(?:news|weather|time|price|who|what\s+is|meaning|define|online|internet|web|song|video\s+of)\b", re.I)


_FIND_SEND = re.compile(r"^(?P<find>.+?)\s+(?:and|then)\s+(?:also\s+)?(?:send|share|forward)\s+(?:it|this|that|them)?\s*"
                        r"(?:to\s+)?(?:me|my\s+(?:telegram|phone|mobile)|telegram)\b.*$", re.I)
_FILEISH = re.compile(r"\b[\w-]+\.[a-z0-9]{1,5}\b|\b(?:file|image|photo|picture|pic|folder|document|pdf|video|zip)\b", re.I)


def findfile_intent(t: str) -> Intent | None:
    if (fs := _FIND_SEND.match(t)) and _FILEISH.search(fs.group("find")) and (found := findfile_intent(fs.group("find"))) is not None:
        # 'look for naruto.jpg image in my laptop and send me': find it everywhere AND send it (the send tool searches)
        name = re.sub(r"\s+(?:image|picture|photo|file|document|video)$", "", found.args["query"], flags=re.I)
        return Intent("sendfile", "send_file_telegram", "telegram", {"path": name}, name)
    m = _FINDFILE.match(t)
    if not m:
        return None
    q = (m.group("q") or "").strip(" ,")
    # reject: not-a-file-search, too long, or a SCOPED search ("X in <folder>", "a/b") -> let the LLM pass a path
    kw = (m.group("kind") or "").lower()
    kind = "folder" if kw in ("folder", "directory", "dir") else "name" if kw in ("file", "document") else "any"
    if q and "/" in q and len(q.split()) <= 8 and not _NOT_FINDFILE.search(q):  # "look for Project1/clz_project"
        path, name = q.rstrip("/").rsplit("/", 1)
        return Intent("findfile", "find_files", "filesearch", {"query": name, "path": path or "/", "kind": kind}, name)
    sc = re.match(r"^(?P<n>.+?)\s+(?:folder\s+|file\s+)?(?:in|inside|under|within)\s+(?:the\s+|my\s+)?(?P<p>.+)$", q or "", I)
    if sc and len(q.split()) <= 8 and not _NOT_FINDFILE.search(q):  # "find report in project1"
        return Intent("findfile", "find_files", "filesearch", {"query": sc.group("n").strip(), "path": sc.group("p").strip(),
                                                               "kind": kind}, sc.group("n").strip())
    if not q or len(q.split()) > 6 or _NOT_FINDFILE.search(q) or re.search(r"\b(?:in|inside|under|within|from)\b|/", q):
        return None
    return Intent("findfile", "find_files", "filesearch", {"query": q, "kind": kind}, q)


def focus_is_anaphora(text: str) -> bool:
    from jarvis.core import focus
    return focus.is_anaphora(text)


def _focus_intent(said: str = "this") -> Intent | None:
    from jarvis.core import focus, workmem
    kind = workmem.kind_named(said)
    if kind not in ("", "folder", "file"):  # "send that video": the newest video this chat touched, or the AI asks
        ref = workmem.latest(kind)  # (never some folder)
        if ref is None:
            return None
    else:
        ref = focus.refer("this folder" if kind == "folder" else "this")  # the same order as every tool: a pasted
        # path, what's selected / open in Files when it's the latest app, then KURAMA's remembered folder
    fp = str(ref) if ref is not None else focus.get_path()  # it's the latest app, then KURAMA's remembered folder
    if not fp:
        return None
    return Intent("sendfile", "send_file_telegram", "telegram", {"path": fp}, fp.rstrip("/").rsplit("/", 1)[-1])


def sendfile_intent(t: str) -> Intent | None:
    if re.match(r"^\s*(?:(?:ok|okay|now|please)\s+)*(?:send|share|forward)\s+(?:me\s+)?(?:this|that|the|it|my)?\s*"
                r"(?:photo|picture|image|pic|wallpaper)(?:\s+(?:you\s+)?(?:made|generated|created))?" + _TGDEST + r"?\s*[.!?]*$", t, I):
        return Intent("sendlast", "send_last_result", "telegram", {"kind": "image"}, "image")
    if _ANAPHORA_SEND.match(t):  # "send this folder" / "send it to telegram"
        return _focus_intent(t)
    m = _full(SENDFILE, t)
    if not m:
        return None
    tgt = (m.group("target") or "").strip(" ,")
    loc = (m.groupdict().get("loc") or "").strip(" ,")
    if re.fullmatch(r"(?:my\s+)?" + _DEST, loc, I):  # "in telegram" wrongly captured as location
        loc = ""
    if not tgt or len(tgt.split()) > 6 or re.fullmatch(r"(?:a message|message|hi|hello)", tgt, I):
        return None
    if re.fullmatch(r"(?:a\s+|the\s+)?(?:camera|webcam|laptop\s+camera)", tgt, I):  # 'send me a camera photo' = the webcam
        return None
    if re.fullmatch(r"(?:it|that|this|them|the)", tgt, I) or focus_is_anaphora(tgt):  # 'this', 'this selected file'
        return _focus_intent(tgt)  # -> what is selected / open (it searched the disk for "this selected")
    path = f"{tgt} in {loc}" if loc else tgt
    return Intent("sendfile", "send_file_telegram", "telegram", {"path": path}, tgt)


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
        "set": _rx(r"(?:set|change|put|turn|make|keep) " + _VOL + r"(?: level)? (?:to |at )?" + _N + _PCT,
                   r"(?:volume|sound)(?: level)? (?:to |at )?" + _N + _PCT,
                   _VOL_HI + " " + _N + _PCT + " " + _DO_HI),
        "up": _rx(r"(?:turn|bump|crank) up " + _VOL + _BY, r"(?:turn|bump|crank) " + _VOL + " up" + _BY,
                  r"(?:increase|raise) (?:the )?(?:more )?(?:volume|sound)(?: more| a bit| a little)?" + _BY,
                  r"(?:volume|sound) up" + _BY, r"(?:make it )?louder",
                  _VOL_HI + " " + _UP_HI),
        "down": _rx(r"turn down " + _VOL + _BY, r"turn " + _VOL + " down" + _BY,
                    r"(?:decrease|lower|reduce) (?:the )?(?:more )?(?:volume|sound)(?: more| a bit| a little)?" + _BY,
                    r"(?:volume|sound) down" + _BY,
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
_VID = r"(?:[\s.,]+(?:the |my |this |that )?(?:music|song|video|movie|playback|youtube(?: video)?))"  # "Stop.playing video" (STT dot)
_VID_NE = r"(?:video|bhidiyo|भिडियो|भिडिओ|वीडियो|gaana|gana|गाना|गीत)"
SWITCHES = [  # (intent name, tool, group, args, patterns); first full match wins
    ("loc_history", "location_history", "system", {"device": "phone"}, _rx(
        r"(?:show |give me |see )?(?:my )?(?:phone|mobile)(?:'s)? (?:location |movement |travel )?history",
        r"where (?:has |did )(?:my |the )?(?:phone|mobile) (?:been|gone|go)(?: today| recently)?",
        r"(?:track|trace) (?:my |the )?(?:phone|mobile)(?:'s)? (?:movement|location history|trail)")),
    ("loc_history", "location_history", "system", {"device": "laptop"}, _rx(
        r"(?:show |give me |see )?(?:my )?(?:laptop|computer|pc)(?:'s)? (?:location |movement |travel )?history",
        r"where (?:has |did )(?:my |the )?(?:laptop|computer) (?:been|gone)(?: today| recently)?",
        r"(?:show |give me )?(?:my )?location history",
        r"(?:track|trace) (?:my |the )?(?:laptop|computer)(?:'s)? (?:movement|location history|trail)")),
    ("find_phone", "find_my_phone", "system", {"phone": "iphone"}, _rx(
        r"(?:find|locate|where(?:'s| is)|track|ring) (?:my |the )?(?:lost |missing )?iphone(?: now)?",
        r"find my (?:phone|mobile) \(?iphone\)?")),
    ("find_phone", "find_my_phone", "system", {"phone": "android", "want": "location"}, _rx(
        r"where(?:'s| is| are)? (?:my |the )?(?:phone|mobile(?: phone)?|android|cell\s*phone)(?: location| at| now| right now)?",
        r"(?:(?:what(?:'s| is)|give|send|show|get|tell)(?: me)?\s*)?(?:the )?(?:current |last |latest |live |real[\s-]?time )?location of (?:my |the )?"
        r"(?:phone|mobile(?: phone)?|android|cell\s*phone)(?: now)?",
        r"(?:give|send|show|get|tell)(?: me)?(?: the| my)? (?:phone|mobile)(?:'s)? (?:current |last |live )?location(?: now)?",
        r"(?:my |the )?(?:phone|mobile|android)(?:'s)? (?:current |last |live )?location(?: now)?",
        r"(?:(?:give|send|show|get|tell)(?: me)?\s*)?(?:the )?(?:middle|mid|little|live) version of (?:my |the )?(?:mobile|phone)(?: phone)?(?:,? right)?",
        r"(?:give|send|show|get|tell)(?: me)?(?: the| my)? (?:last |latest )?location (?:that |which )?(?:i |you )?(?:shared?|sent|got|received)"
        r"(?: (?:in|on|via|through|with you on) (?:the )?telegram)?",
        r"(?:the )?location (?:i |that i )?(?:shared?|sent) (?:in|on|via) (?:the )?telegram",
        r"(?:phone|mobile|मोबाइल|फोन) (?:kaha|kahan|कहाँ|कहां)(?: (?:cha|chha|xa|छ|hai|है))?")),
    ("find_phone", "find_my_phone", "system", {"phone": "android", "want": "open"}, _rx(
        r"(?:find|locate|track|ring) (?:my |the )?(?:lost |missing )?(?:phone|mobile(?: phone)?|android|cell\s*phone)(?: now)?",
        r"(?:open |launch )?(?:google )?find my (?:device|phone|mobile|android)",
        r"(?:phone|mobile|मोबाइल|फोन) (?:khoj|खोज)(?:\s\w+)?")),
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
        _SONG_HI + r" (?:roko|rok do|रोको|रोक दो|रोक|रोकिदेउ)",
        r"stop[\s.,]+playing(?: it)?" + _VID + "?", r"(?:stop|hold|freeze)" + _VID, r"(?:music|song|video|movie)[\s.,]+(?:pause|stop)",
        _VID_NE + r" (?:roka|roku|rok|roko|pause gara|pause garnu|रोक|रोका|रोकिदेउ|रोको|रोक दो|पज गर)")),
    ("media", "media_control", "media", {"action": "play"}, _rx(
        r"play", r"(?:resume|unpause)" + _MEDIA_OBJ, r"continue (?:playing|the (?:music|song|video))",
        r"(?:start|continue|keep|resume)(?:[\s.,]+play(?:ing)?)?" + _VID + r"(?: again| now)?",
        r"(?:start|continue|keep) playing(?: it)?", r"play it(?: again| now)?", r"play(?: the| this| that)? (?:video|movie)(?: again| now)?",
        r"(?:music|song|video|movie)[\s.,]+(?:play|resume|continue)",
        _VID_NE + r" (?:chalau|chalaa|chalao|chalu gara|play gara|चलाउ|चलाऊ|चलाओ|चलाइदेउ|फेरि चलाउ)")),
    ("media", "media_control", "media", {"action": "pause"}, _rx(  # slash forms (desktop + Telegram), 0 tokens
        r"/(?:pause|stop[-_]?video|hold)(?:\s+(?:the\s+)?(?:video|music|song|it))?")),
    ("media", "media_control", "media", {"action": "play"}, _rx(
        r"/(?:play|resume|continue|unpause)(?:\s+(?:the\s+)?(?:video|music|song|it))?")),
    ("media", "media_control", "media", {"action": "next"}, _rx(r"/(?:next|skip)(?:\s+(?:video|song|track))?")),
    ("media", "media_control", "media", {"action": "previous"}, _rx(r"/(?:prev|previous|back)(?:\s+(?:video|song|track))?")),
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
        r"lock (?:the |my |this )?(?:laptop(?:'s)? |computer(?:'s)? )?(?:screen|computer|pc|laptop|desktop|system|machine)(?: now)?",
        r"(?:screen|computer|laptop|स्क्रीन|स्क्रिन|कम्प्युटर|कंप्यूटर) (?:lock|लॉक|लक) " + _DO_HI)),
]


_MAXW = r"(?:max|maximum|full|highest|top|100\s*%)"
_MINW = r"(?:min|minimum|lowest|zero)"


def _levels_words(t: str) -> str:
    """'set the volume maximum' / 'full volume' / 'brightness to lowest' -> the same request with 100 / 0, so the
    fixed volume and brightness commands read them (11-01: 'Set the volume maximum.' went to the AI)."""
    for words, n in ((_MAXW, "100"), (_MINW, "0")):
        t = re.sub(r"\b" + words + r"\s+(volume|sound|brightness)\b", r"\1 " + n, t, flags=I)
        t = re.sub(r"\b(volume|sound|brightness)(\s+level)?\s+(?:to\s+|at\s+)?(?:the\s+)?" + words + r"\b",
                   r"\1\2 " + n, t, flags=I)
    return t


def _system_intent(t: str) -> Intent | None:
    t = _levels_words(t)
    for name, (tool, group, actions) in LEVELS.items():
        for action, pats in actions.items():
            if m := _full(pats, t):
                n = m.groupdict().get("n")
                args: dict = {"action": action}
                if action == "set":
                    if n is None or not 0 <= int(n) <= 150:  # up to 150 with Ubuntu's Over-Amplification
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
    r"who am i", r"what(?:'s| is) my name", r"tell me (?:what you know )?about (?:me|myself)", r"(?:show |what(?:'s| is) )?my profile",
    r"(?:timilai|tapai lai|tumhe|aapko) mero (?:barema|bare ma) (?:ke|kya) thaha (?:cha|xa|chha)",
)
NAME = _rx(
    r"(?:my name is|my name's|call me|you can call me|mero naam|mera naam|mero nam)\s+"
    r"(?P<name>[^\W\d_][\w'-]*(?: [^\W\d_][\w'-]*)?)(?: (?:ho|hai))?",
    r"(?:मेरो|मेरा) नाम (?P<name>\S+(?: \S+)?) (?:हो|है)",
)
_NAME_BAD = re.compile(r"\b(?:not|and|what|is|the|a|an|back|later|tomorrow|when|if|now|again|maybe|soon|please)\b", I)


_PM_WORDS = (("full", r"full(?:\s+power)?|max(?:imum)?(?:\s+power)?|all\s+power"), ("smart", r"best\s+ai|smart(?:est)?|best\s+brain"),
             ("normal", r"normal"), ("basic", r"basic"), ("lowram", r"low\s+ram|less\s+ram|ram\s+saver|lightweight"),
             ("laptop", r"laptop\s+only|general"), ("noai", r"no\s+ai|zero\s+token|offline|without\s+ai"))
_PM_ANY = "|".join(f"(?P<{k}>{v})" for k, v in _PM_WORDS)
POWER_MODE = re.compile(r"^(?:please\s+|kurama\W+|can\s+you\s+)*(?:(?:switch|change|go|put|set|turn|move)(?:\s+(?:kurama|yourself|it))?"
                        r"(?:\s+(?:on|back))?\s+(?:to|into|in|on)\s+|(?:enable|activate|use|start|turn\s+on)\s+)?(?:the\s+)?"
                        r"(?:" + _PM_ANY + r")\s+mode(?:\s+(?:on|please|now))?\s*[.!]*$", I)
POWER_STATUS = re.compile(r"^(?:what|which)\s+(?:power\s+)?mode\s+(?:are\s+you|is\s+kurama|am\s+i|is\s+on|is\s+it)(?:\s+(?:in|on|using))?"
                          r"(?:\s+now)?\s*\??$|^(?:current|kurama(?:'s)?)\s+(?:power\s+)?mode\s*\??$", I)


def power_mode_intent(t: str) -> Intent | None:
    """'switch to low ram mode', 'full power mode', 'no ai mode', 'what mode are you in' (0 tokens)."""
    if POWER_STATUS.match(t):
        return Intent("power_mode", "power_mode", "usage", {"mode": "status"})
    if m := POWER_MODE.match(t):
        return Intent("power_mode", "power_mode", "usage", {"mode": next(k for k, v in m.groupdict().items() if v)})
    if re.fullmatch(r"(?:please\s+)?(?:save|free\s+up|use\s+less)\s+(?:some\s+)?ram(?:\s+(?:please|now))?[.!]*", t, I):
        return Intent("power_mode", "power_mode", "usage", {"mode": "lowram"})
    return None


# --- alert mute: "don't send RAM warnings for 20 minutes", "mute all alerts for an hour", "unmute alerts" ---
_MUTE_KIND = (("resource", r"ram|memory|resource|cpu|swap|disk"), ("location", r"location|gps|tracking"),
              ("jobs", r"jobs?|tasks?"), ("downloads", r"downloads?"), ("digest", r"(?:daily\s+)?(?:summary|digest)"),
              ("reminders", r"reminders?|timers?"), ("guard", r"guard|theft"), ("internet", r"internet|wi-?fi|network"),
              ("all", r"all|every|any|other"), ("last", r"this|that|these|those|it|the same|such"))
_MUTE_NOUN = r"(?:alerts?|allots?|alarts?|warnings?|notifications?|notifs?|messages?|pings?|updates?|reports?)"
_MUTE_VERB = (r"(?:mute|silence|pause|snooze|stop|disable|turn\s+off|block|hold|hide|quiet|"
              r"(?:do\s*n[o']?t|dont|never)\s+(?:send|show|give|tell|ping|notify|bother|disturb)(?:\s+me)?(?:\s+with)?|"
              r"no\s+more|stop\s+(?:sending|showing|giving)(?:\s+me)?)")
_NUMW = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "ten": 10, "fifteen": 15,
         "twenty": 20, "thirty": 30, "forty": 40, "forty five": 45, "fifty": 50, "sixty": 60, "few": 5, "couple of": 2}
_MUTE_FOR = re.compile(r"\b(?:for|till|until)\s+(?:the\s+next\s+|next\s+)?(?P<half>half\s+an?\s+)?(?P<n>\d+(?:\.\d+)?|"
                       + "|".join(sorted(_NUMW, key=len, reverse=True)) + r")?\s*(?P<u>min(?:ute)?s?|m|hours?|hrs?|h|"
                       r"days?|today|tonight|the\s+day)\b", I)


def _mute_minutes(t: str) -> float | None:
    m = _MUTE_FOR.search(t) or re.search(r"\b(?P<u>today|tonight)\b(?P<half>)(?P<n>)", t, I)
    if not m:
        return None
    u = m.group("u").lower()
    if m.group("half"):
        return 30.0
    if u in ("today", "tonight", "the day"):
        end = time.localtime()
        return max(30.0, (23 - end.tm_hour) * 60 + (60 - end.tm_min))
    n = m.group("n")
    n = float(n) if n and n[0].isdigit() else float(_NUMW.get((n or "one").lower(), 1))
    return n * (1440 if u.startswith("d") else 60 if u.startswith("h") else 1)


def mute_intent(t: str) -> Intent | None:
    """0-token alert mute / unmute / status; the time is required unless an alert word is named."""
    low = t.lower().strip(" .!?")
    if re.fullmatch(r"(?:please\s+)?(?:which|what)\s+(?:alerts?|notifications?|warnings?)\s+(?:are|is)\s+(?:muted|"
                    r"paused|off|silenced|on|allowed|active)|(?:show\s+)?muted\s+(?:alerts?|notifications?)|(?:(?:show|check|tell|give)(?:\s+me)?\s+|"
                    r"what(?:'s|\s+is|\s+are)\s+)?(?:my\s+|the\s+|all\s+)?(?:notifications?|alerts?|warnings?)(?:\s+(?:status|settings))?", low) \
            and not re.fullmatch(r"(?:notifications?|alerts?|warnings?)", low):
        return Intent("mute", "mute_alerts", "telegram", {"action": "status"})
    if m := re.fullmatch(r"(?:please\s+)?unmute(?:\s+(?:the\s+|my\s+)?(?P<k>all|everything|ram|memory|resources?|location|jobs?|"
                         r"downloads?|todo|reminders?|guard|internet|backup))?(?:\s+(?:now|please))?", low):
        k = (m.group("k") or "all").lower()
        kind = next((n for n, rx in _MUTE_KIND if re.fullmatch(rx, k)), "all") if k not in ("everything", "todo") else \
            ("all" if k == "everything" else "todo")
        return Intent("mute", "mute_alerts", "telegram", {"action": "off", "what": kind})
    if m := (re.fullmatch(r"(?:please\s+)?(?:unmute|resume|turn\s+(?:back\s+)?on|enable|allow|bring\s+back)\s+(?:the\s+|my\s+)?"
                          r"(?P<k>\w+\s+)?" + _MUTE_NOUN + r"(?:\s+again|\s+back(?:\s+on)?)?(?:\s+please)?", low)
             or re.fullmatch(r"(?:please\s+)?turn\s+(?:the\s+|my\s+)?(?P<k>\w+\s+)?" + _MUTE_NOUN
                             + r"\s+(?:back\s+on|on\s+again)(?:\s+please)?", low)):
        k = (m.group("k") or "").strip()
        kind = next((n for n, rx in _MUTE_KIND if k and re.fullmatch(rx, k)), "all")
        return Intent("mute", "mute_alerts", "telegram", {"action": "off", "what": "all" if kind == "last" else kind})
    if not re.search(r"^(?:please\s+|kurama\W+|can\s+you\s+|i\s+want\s+you\s+to\s+)*" + _MUTE_VERB + r"\b", low):
        return None
    mins = _mute_minutes(low)
    noun = re.search(r"\b" + _MUTE_NOUN + r"\b", low)
    kinds = [n for n, rx in _MUTE_KIND if re.search(r"\b(?:" + rx + r")\b", low)]
    if not noun and re.search(r"\b(?:send|sending|show|give|tell|ping)\b", low) and (
            "location" in kinds or ("last" in kinds and mins)):
        noun = True  # "don't send (me) the location for 2 hours", "do not send this for 1 hour"
    if not noun and mins and [k for k in kinds if k not in ("last", "all")] and re.match(
            r"(?:please\s+)?(?:mute|silence|snooze|pause|quiet)\b", low):
        noun = True  # "mute ram for 20 min"
    if not noun or (mins is None and not kinds) or len(low.split()) > 16:
        return None  # "turn off notifications" = Do Not Disturb; "stop" alone = audio
    if re.search(r"\b(?:wifi|bluetooth|music|song|video|timer|alarm)\b", low) and "alert" not in low and mins is None:
        return None
    kind = next((k for k in kinds if k != "last"), "last" if "last" in kinds else "all")
    if kind == "all" and "last" in kinds and not re.search(r"\b(?:all|every|any)\b", low):
        kind = "last"
    return Intent("mute", "mute_alerts", "telegram", {"action": "on", "what": kind, "minutes": mins or 0})


_STOP_TRACK = re.compile(r"^(?:please\s+|kurama\W+)*(?:stop|end|turn\s+off|disable|cancel)\s+(?:the\s+)?(?:tracking|lost\s+mode|"
                         r"(?:sending(?:\s+me)?\s+)?(?:the\s+|my\s+)?(?:laptop(?:'s)?\s+)?location(?:\s+(?:messages?|updates?|alerts?))?)"
                         r"(?:\s+(?:for\s+)?(?:my|the|of\s+my|of\s+the)?\s*laptop)?(?:\s+(?:please|now))?\s*[.!]*$", I)
_WHERE_LAPTOP = re.compile(r"^(?:please\s+|kurama\W+)*(?:(?:give|tell|show|send)\s+me\s+|what(?:'s|\s+is)\s+)?(?:the\s+)?"
                           r"(?:(?:current\s+|live\s+)?location\s+of\s+(?:my\s+|the\s+)?laptop|(?:my\s+)?laptop(?:'s)?\s+location|"
                           r"where\s+is\s+my\s+laptop)(?:\s+(?:please|now))?\s*[.!?]*$", I)

_REQS = re.compile(r"^(?:please\s+|kurama\W+)*(?:generate|create|make|write|build)\s+(?:(?:a|the|new|my|me)\s+)*requirements?"
                   r"(?:\.txt)?(?:\s+file)?(?:\s+(?:for|of|in)\s+(?P<p>.+?))?[\s.!]*$|^requirements?(?:\.txt)?\s+(?:banao|bana\s+do|banau)[\s.!]*$", I)
_NB2PY = re.compile(r"^(?:please\s+|kurama\W+)*(?:convert|change|turn|export)\s+(?P<p>.+?\.ipynb|(?:this|the|my)\s+notebook|"
                    r"(?:this|the|my)\s+ipynb)\s+(?:in)?to\s+(?:a\s+)?(?:\.?py|python)(?:\s+(?:script|file))?[\s.!]*$", I)
_DEPS = re.compile(r"^(?:please\s+|kurama\W+)*(?:check|scan|audit|diagnose)\s+(?:the\s+|my\s+)?(?:dependencies|dependency|"
                   r"requirements|packages)(?:\s+(?:for|of|in)\s+(?P<p>.+?))?[\s.!?]*$", I)


def coding_intent(t: str) -> Intent | None:
    """'generate requirements.txt (for <project>)', 'convert this notebook to python', 'check dependencies' -> 0 tokens;
    no project named = the one open in VS Code."""
    from jarvis.tools.core.code import _notebook, _project
    if m := _REQS.match(t):
        return Intent("devutils", "generate_requirements", "devutils", {"path": _project({"path": m.group("p") or ""})})
    if m := _NB2PY.match(t):
        p = m.group("p")
        return Intent("devutils", "notebook_to_script", "devutils", {"path": _notebook({"path": "" if "notebook" in p.lower() or
                                                                                                 p.lower().endswith(" ipynb") else p})})
    if m := _DEPS.match(t):
        return Intent("deps", "dependency_doctor", "codequality", {"repo": _project({"path": m.group("p") or ""})})
    return None


def _p7_intent(t: str) -> Intent | None:
    if ci := coding_intent(t):
        return ci
    if _STOP_TRACK.match(t) and not _mute_minutes(t):  # lost mode is what sends location: switch it off
        return Intent("guard", "laptop_guard", "power", {"action": "track_off"})
    if _WHERE_LAPTOP.match(t):
        return Intent("guard", "laptop_guard", "power", {"action": "where"})
    if mu := mute_intent(t):
        return mu
    if pm := power_mode_intent(t):
        return pm
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
                    r"(?:an?\s+|the\s+)?(?:(?P<q>hd|high[\s-]quality|detailed|realistic|beautiful|nice|cool|cute|simple|4k|"
                    r"random|funny|any|surprise)\s+)?(?:ai\s+)?"
                    r"(?:image|picture|photo|pic|drawing|painting|illustration|artwork)s?"
                    r"(?:\s+(?:of|about|showing|with|for)\s+(?P<p>.{3,}))?$", I)  # no subject: 'a random image' (04e9edfd)
_DRAW = re.compile(r"^(?:can you\s+)?draw\s+(?:me\s+)?(?P<p>.{3,})$", I)


WALL_TAIL = re.compile(r"[\s,]*(?:\band\b|\bthen\b)?\s*(?:please\s+)?(?:make|set|use|keep|put|apply)\s+"
                       r"(?:it|this|that|the (?:image|picture|photo))?\s*(?:as\s+)?(?:my\s+|the\s+)?(?:desktop\s+)?"
                       r"(?:wallpaper|background)\b.*$", I)


TG_TAIL = re.compile(r"[\s,]*(?:\b(?:and|then)\b\s*)?(?:also\s+)?(?:please\s+)?(?:send|share|forward|get|put|drop|deliver)\s+"
                     r"(?:it|this|that|them|the (?:image|picture|photo|pic|file))?\s*(?:image|picture|photo|pic)?\s*"
                     r"(?:to|in|on|via|through)\s+(?:my\s+)?(?:telegram|phone|mobile)\b.*$", I)


_NWORD = {"two": 2, "three": 3, "four": 4, "2": 2, "3": 3, "4": 4, "a couple of": 2, "few": 3, "some": 3}
_DETAIL = re.compile(r",?\s*\b(?:in\s+)?(?:high\s+quality|hq|hd|ultra\s+detailed|highly\s+detailed|very\s+detailed|detailed|best\s+quality|"
                     r"better\s+quality)\b", I)


def music_intent(t: str) -> Intent | None:
    """Music without the browser (0 tokens): 'play lofi music', 'play kya mujhe pyar hai by KK', 'play <youtube link>',
    'play this playlist', 'save this playlist as study', 'play / shuffle my study playlist', 'show my playlists',
    'delete the study playlist', 'play my music' (~/Music), 'stop the music', 'music volume up', and plain
    'next' / 'skip' / 'previous' while the music plays."""
    from jarvis.core import music
    def mu(action, q="", shuffle=False):
        return Intent("music", "music", "media", {"action": action, "query": q, **({"shuffle": True} if shuffle else {})})
    low = t.strip(" .!?").lower()
    lead = r"(?:please\s+|kurama\W+|can\s+you\s+|hey\s+|now\s+|okay\s+|ok\s+)*"
    if re.fullmatch(lead + r"(?:next|skip|skip\s+(?:it|this)|next\s+one|another\s+one|change\s+(?:it|the\s+song))", low, I) and music.running():
        return Intent("media", "media_control", "media", {"action": "next"}, "media")
    if re.fullmatch(lead + r"(?:previous|back|go\s+back|last\s+one|play\s+(?:the\s+)?previous\s+one)", low, I) and music.running():
        return Intent("media", "media_control", "media", {"action": "previous"}, "media")
    bare = re.sub(r"\s*https?://\S+", "", low).strip()
    if m := re.fullmatch(lead + r"(?:save|store|keep)\s+(?:this|that|the)\s+(?:playlist|song|music|mix)\s+(?:as|in)\s+(?:my\s+)?(?P<n>[\w\s]+?)(?:\s+playlist)?", bare, I) \
            or re.fullmatch(lead + r"save\s+(?:this|that)\s+as\s+(?:my\s+)?(?P<n>[\w\s]+?)\s+playlist", bare, I):
        url = re.search(r"https?://\S+", t)
        return mu("save", m.group("n").strip() + ("|" + url.group(0) if url else ""))
    if re.fullmatch(lead + r"(?:show|list|what\s+are)\s+(?:me\s+)?(?:all\s+)?(?:my|the)\s+(?:saved\s+)?playlists?|my\s+playlists", low, I):
        return mu("playlists")
    if m := re.fullmatch(lead + r"(?:delete|remove)\s+(?:the\s+|my\s+)?(?P<n>[\w\s]+?)\s+playlist", low, I):
        return mu("delete", m.group("n"))
    if m := re.search(r"https?://(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)/\S+", t):
        if re.match(lead + r"(?:play|shuffle|listen\s+to)\b", low, I) and not re.search(r"\b(?:video|watch|download)\b", low):
            return mu("url", m.group(0), shuffle=low.startswith("shuffle"))
    if re.fullmatch(lead + r"(?:play|shuffle|listen\s+to)\s+(?:this|that)\s+(?:playlist|song|music|mix)", low, I):
        return mu("url", "", shuffle=low.startswith("shuffle"))
    if m := re.fullmatch(lead + r"(?P<v>play|shuffle|start|put\s+on)\s+(?:my|the)\s+(?P<n>[\w\s]+?)\s+playlist", low, I):
        return mu("playlist", m.group("n"), shuffle=m.group("v").lower() == "shuffle")
    if re.fullmatch(lead + r"(?:play|shuffle|start)\s+(?:my|the)\s+(?:saved\s+)?playlists?", low, I):
        return mu("playlists")
    if re.fullmatch(lead + r"(?:play|shuffle)\s+(?:my\s+(?:own\s+)?(?:music|songs)|(?:the\s+)?(?:songs|music)\s+(?:on|from|in)\s+(?:my\s+)?(?:laptop|computer|pc|music\s+folder)|"
                    r"my\s+(?:downloaded|offline)\s+(?:songs|music)|offline\s+music)", low, I):
        return mu("local")
    if music.running() and not re.search(r"\b(?:system|laptop|computer|speakers?|device|mic|microphone|brightness)\b", low):
        if m := re.fullmatch(lead + r"(?:(?:increase|raise|turn\s+up|louder|more)\s+(?:the\s+)?(?:music\s+|song\s+)?(?:volume|sound)?"
                             r"|(?:the\s+)?(?:music\s+|song\s+)?(?:volume|sound)\s+(?:up|higher|louder)|louder(?:\s+please)?|turn\s+it\s+up)"
                             r"(?:\s+by\s+(?P<n>\d{1,3}))?(?:\s+(?:a\s+(?:bit|little)|please|more))*", low, I):
            return Intent("music", "music", "media", {"action": "volume_up", "query": m.group("n") or ""})
        if m := re.fullmatch(lead + r"(?:(?:decrease|lower|reduce|turn\s+down|quieter|less)\s+(?:the\s+)?(?:music\s+|song\s+)?(?:volume|sound)?"
                             r"|(?:the\s+)?(?:music\s+|song\s+)?(?:volume|sound)\s+(?:down|lower)|(?:softer|quieter)(?:\s+please)?|turn\s+it\s+down)"
                             r"(?:\s+by\s+(?P<n>\d{1,3}))?(?:\s+(?:a\s+(?:bit|little)|please|more))*", low, I):
            return Intent("music", "music", "media", {"action": "volume_down", "query": m.group("n") or ""})
        if m := re.fullmatch(lead + r"(?:set\s+)?(?:the\s+)?(?:music\s+)?volume\s+(?:to\s+)?(?P<n>\d{1,3})\s*%?", low, I):
            return Intent("music", "music", "media", {"action": "volume_set", "query": m.group("n")})
    if re.search(r"\b(?:youtube|video|videos|movie|spotify)\b", t, I) or len(t.split()) > 16:
        return None
    if re.fullmatch(lead + r"(?:stop|turn\s+off|switch\s+off|end|kill|close)\s+(?:the\s+|my\s+|this\s+)?(?:music|songs?|playing\s+music)(?:\s+now|\s+please)?"
                    r"|(?:music|gana|गाना)\s+(?:off|band\s+gara|banda\s+gara|बन्द\s+गर)", t, I):
        return mu("stop") if music.running() else None  # no music of ours: 'stop the music' pauses the browser
    if m := re.fullmatch(lead + r"(?:turn\s+)?(?:the\s+)?music\s+(?:volume\s+)?(?P<d>up|down|louder|quieter|softer)", t, I):
        return mu("volume_up" if m.group("d").lower() in ("up", "louder") else "volume_down")
    t = re.sub(r"[\s,]+(?:buddy|bro|brother|dude|yaar|dai|bhai|man|my\s+friend|kurama|please|now)[\s.!?]*$", "", t, flags=I)
    shuffle = bool(re.match(lead + r"shuffle\b", low, I))
    if m := re.fullmatch(lead + r"(?:play|shuffle|put\s+on|start|listen\s+to|i\s+want\s+to\s+listen\s+to|bajau|bajaau)\s+(?:me\s+)?(?:some\s+|a\s+|the\s+)?"
                         r"(?P<q>.*?)\s*(?P<k>music|songs?|playlist|mix|beats|lofi|gana|गाना|geet|bhajan|ghazal)(?:\s+(?:please|now|for\s+me))?[\s.!]*", t, I):
        q = f"{m.group('q')} {m.group('k')}".strip()
        if re.match(r"my\s+", q, I):
            return None  # 'play my playlist' / 'my songs': handled above or the saved playlists
        if re.fullmatch(r"(?:music|songs?|playlist|gana|गाना)", q, I):
            q = "relaxing music"
        return mu("play", q, shuffle)
    if m := re.fullmatch(lead + r"(?:play|shuffle)\s+(?P<q>.+?)\s+by\s+(?P<a>[\w .'-]+)", t, I):  # 'play kya mujhe pyar hai by KK'
        return mu("play", f"{m.group('q')} {m.group('a')}", shuffle)
    if m := re.fullmatch(lead + r"(?:listen\s+to|i\s+want\s+to\s+listen\s+to)\s+(?P<q>.+)", t, I):
        return mu("play", m.group("q").strip(" ."))
    return None


def video_make_intent(t: str) -> Intent | None:
    """'make a short video about the Himalayas' / 'make a reel about tea' / 'make a video with this script: ...' /
    'make a slideshow from ~/Pictures/trip' / '/video <topic>' -> make_video."""
    if m := re.fullmatch(r"/(?:makevideo|reel)(?:\s+(?P<a>.+))?", t, I | re.S):
        return Intent("makevideo", "make_video", "image", {"topic": (m.group("a") or "").strip(), "vertical": t.lower().startswith("/reel")})
    if not re.search(r"\b(?:make|create|generate|produce)\b", t, I) or not re.search(r"\b(?:video|reel|reels|short|shorts|slideshow|slide\s+show)\b", t, I):
        return None
    if re.search(r"\b(?:download|record|screen\s+record|camera|youtube\s+video\s+of|convert)\b", t, I):
        return None
    vertical = bool(re.search(r"\b(?:reel|reels|shorts|vertical|tiktok|story)\b", t, I))
    if m := re.search(r"\b(?:slide\s*show|video)\s+(?:from|of|with)\s+(?:the\s+|my\s+)?(?:pictures|photos|images)\s+(?:in|from|of)\s+(?P<f>.+)$"
                      r"|\bslide\s*show\s+(?:from|of)\s+(?P<g>.+)$", t, I):
        return Intent("makevideo", "make_video", "image", {"folder": (m.group("f") or m.group("g")).strip(" ."), "vertical": vertical})
    if m := re.search(r"\b(?:script|narration|story)\s*[:\-]\s*(?P<s>.+)$", t, I | re.S):
        return Intent("makevideo", "make_video", "image", {"script": m.group("s").strip(), "vertical": vertical})
    if m := re.search(r"\b(?:video|reel|short|shorts)\s+(?:about|on|of|explaining|showing|for)\s+(?P<t>.{3,})$", t, I):
        return Intent("makevideo", "make_video", "image", {"topic": m.group("t").strip(" ."), "vertical": vertical})
    return None


def audio_intent(t: str) -> Intent | None:
    """'make an audio of this' / 'read this as mp3' / 'convert this text to speech' / 'turn the last result into audio'
    / 'make an mp3 of https://...' / 'make an audio of: hello' / '/audio [link|file|text]' -> make_audio (0 tokens)."""
    if m := re.fullmatch(r"/(?:audio|mp3|speak)(?:\s+(?P<a>.+))?", t, I | re.S):
        a = (m.group("a") or "").strip()
        src = a if re.match(r"https?://|[~/]|.+\.(?:txt|md|pdf)$", a, I) else ("text" if a else "selection")
        return Intent("audio", "make_audio", "image", {"source": src, "text": a if src == "text" else ""})
    if not re.search(r"\b(?:audio|mp3|audiobook|podcast|text\s+to\s+speech|speech|voice\s+file|sound\s+file)\b", t, I) \
            or re.search(r"\b(?:video|youtube|song|music|movie|record|recording|mic|microphone|download)\b", t, I) \
            or re.search(r"\.(?:mp4|mkv|webm|avi|mov|wav|m4a|flac|ogg)\b", t, I):
        return None
    if not re.search(r"\b(?:make|create|turn|convert|change|read|generate|give|save|export|produce)\b", t, I):
        return None
    if m := re.search(r"https?://\S+", t):
        return Intent("audio", "make_audio", "image", {"source": m.group(0).rstrip(".,)")})
    if m := re.search(r"((?:~|/)[^\s]+\.(?:txt|md|pdf)|[\w.-]+\.(?:txt|md|pdf))\b", t, I):
        return Intent("audio", "make_audio", "image", {"source": m.group(1)})
    if m := re.search(r"(?:audio|mp3|speech)\s+(?:of|for|saying|that\s+says)\s*:\s*(?P<x>.+)", t, I | re.S):
        return Intent("audio", "make_audio", "image", {"source": "text", "text": m.group("x").strip()})
    if re.search(r"\b(?:last|latest|newest)\s+(?:result|answer|document|doc|essay|file|output)|\bworkspace\b|\bthe\s+(?:essay|article|report|notes?)\b", t, I):
        return Intent("audio", "make_audio", "image", {"source": "last"})
    if re.search(r"\b(?:this|that|it|selected|highlighted|the\s+selection|these)\b", t, I) and len(t.split()) <= 16:
        return Intent("audio", "make_audio", "image", {"source": "selection"})
    return None


def diagram_intent(t: str) -> Intent | None:
    """'make a diagram of this project' / 'diagram of the kurama project' / 'flowchart: login, check password, open
    the dashboard' / 'diagram of this code' / '/diagram' / '/flow steps' -> make_diagram (0 tokens)."""
    def d(kind, target=""):
        return Intent("diagram", "make_diagram", "image", {"kind": kind, "target": target})
    if m := re.fullmatch(r"/(?:diagram|flow|flowchart|callgraph)(?:\s+(?P<a>.+))?", t, I):
        cmd = t.split()[0].lower()
        return d("flow" if cmd.startswith("/flow") else "code" if cmd == "/callgraph" else "project", (m.group("a") or "").strip())
    if not re.search(r"\b(?:diagram|flow\s*chart|flow\s+diagram|mind\s*map|call\s+graph|architecture\s+(?:picture|diagram))\b", t, I) \
            or len(t.split()) > 60 or re.search(r"\bwhat\s+is\s+an?\b", t, I):
        return None
    if m := re.search(r"\b(?:flow\s*chart|flow\s+diagram|diagram)\s*(?:of|for|showing)?\s*(?:these|the|my|this)?\s*(?:steps|process|flow)?\s*[:\-]\s*(?P<s>.+)", t, I):
        return d("flow", m.group("s"))
    if m := re.search(r"\b(?:flow\s*chart|flow\s+diagram)\s+(?:of|for)\s+(?P<s>.+(?:,|->|→|\bthen\b).+)", t, I):
        return d("flow", m.group("s"))
    if re.search(r"\b(?:this|my|the)\s+(?:code|file|script|module)\b|\bcall\s+graph\b|\bfunctions?\b", t, I):
        p = re.search(r"([\w./~-]+\.py)\b", t)
        return d("code", p.group(1) if p else "")
    if m := re.search(r"\bproject\s+(?:at|in)\s+(?P<p>(?:~|/)\S+)|\b(?:the\s+|my\s+)(?P<n>[\w-]+)\s+project\b|(?P<q>(?:~|/)\S+)", t, I):
        tgt = m.group("p") or m.group("q") or ("" if (m.group("n") or "").lower() in ("this", "current", "whole") else m.group("n") or "")
        return d("project", tgt or "")
    if re.search(r"\b(?:project|repo|repository|readme|app)\b", t, I):
        return d("project")
    return None


def chart_intent(t: str) -> Intent | None:
    """'chart my expenses (this week)', 'pie chart of my spending', 'make a chart from sales.csv', 'draw a graph of
    population by district from https://...', '/chart <file|link>' -> make_chart (0 tokens to route)."""
    if not re.search(r"\b(?:chart|charts|graph|graphs|plot|visuali[sz]e|pie|histogram)\b", t, I) or len(t.split()) > 40:
        return None
    kind = "pie" if re.search(r"\bpie\b", t, I) else "line" if re.search(r"\bline\s+(?:chart|graph)\b", t, I) else \
        "bar" if re.search(r"\bbar\s+(?:chart|graph)\b", t, I) else "all" if re.search(r"\b(?:all|different|every)\s+(?:views?|kinds?|types?|charts?)\b", t, I) else "auto"
    url = re.search(r"https?://\S+", t)
    path = re.search(r"(?:^|\s)((?:~|/)[^\s]+\.(?:csv|tsv|xlsx|xlsm|json)|[\w.-]+\.(?:csv|tsv|xlsx|xlsm|json))\b", t, I)
    if url or path:
        src = (url.group(0) if url else path.group(1)).rstrip(".,)")
        return Intent("chart", "make_chart", "image", {"source": src, "request": t.replace(src, " ").strip(), "kind": kind})
    if re.search(r"\b(?:expenses?|spending|spent|money|kharcha)\b", t, I) and re.search(r"\b(?:my|the)\b", t, I):
        return Intent("chart", "make_chart", "image", {"source": "money", "kind": kind, "period": _period(t)})
    return None


def image_intent(t: str) -> Intent | None:
    """+ '4 versions of a fox', 'same picture but at night', 'another version', 'make it more colorful' (right after a
    picture), 'detailed / HD' -> the service improves the prompt."""
    from jarvis.tools.general import generate_image as gi
    if m := re.fullmatch(r"(?:please\s+|can\s+you\s+)?(?:make|draw|generate|create|give\s+me|show\s+me)\s+(?:me\s+)?(?P<n>2|3|4|two|three|four|a\s+couple\s+of|few|some)\s+"
                         r"(?:different\s+)?(?:versions?|images?|pictures?|variations?|options?|designs?|photos?)\s+(?:of|for|showing|with)\s+(?P<p>.{3,})", t, I):
        p = m.group("p").strip(" .,!?")
        return Intent("image", "generate_image", "image", {"prompt": _DETAIL.sub("", p).strip(), "count": _NWORD[m.group("n").lower()],
                                                           **({"detailed": True} if _DETAIL.search(p) else {})}, p)
    if m := re.fullmatch(r"(?:please\s+)?(?:(?:make|draw|generate|give\s+me|show\s+me|create)\s+)?(?:the\s+|that\s+)?same\s+(?:picture|image|one|photo)\s+but\s+(?P<c>.+)", t, I):
        return Intent("image", "generate_image", "image", {"prompt": m.group("c").strip(" .!"), "change_last": True}, "same picture")
    if re.fullmatch(r"(?:please\s+)?(?:make|draw|generate|give\s+me|show\s+me|create|try)\s+(?:me\s+)?(?:another|a\s+new|a\s+different|one\s+more)"
                    r"(?:\s+(?:version|one|variation|picture|image|try))?(?:\s+of\s+(?:it|that|this))?[\s.!]*", t, I) and gi.last_recent():
        return Intent("image", "generate_image", "image", {"prompt": "another version", "change_last": True}, "another version")
    if (m := re.fullmatch(r"(?:please\s+)?(?:now\s+)?make\s+(?:it|the\s+(?:picture|image))\s+(?P<c>(?:at|in|more|less|a\s+bit|darker|brighter|"
                          r"colou?rful|bigger|smaller|with|without|look|night|day|sunset|winter|summer|rain).+)", t, I)) and gi.last_recent():
        return Intent("image", "generate_image", "image", {"prompt": m.group("c").strip(" .!"), "change_last": True}, "change")
    wall = bool(WALL_TAIL.search(t))
    t = WALL_TAIL.sub("", t) if wall else t
    tg = bool(TG_TAIL.search(t))
    t = TG_TAIL.sub("", t) if tg else t
    m = _IMAGE.match(t) or _DRAW.match(t)
    if not m or re.search(r"\b(?:and|then)\s+(?:send|open|set)\b", t, I):  # multi-step: let the planner split it
        return None
    prompt = (m.group("p") or "").strip(" .,!?")
    q = m.groupdict().get("q")
    if not prompt and not q:
        return None  # 'generate an image': of what? (the AI asks)
    if not prompt:  # 'generate a random image': KURAMA picks the subject (the AI wrote a 1x1 PNG by hand, 7,897 tokens)
        prompt = "a surprising, beautiful scene of anything" if q.lower() in ("random", "any", "surprise") \
            else f"something {q}"
    elif q:  # 'an HD image of', 'a realistic photo of': the quality/style belongs to the prompt
        prompt = f"{prompt}, {q}"
    detailed = bool(_DETAIL.search(prompt))
    prompt = _DETAIL.sub("", prompt).strip(" ,") or prompt
    args = {"prompt": prompt, **({"set_as_wallpaper": True} if wall else {}), **({"send_to_telegram": True} if tg else {}),
            **({"detailed": True} if detailed else {})}
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
_RESET = re.compile(
    r"^(?:please\s+)?(?:(?P<all>reset|wipe|factory\s*reset)(?:\s+(?:kurama|everything|all|yourself))?"
    r"|(?:clear|forget|wipe|delete|erase|start)\s+(?:a\s+)?(?:new\s+)?"
    r"(?:(?P<recent>(?:the\s+)?(?:recent|reminders?(?:\s+and\s+(?:chat|cache))?|cache))|"
    r"(?:the\s+|this\s+|our\s+|my\s+)?(?:chat|conversation|chat\s+history|memory\s+of\s+(?:this\s+)?chat))"
    r"|(?:new\s+chat|start\s+over|start\s+fresh|start\s+a\s+new\s+chat))\s*[.!?]*$", re.I)
_COLAB_SETUP = re.compile(
    r"^(?:(?:please |now )?(?:set\s*up|setup|connect|link|configure|enable|start|get|give me)\s+)"
    r"(?:(?:the|my|a)\s+)?(?:google\s+)?colab(?:\s+(?:cell|notebook|training|tracking|watch|monitor|link|"
    r"for\s+(?:track(?:ing)?|watch(?:ing)?|monitor(?:ing)?)(?:\s+training)?))?\s*[.!?]*$"
    r"|^(?:google\s+)?colab\s+(?:set\s*up|setup|cell|link|tracking|connect)\s*[.!?]*$", re.I)
_TRAIN_Q = re.compile(r"^(?:what(?:'s| is) the |how many |which )?(?:current |latest )?(?:accuracy|acc|loss|epochs?|val(?:idation)?"
                      r"(?:accuracy|loss))(?: (?:now|so far|is it(?: on)?|done|completed|finished|are done|of (?:my |the )?"
                      r"(?:model|training)))*$", I)
_TRAIN_STOP = re.compile(r"^(?:please )?(?:stop|end|cancel|kill|halt) (?:the |my )?(?:model )?(?:training|train(?:ing)? run|"
                         r"colab(?: training| run)?)(?P<now> (?:right )?now| immediately| at once)?$", I)


def _study_intent(t: str) -> Intent | None:
    if _STATUS.match(t):
        return Intent("status", "status_now", "usage", {})
    from jarvis.core.remotedesk import START_RE, STOP_RE, CHANGE_RE
    if STOP_RE.match(t):
        return Intent("remote", "remote_desktop", "system", {"stop": True})
    if START_RE.match(t) or CHANGE_RE.match(t):
        return Intent("remote", "remote_desktop", "system", {})
    if m := _RESET.match(t):
        lvl = "all" if m.group("all") else ("recent" if m.group("recent") else "chat")
        return Intent("reset", "reset_kurama", "self", {"level": lvl})
    if _COLAB_SETUP.match(t):
        return Intent("training", "training", "watch", {"action": "colab"})
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


_VID_SITES = r"(?:youtube\.com|youtu\.be|vimeo\.com|facebook\.com|fb\.watch|instagram\.com|tiktok\.com|x\.com|twitter\.com|dailymotion\.com)"
_VDL = re.compile(r"^(?:please\s+)?(?:download|save|get)\s+(?:me\s+)?(?P<det>the\s+|this\s+|that\s+|a\s+)?(?P<pl>(?:whole\s+)?playlist\s+)?"
                  r"(?:(?:youtube|yt)\s+)?(?P<kind>video|movie|film|song|music|audio|mp3|clip|playlist)?"
                  r"(?:\s+(?:of|called|named|for))?\s*(?P<src>.*?)"
                  r"(?:\s+(?:from|on)\s+youtube)?"
                  r"(?:\s+(?:in|at|with)\s+(?:the\s+)?(?P<q>4k|2k|\d{3,4}\s*p?|full\s+hd|hd|fhd|best|high|good|extra\s+high|highest|max(?:imum)?|ultra(?:\s+hd)?|top)(?:\s+qu\w*)?)?"
                  r"(?P<aud>\s+(?:as|in|to)\s+(?:an?\s+)?(?:mp3|audio|music|sound\s+only))?"
                  r"(?:\s+(?:with|and)\s+(?:the\s+)?(?:sound|audio))?$", I)
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
    if re.match(r"(?:please\s+)?(?:save|store|keep)\s+(?:this|that|the)\s+(?:playlist|song|music|mix)\s+as\b|save\s+(?:this|that)\s+as\s+(?:my\s+)?\w+\s+playlist", t, I) \
            and (mi := music_intent(t)):  # a playlist to keep, not a download
        return mi
    if vd := video_dl_intent(t):
        return vd
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
    if ia := app_install_intent(t):
        return ia
    if m := _INSTALL.match(t):
        pkg = m.group("p")
        if pkg.lower() in ("it", "this", "that", "them"):  # "install it" right after a ModuleNotFoundError
            last = store._exec("SELECT error FROM errors WHERE sig=?", (store.kv_get("errmem_last") or "",))
            pkg = last[0][0] if last and "No module named" in last[0][0] else ""
        if pkg and pkg.lower() not in ("app", "the"):
            return Intent("install", "python_env", "dev", {"action": "install", "package": pkg,
                                                           "folder": m.group("f") or "."})
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
        return Intent("code", "where_was_i", "git", {"project": m.group("p") or m.group("p2") or m.group("p3") or ""})
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
    if re.search(r"\d", t) and re.search(r"[a-z]", t, I):  # said in words: '30 percent of 100', '5 times 6'
        from jarvis.tools.general.calculate import spoken_math
        if (sm := spoken_math(t)) != t and (m := _MATH.match(sm)) and re.search(r"[+\-*/×÷^%]|sqrt", sm):
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


_CONV = re.compile(r"^(?:please\s+)?(?:convert|change|turn|transform|save|export)\s+(?P<src>.+?)\s+"
                   r"(?:in\s*to|to|as|into)\s+(?:an?\s+)?\.?(?P<to>[a-z0-9]{2,10})(?:\s+(?:file|format|files))?$", I)
_CONV2 = re.compile(r"^(?:please\s+)?(?:make|create|give\s+me)\s+(?:an?\s+)?(?P<to>pdf|md|markdown|png|jpg|mp3|mp4|gif|"
                    r"docx|xlsx|csv|txt)(?:\s+file)?\s+(?:of|from|out\s+of)\s+(?P<src>.+)$", I)
_ALL_IN = re.compile(r"^(?:all\s+)?(?:the\s+)?(?P<ext>[a-z0-9]{2,5})\s+(?:files|images|photos|pictures|videos|songs)?"
                     r"\s*(?:in|inside|from)\s+(?:the\s+|my\s+)?(?P<dir>.+?)(?:\s+folder)?$", I)


def convert_intent(t: str) -> Intent | None:
    """'convert this pdf into md file', 'convert notes.md to pdf', 'convert all jpg in downloads to png'."""
    from jarvis.core import convert as cv
    m = _CONV.match(t) or _CONV2.match(t)
    if not m:
        return None
    to = cv.ext_of(m.group("to"))
    known = cv.IMAGES | cv.MEDIA | cv.OFFICE | cv.TABLES | cv.TEXTS | {"pdf", "gif"}
    if to not in known:
        return None
    src = re.sub(r"\s+(?:file|document|doc)$", "", m.group("src").strip(), flags=I)
    if re.match(r"^(?:on|off|up|down|speech|voice|my\s+voice|audio\s+input)\b", src, I):
        return None  # "turn on speech to text" is dictation, not a file conversion
    if a := _ALL_IN.match(src):
        if cv.ext_of(a.group("ext")) in known:
            return Intent("convert", "convert_file", "daily", {"path": a.group("dir"), "to": to,
                                                               "src_ext": cv.ext_of(a.group("ext"))})
    words = src.split()
    ext = ""
    if words and cv.ext_of(words[-1]) in known and not re.search(r"\.\w+$", src):
        ext = cv.ext_of(words[-1])  # "this pdf", "report pdf", "my resume docx"
        src = " ".join(words[:-1])
    src = re.sub(r"^(?:the|my|this|that|these)\s+", lambda x: "this " if x.group(0).strip().lower() in
                 ("this", "that", "these") else "", src, flags=I).strip()
    if src.lower() in ("", "this", "it", "that"):
        src = "this"
    return Intent("convert", "convert_file", "daily", {"path": src, "to": to, "src_ext": ext})


_PY_HINT = re.compile(r"\b(?:pip|module|library|package|python|requirements|venv)\b", I)
_PY_COMMON = {"numpy", "pandas", "scipy", "matplotlib", "seaborn", "sklearn", "scikit-learn", "torch", "tensorflow",
              "keras", "transformers", "requests", "flask", "fastapi", "django", "langchain", "openai", "groq",
              "opencv-python", "cv2", "pillow", "tqdm", "pytest", "jupyter", "notebook", "streamlit", "gradio",
              "xgboost", "lightgbm", "nltk", "spacy", "sympy", "plotly", "beautifulsoup4", "bs4", "selenium",
              "playwright", "uvicorn", "pydantic", "sqlalchemy", "faiss-cpu", "fastembed", "datasets", "accelerate"}
_APP_INSTALL = re.compile(r"^(?:please\s+)?(?:install|download\s+and\s+install|set\s+up)\s+(?:the\s+|a\s+)?"
                          r"(?P<n>[\w .+-]{2,40}?)(?:\s+(?:app|application|software|program))?(?:\s+on\s+(?:my\s+)?"
                          r"(?:laptop|computer|pc))?$", I)
_APP_REMOVE = re.compile(r"^(?:please\s+)?(?:uninstall\s+(?:the\s+)?(?P<a>[\w .+-]{2,40}?)(?:\s+app)?|remove\s+(?:the\s+)?"
                         r"(?P<b>[\w .+-]{2,40}?)\s+(?:app|application|software|program))$", I)
_APP_UPDATE = re.compile(r"^(?:please\s+)?(?:update|upgrade)\s+(?:all\s+)?(?:(?:my|the)\s+)?(?:apps|applications|"
                         r"everything|system|software|packages|laptop|ubuntu)(?:\s+(?:apps|packages))?$", I)


def app_install_intent(t: str) -> Intent | None:
    """'install obs', 'install vs code', 'uninstall zoom', 'update all apps'. Python packages stay with python_env."""
    if _APP_UPDATE.match(t):
        return Intent("app", "install_app", "apps", {"action": "update", "name": ""})
    if m := _APP_REMOVE.match(t):
        n = (m.group("a") or m.group("b")).strip()
        return Intent("app", "install_app", "apps", {"action": "remove", "name": n}, known=n)
    m = _APP_INSTALL.match(t)
    if not m or _PY_HINT.search(t):
        return None
    name = m.group("n").strip()
    if (name.lower() in _PY_COMMON or name.lower() in ("it", "this", "that", "them") or re.search(r"[=<>\[]", name)
            or re.search(r"\s(?:in|into|for)\s", name, I)):  # "install timm in my project" = a Python package
        return None
    name = re.sub(r"\s+(?:bro|pls|please|plz|now)$", "", name, flags=I)
    # "install X" says what it is, so X is judged out of the meaning; "set up X" may be a project ("set up a fastapi
    # skeleton", test round 1): there the whole sentence must mean installing
    explicit = re.match(r"(?:please\s+)?(?:install|download\s+and\s+install)\b", t, I) is not None
    return Intent("app", "install_app", "apps", {"action": "install", "name": name}, known=name if explicit else "")


_WIFI = r"(?:wi[\s-]*fi|wifi|lan|local\s+network|hotspot)"
_WSHARE = re.compile(r"^(?:please\s+)?(?:(?:share|send|transfer|give)\s+(?P<a>.+?)\s+(?:to\s+(?:my\s+)?(?:phone|mobile)\s+)?"
                     r"(?:over|via|by|through|on|using)\s+(?:the\s+)?" + _WIFI + r"|" + _WIFI +
                     r"\s+(?:share|send|transfer)\s+(?P<b>.+?))$", I)
_WSTOP = re.compile(r"^(?:please\s+)?(?:stop|end|close|turn\s+off)\s+(?:the\s+)?(?:" + _WIFI +
                    r"\s+(?:share|sharing|transfer)|sharing(?:\s+(?:over|via|on)\s+" + _WIFI + r")?)$", I)


def wifi_share_intent(t: str) -> Intent | None:
    """'send this folder to my phone over wifi', 'share report.pdf via wifi', 'stop wifi share'."""
    if _WSTOP.match(t):
        return Intent("wifi", "wifi_share", "telegram", {"action": "stop", "path": ""})
    if m := _WSHARE.match(t):
        src = re.sub(r"^(?:the|my)\s+", "", (m.group("a") or m.group("b")).strip(), flags=I)
        src = re.sub(r"\s+(?:folder|file|directory)$", "", src, flags=I) if not src.lower().startswith(
            ("this", "that", "it")) else "this"
        return Intent("wifi", "wifi_share", "telegram", {"action": "share", "path": src})
    return None


_PH = r"(?P<p>\+?\d[\d\s-]{4,18}\d)"
_CNAME = r"(?P<n>[^\d]{1,40}?)"
_C_ADD = [re.compile(r"^(?:please\s+)?(?:save|add|store|remember|note(?:\s+down)?|write\s+down|keep)\s+(?:a\s+|new\s+)*(?:contact\s+)?" + _CNAME +
                     r"(?:'s|s'|\s+ko)?\s+(?:(?:phone|mobile|cell)\s+)?(?:number|no\.?|contact)?\s*(?:is|as|:|=)?\s*" + _PH +
                     r"(?:\s+(?:as|note)\s+(?P<note>.+))?$", I),
          re.compile(r"^(?:please\s+)?(?:save|add|store)\s+" + _PH + r"\s+(?:as|for)\s+" + _CNAME + r"(?:'s)?(?:\s+number)?$", I),
          re.compile(r"^" + _CNAME + r"(?:'s|s')\s+(?:(?:phone|mobile)\s+)?number\s+is\s+" + _PH + r"$", I)]
_C_FIND = [re.compile(r"^(?:please\s+)?(?:what(?:'s|\s+is)\s+|give\s+me\s+|tell\s+me\s+|send\s+me\s+|find\s+|get\s+|show\s+(?:me\s+)?)?"
                      r"(?:the\s+)?" + _CNAME + r"(?:'s|s'|\s+ko)\s+(?:(?:phone|mobile|cell|contact)\s+)?(?:number|no\.?|contact)\s*\??$", I),
           re.compile(r"^(?:please\s+)?(?:what(?:'s|\s+is)\s+|give\s+me\s+|tell\s+me\s+|find\s+|get\s+)?(?:the\s+)?"
                      r"(?:(?:phone|mobile|contact)\s+(?:number|no\.?|details?)|contact)\s+(?:of|for)\s+" + _CNAME + r"\s*\??$", I),
           re.compile(r"^(?:please\s+)?(?:find|search|look\s+up)\s+(?:the\s+)?contact\s+" + _CNAME + r"$", I),
           re.compile(r"^(?:please\s+)?(?:what(?:'s|\s+is)|give\s+me|tell\s+me|send\s+me|get\s+me)\s+" + _CNAME +
                      r"\s+(?:(?:phone|mobile)\s+)?(?:number|no\.?|contact)\s*\??$", I)]
_C_LIST = re.compile(r"^(?:please\s+)?(?:show|list|open|give\s+me)\s+(?:all\s+)?(?:of\s+)?(?:my\s+|the\s+)?(?:contacts|contact\s+list|phone\s+book|phonebook)$", I)
_C_DEL = re.compile(r"^(?:please\s+)?(?:delete|remove)\s+(?:the\s+)?contact\s+" + _CNAME + r"$", I)
_C_UPD = re.compile(r"^(?:please\s+)?(?:change|update|edit)\s+" + _CNAME + r"(?:'s|s')?\s+(?:(?:phone|mobile)\s+)?number\s+to\s+" + _PH + r"$", I)
_C_STOP = {"my", "your", "his", "her", "their", "our", "the", "this", "that", "a", "an", "it", "phone", "mobile",
           "kurama", "jarvis", "you", "me", "tracking", "order", "account", "roll", "registration", "serial"}


def contacts_intent(t: str) -> Intent | None:
    """'save Ram's number 9800000000', 'what is Ram's number', 'phone number of Sita', 'show my contacts'."""
    def ok(n: str) -> bool:
        n = n.strip(" ,.?")
        return bool(n) and n.lower().split()[0] not in _C_STOP and len(n.split()) <= 4
    if _C_LIST.match(t):
        return Intent("contact", "contacts", "memory", {"action": "list"})
    if (m := _C_UPD.match(t)) and ok(m.group("n")):
        return Intent("contact", "contacts", "memory", {"action": "update", "name": m.group("n").strip(), "phone": m.group("p")})
    if (m := _C_DEL.match(t)) and ok(m.group("n")):
        return Intent("contact", "contacts", "memory", {"action": "delete", "name": m.group("n").strip()})
    for rx in _C_ADD:
        if (m := rx.match(t)) and ok(m.group("n")):
            note = (m.groupdict().get("note") or "").strip()
            return Intent("contact", "contacts", "memory", {"action": "add", "name": m.group("n").strip(" ,"),
                                                            "phone": m.group("p"), "note": note})
    for rx in _C_FIND:
        if (m := rx.match(t)) and ok(m.group("n")):
            return Intent("contact", "contacts", "memory", {"action": "find", "name": m.group("n").strip(" ,.?")})
    return None


_DAYW = r"(?:the\s+|today'?s?\s+|tonight'?s?\s+|last\s+|latest\s+|yesterday'?s?\s+|recent\s+|live\s+)*"
_LIVE_SPORT = [re.compile(r"^(?:please\s+)?(?:what(?:'s|\s+is|\s+was)\s+|tell\s+me\s+|give\s+me\s+|show\s+(?:me\s+)?|check\s+)?(?:the\s+)?"
                          r"(?:live\s+|final\s+|latest\s+)?(?:score|result)s?\s+(?:of|in|for|from)\s+" + _DAYW +
                          r"(?P<t>.+?)(?:\s+(?:match|game|fixture))?(?:\s+today|\s+tonight|\s+now)?\??$", I),
               re.compile(r"^(?:please\s+)?(?:what(?:'s|\s+is)\s+)?(?:the\s+)?" + _DAYW +
                          r"(?P<t>[^?]{3,40}?)\s+(?:match|game)?\s*(?:score|result|scores|results|live\s+score)"
                          r"(?:\s+today|\s+now|\s+tonight)?\??$", I),
               re.compile(r"^(?:did|has|have)\s+(?P<t>.+?)\s+(?:win|won|lose|lost|draw|drawn|beat|play|played)\b.*$", I),
               re.compile(r"^who\s+won\s+(?:the\s+|today'?s?\s+|last\s+|yesterday'?s?\s+)*(?P<t>.+?)(?:\s+(?:match|game))?(?:\s+today|\s+yesterday)?\??$", I),
               re.compile(r"^when\s+(?:is|does|do|will)\s+(?:the\s+)?(?:next\s+)?(?P<t>.+?)(?:'s)?\s+(?:next\s+)?"
                          r"(?:match|game|play(?:ing)?(?:\s+next)?|fixture)(?:\s+next)?\??$", I),
               re.compile(r"^(?:is|are)\s+(?P<t>.+?)\s+playing\s+(?:today|tonight|now)\??$", I),
               # "tell me today man united match", "man united match today", "what happened in the X game"
               re.compile(r"^(?:please\s+)?(?:(?:tell|show|give)\s+(?:me\s+)?(?:about\s+)?|what\s+happened\s+(?:in|to)\s+|"
                          r"how\s+(?:was|is|did)\s+|update\s+(?:on|me\s+on)\s+|any\s+update\s+on\s+)?" + _DAYW +
                          r"(?P<t>[^?]{3,40}?)(?:'s)?\s+(?:match|game|fixture)(?:\s+(?:today|tonight|yesterday|now|go|end))?\??$", I),
               re.compile(r"^how\s+did\s+(?P<t>.+?)\s+(?:do|play|perform)(?:\s+(?:today|tonight|yesterday))?\??$", I),
               re.compile(r"^(?P<t>[a-z .'-]{3,30}?)\s+(?:vs\.?|versus|v)\s+[a-z .'-]{3,30}(?:\s+(?:today|score|result|match))?\??$", I)]
_LIVE_NEWS = re.compile(r"^(?:please\s+)?(?:(?:what(?:'s|\s+is)\s+the\s+|give\s+me\s+(?:the\s+)?|show\s+(?:me\s+)?(?:the\s+)?|"
                        r"tell\s+me\s+(?:the\s+)?)?(?:latest|today'?s|recent|top|breaking|current)\s+)?(?:news|headlines)"
                        r"(?:\s+(?:about|on|for|from|in|of)\s+(?P<t>.+?))?(?:\s+today|\s+now)?\??$", I)
_LIVE_PRICE = re.compile(r"^(?:please\s+)?(?:what(?:'s|\s+is|\s+are)\s+|tell\s+me\s+|give\s+me\s+|check\s+|how\s+much\s+is\s+)?(?:the\s+)?"
                         r"(?:today'?s\s+|current\s+|latest\s+|live\s+)?(?:(?:price|rate|cost|value)\s+of\s+.{2,40}|"
                         r".{2,40}?\s+(?:price|rate|prices|rates|bhau|भाउ)|exchange\s+rates?)"
                         r"(?:\s+(?:in|of)\s+nepal)?(?:\s+(?:today|now|right\s+now|currently))?\??$", I)
_FRESH = re.compile(r"\b(?:today|tonight|now|right\s+now|current|currently|latest|recent|recently|this\s+(?:week|month|year)|"
                    r"live|so\s+far|yet|breaking|just\s+(?:now|announced|happened))\b", I)
_ASK = re.compile(r"^(?:what|who|whom|which|when|where|how|is|are|was|were|did|does|has|have|will|tell\s+me|give\s+me|any)\b", I)
_NOT_FRESH = re.compile(r"\b(?:you|your|yourself|my|me|i|we|our|kurama|jarvis|time|date|day|weather|battery|volume|"
                        r"brightness|training|traning|epoch|accuracy|loss|it|status|progress|usage|tokens?|ram|cpu|memory|disk|storage|wifi|internet|location|laptop|computer|pc|system|process|processes|app|apps|job|jobs|reminder|alarm|timer|download|file|folder|code|project)\b", I)


def fresh_intent(t: str) -> Intent | None:
    """LAST resort before the LLM: a question about something current ('who is leading the election now',
    'latest iphone price', 'is the airport open today') -> live_search answer from minutes-fresh sources."""
    if len(t.split()) < 3 or not _ASK.match(t) or not _FRESH.search(t) or _NOT_FRESH.search(t):
        return None
    return Intent("live", "live_search", "web", {"query": t, "kind": "auto"})


_LIVE_SPORT_MIX = re.compile(r"\b(?:match|game|khel|score|result|natija|नतिजा)\b", I)
_MIX_ASK = re.compile(r"\b(?:k|ke|kya|kasto|kesto|kati)\s+(?:vayo|bhayo|bhaye|hua|huwa|cha|xa)\b|\b(?:jityo|haryo|jita|hara)\b|"
                      r"\b(?:aja|aaja|aaj|hijo|kal)\b.*\b(?:ko|ka|ki)\b", I)
_NOT_TEAM = re.compile(r"^(?:my|the|this|that|it|your|our|test|tests|training|model|exam|search|regex|file|files|"
                       r"find|open|close|install|launch|start|run|compare|best|perfect|exact|a|an|pattern|string|"
                       r"build|code|job|jobs|download|backup|query)\b", I)


_TIME_WX = re.compile(r"^(?:please\s+)?(?:(?:what(?:'s|\s+is)|tell\s+me|give\s+me)\s+)?(?:the\s+)?(?:current\s+)?"
                      r"(?:time\s+(?:and|in|&|plus)\s+(?:the\s+)?(?:weather|whether|order|wether)|"
                      r"(?:weather|whether)\s+(?:and|&|plus)\s+(?:the\s+)?time)"
                      r"(?:\s+(?:right\s+now|now|today))?(?:\s+(?:in|of|at|for)\s+(?P<place>[^,?]+?))?"
                      r"(?:\s+(?:right\s+now|now|today))?(?:\s+and\s+.*)?\??$", I)


def time_weather_intent(t: str) -> Intent | None:
    """'what is the time and weather right now (in Nepal)'; STT often hears 'time in the weather' / 'time and order'."""
    m = _TIME_WX.match(t)
    if not m:
        return None
    place = _place(m.group("place")) if m.group("place") else ""
    if place is None or (place and place.lower() in ("nepal", "here", "my place", "my location")):
        place = ""  # local (KURAMA is in Nepal): the default weather/time
    return Intent("weather", "weather", "weather", {"place": place, "days": 1, "_time": True}, place)


_HELLO = re.compile(r"^(?:hi+|hello+|hey+|hii+|yo|namaste|namaskar|नमस्ते|good\s+(?:morning|afternoon|evening))"
                    r"(?:\s+(?:kurama|jarvis|there|buddy|bro|sir))?(?:[\s,.!]+(?:how\s+are\s+you(?:\s+doing)?|how\s+r\s+u|"
                    r"what\s+are\s+you\s+doing|what'?s\s+up|sup)[\s?.!]*)*[\s?.!]*$", I)
_HOWRU = re.compile(r"^(?:how\s+are\s+you(?:\s+doing)?(?:\s+today)?|how\s+r\s+u|what'?s\s+up|k\s+cha|kasto\s+cha|"
                    r"kaise\s+ho|sanchai\s+(?:hunuhunchha|cha)|what\s+are\s+you\s+doing)[\s?.!]*$", I)
_THANKS = re.compile(r"^(?:ok(?:ay)?\s+)?(?:thanks?(?:\s+(?:a\s+lot|so\s+much|you|bro|kurama))*|thank\s+you(?:\s+(?:so\s+much|kurama))?|"
                     r"dhanyabad|dhanyavaad|shukriya|thx|ty|great|nice|good\s+job|well\s+done|perfect|awesome|cool)[\s!.]*$", I)
_OKAY = re.compile(r"^(?:ok(?:ay)?|k|fine|alright|got\s+it|hmm+|mm+h?|oh+|ah+)[\s!.]*$", I)
_BYE = re.compile(r"^(?:bye|good\s*bye|good\s+night|see\s+you(?:\s+later)?|ta\s*ta)(?:\s+kurama)?[\s!.]*$", I)
_KILL = re.compile(r"^(?:please\s+)?(?:kill|force\s+(?:quit|close|stop)|terminate)\s+(?:the\s+)?(?P<a>[\w .+-]{2,30}?)"
                   r"(?:\s+(?:app|application|process|window))?[\s.!]*$", I)
_TOP_PROC = re.compile(r"\b(?:top|biggest|heaviest|most|which|what)\b.{0,30}\b(?:memory|ram|cpu)\b.{0,30}\b(?:process|processes|apps?|"
                       r"programs?)\b|\b(?:process|apps?)\b.{0,20}\busing\s+(?:the\s+)?most\s+(?:memory|ram|cpu)\b", I)
_SLOW = re.compile(r"\b(?:laptop|computer|pc|system)\b.{0,25}\b(?:slow|lag+y?|lagging|hang(?:ing)?|stuck|heating)\b|"
                   r"^(?:please\s+)?(?:clean|clear|speed\s+up|optimi[sz]e|boost)\s+(?:up\s+)?(?:my\s+|the\s+)?"
                   r"(?:laptop|computer|pc|system|ram|memory)\b", I)
_TRAIN_ST = re.compile(r"^(?:give\s+me\s+|what(?:'s|\s+is)\s+|show\s+(?:me\s+)?)?(?:the\s+)?(?:current\s+)?"
                       r"(?:status\s+of\s+(?:the\s+|my\s+)?training|training\s+status)[\s?.!]*$", I)
_CUR_STATUS = re.compile(r"^(?:what(?:'s|\s+is)\s+(?:the\s+)?current\s+status|current\s+status|status)[\s?.!]*$", I)
_DIGEST2 = re.compile(r"^(?:please\s+)?summari[sz]e\s+(?:my\s+)?(?:today|the\s+day|today'?s?\s+day|my\s+day)"
                      r"(?:\s+(?:till|until|so\s+far|up\s+to)\s*(?:now)?)?[\s.!]*$", I)
_WHERE_PATH = re.compile(r"^(?:give\s+me\s+|tell\s+me\s+|what(?:'s|\s+is)\s+)?(?:the\s+)?(?:exact\s+|full\s+)?path"
                         r"(?:\s+of\s+(?:that|this|the|it)(?:\s+(?:folder|file|one))?)?[\s?.!]*$|"
                         r"^where\s+is\s+(?:that|this|it)(?:\s+(?:folder|file))?[\s?.!]*$", I)


# "can you fix this sentence?", "fix the format of this sentence more good", "correct the highlighted text please":
# any rewrite verb + anything that points at text, unless it is about code/errors/the laptop
_RW_VERB = re.compile(r"\b(?:fix|correct|improve|rewrite|re-?write|rephrase|reword|polish|format|edit|proof-?read|clean\s+up|"
                      r"make\s+(?:it|this|that)\s+(?:better|good|nice|nicer|formal|professional|polite|clear)|paraphrase|"
                      r"simplify|shorten|translate|grammar)\b", I)
_RW_OBJ = re.compile(r"\b(?:this|it|that|sentence|sentences|text|paragraph|line|lines|selection|selected|highlighted|message|"
                     r"email|mail|wording|words|grammar|spelling|para)\b", I)
_RW_NOT = re.compile(r"\b(?:error|errors|bug|bugs|code|crash|traceback|exception|laptop|computer|wifi|internet|sound|"
                     r"audio|mic|camera|screen|brightness|test|tests|file|folder|pdf|docx?|png|jpe?g|mp[34]|installation|"
                     r"build|server|issue\s+with|problem\s+with|reminder|alarm|time|date)\b", I)
_SEL = r"(?:this|it|that|the\s+selected\s+text|the\s+selection|selected\s+text|selection|this\s+(?:text|paragraph|line|sentence|email|message))"
_REWRITE = re.compile(r"^(?:please\s+)?(?:make\s+" + _SEL + r"\s+(?:more\s+)?(?:formal|informal|polite|professional|simple|simpler|"
                      r"shorter|longer|clear(?:er)?|friendly|casual|concise|better|nicer|funny|serious)|"
                      r"(?:fix|correct|check)\s+(?:the\s+)?(?:grammar|spelling|typos?)(?:\s+(?:of|in)\s+" + _SEL + r")?(?:\s+" + _SEL + r")?|"
                      r"(?:shorten|summari[sz]e|simplify|paraphrase|rephrase|rewrite|improve|polish|expand)\s+" + _SEL +
                      r"(?:\s+.{1,40})?|translate\s+" + _SEL + r"\s+(?:in)?to\s+\w+(?:\s+\w+)?)[\s.!]*$", I)


_SELREF = (r"(?:(?:this|that|these|the)\s+(?:whole\s+|entire\s+|full\s+|complete\s+)?(?:selected\s+|selective\s+|highlighted\s+)?"
           r"(?:word|words|sentence|sentences|paragraph|paragraphs|text|line|lines|part|passage|question|phrase|section|"
           r"code|function|thing|para)|this|it|that|these|the\s+selected(?:\s+\w+)?|the\s+highlighted(?:\s+\w+)?|"
           r"selected\s+\w+|highlighted\s+\w+|the\s+selection|what\s+i\s+(?:selected|highlighted))")
_LANGW = r"(?:in|into|to)\s+(?:" + _LANG_ALT + r")"
_A_EXPLAIN = re.compile(r"^(?:please\s+|kurama\W+|can\s+you\s+|could\s+you\s+)*(?:explain(?:\s+me)?|what\s+(?:does|do|is)\s+"
                        + _SELREF + r"\s+(?:mean|meaning|saying|say|talking\s+about|about|doing|do)|what\s+is\s+(?:the\s+)?meaning\s+of\s+"
                        r"(?:this|that|the)\s+(?:sentence|line|paragraph|question|passage|text)|i\s+(?:don'?t|do\s+not|can'?t)\s+"
                        r"understand)\b(?P<rest>.*)$", I)
_A_MEANING = re.compile(r"^(?:please\s+|kurama\W+|can\s+you\s+)*(?:(?:what(?:'s|\s+is)\s+)?(?:the\s+)?(?:meaning|artha|matlab)\s+of\s+"
                        r"(?P<x>.+?)|(?P<y>.+?)\s+(?:ko|को)\s+(?:meaning|artha|अर्थ|matlab)(?:\s+k(?:e|a|ya)\s*(?:ho|hai|cha)?)?|"
                        r"(?:what\s+does\s+)?(?P<z>[\w'-]{2,30})\s+(?:mean|means))(?:\s+" + _LANGW + r")?\s*\??$", I)
_A_TRANSLATE = re.compile(r"^(?:please\s+|kurama\W+|can\s+you\s+)*translate\s+(?P<x>.+?)\s+(?:in|into|to)\s+(?P<l>"
                          + _LANG_ALT + r")(?:\s+language)?(?P<r>\s+and\s+replace(?:\s+it)?|\s+(?:in\s+place|here))?\s*[.!]*$", I)
_A_CODEFIX = re.compile(r"\b(?:improve|optimi[sz]e|fix|refactor|format|clean\s+up|modify|change|update|edit|enhance|expand|rewrite|"
                        r"correct|add\s+(?:comments|docstrings|type\s+hints)\s+to|"
                        r"simplify|speed\s+up|debug|make\s+(?:it|this)\s+(?:faster|cleaner|better))\b.*\b(?:code|function|class|"
                        r"method|script|loop|query|component)\b", I)
_A_WRITE = re.compile(r"^(?:please\s+|kurama\W+|can\s+you\s+|now\s+)*(?:write|create|generate|add|make|implement|code)\s+(?:me\s+)?"
                      r"(?:the\s+|a\s+|an\s+|some\s+)?(?:\w+\s+){0,3}?(?:code|function|class|program|script|method|component|"
                      r"endpoint|api|calculator|algorithm)\b.*$", I)
_A_FILE = re.compile(r"^(?:please\s+|can\s+you\s+)*(?:explain|summari[sz]e|what\s+(?:is|does))\s+(?:me\s+)?(?:the\s+)?(?P<f>this\s+file|"
                     r"(?:file\s+)?[\w./~-]+\.(?:py|js|ts|jsx|tsx|java|c|cpp|h|go|rs|php|rb|kt|sql|sh|md|txt|ipynb|html|css|json|yaml|yml))"
                     r"(?:\s+(?:do|does|about))?(?:\s+" + _LANGW + r")?\s*\??$", I)


_A_BARE_SEL = re.compile(r"^(?:(?:this|that|the)\s+(?:selected\s+|highlighted\s+)?(?:word|one|phrase|term)|(?:the\s+)?"
                         r"(?:selected|highlighted)\s+(?:word|one|phrase|term)|this\s+selected\s+\w+|"
                         r"(?:the\s+)?(?:word|one)\s+i\s+(?:selected|highlighted|select))[\s.!?]*$", I)
_A_POINT = re.compile(r"\b(?:this|that|these|selected|highlighted|i\s+select(?:ed)?)\b", I)
_A_NOT_SEL = re.compile(r"\b(?:error|errors|traceback|exception|warning|file|folder|project|life|world|song|movie|dream|"
                        r"message\s+from|notification|alert)\b|\bmy\s+name\b", I)


_TIDY_FILE = r"(?P<f>(?:this|my|the)\s+(?:whole\s+|entire\s+|full\s+|python\s+)?(?:code|file|script|program)(?:\s+file)?|" \
             r"[\w./~-]+\.(?:py|pyi|json))"


_DEC_KIND = {"json": "json", "jwt": "jwt", "token": "jwt", "base64": "base64", "base 64": "base64", "url": "url",
             "link": "url", "timestamp": "timestamp", "time stamp": "timestamp", "epoch": "timestamp", "html": "html",
             "unicode": "unicode", "xml": "xml", "hex": "hex"}
_DEC_K = "|".join(sorted(map(re.escape, _DEC_KIND), key=len, reverse=True))


def decode_intent(t: str) -> Intent | None:
    """'decode this', 'decode this base64', 'prettify this json', 'what time is this timestamp',
    'encode this to base64', 'url encode this' -> decode_text (0 tokens)."""
    sel = r"(?:this|that|it|the\s+selected(?:\s+text)?|the\s+selection|selected\s+text)"
    if m := re.fullmatch(r"(?:please\s+)?(?:(?P<k1>base\s?64|url)\s+encode\s+" + sel + r"|encode\s+" + sel +
                         r"\s+(?:to|in|into|as)\s+(?P<k2>base\s?64|url(?:\s+encoding)?))[\s.!]*", t, I):
        k = (m.group("k1") or m.group("k2") or "").lower()
        return Intent("decode", "decode_text", "devutils", {"mode": "encode_url" if k.startswith("url") else "encode_base64"})
    if m := re.fullmatch(r"(?:please\s+|can\s+you\s+)*(?:decode|unescape|parse|prettify|pretty[\s-]?print|beautify|format|"
                         r"convert|read)\s+" + sel + r"(?:\s+(?P<k>" + _DEC_K + r"))?(?:\s+(?:string|text|code|data|value|token))?"
                         r"(?:\s+(?:to|into)\s+(?:a\s+)?(?:date|time|readable(?:\s+\w+)?|text|json))?[\s.!?]*", t, I):
        k = (m.group("k") or "").lower()
        if not k and not re.match(r"(?:please\s+|can\s+you\s+)*(?:decode|unescape|parse|pretty)", t, I):
            return None  # "format this" / "convert this" alone: other tools
        return Intent("decode", "decode_text", "devutils", {"mode": _DEC_KIND.get(k, "auto")})
    if re.fullmatch(r"(?:what\s+(?:time|date)\s+is\s+(?:this|that)(?:\s+(?:timestamp|epoch|unix\s+time))?|"
                    r"(?:url|base\s?64|jwt)\s+decode\s+" + sel + r")[\s.?!]*", t, I):
        k = "timestamp" if re.match(r"what", t, I) else re.match(r"(url|base\s?64|jwt)", t, I).group(1).lower().replace(" ", "")
        return Intent("decode", "decode_text", "devutils", {"mode": k})
    return None


def code_tidy_intent(t: str) -> Intent | None:
    """'format my code / this file / main.py', 'check this file', 'lint my code', 'any errors in this file',
    'fix the problems' -> code_tidy (ruff, 0 tokens)."""
    def path(m):
        f = (m.groupdict().get("f") or "").strip()
        return f if re.search(r"\.\w+$", f) else ""
    if m := re.fullmatch(r"(?:please\s+|can\s+you\s+)*(?:format|beautify|indent|reformat|prettify|pretty\s+print|tidy(?:\s+up)?|"
                         r"clean\s+up\s+the\s+formatting\s+of|fix\s+the\s+(?:formatting|indentation)\s+(?:of|in))\s+"
                         + _TIDY_FILE + r"(?:\s+please)?[\s.!?]*", t, I):
        return Intent("tidy", "code_tidy", "codequality", {"action": "format", "path": path(m)})
    if m := (re.fullmatch(r"(?:please\s+|can\s+you\s+)*(?:check|lint|scan)\s+" + _TIDY_FILE +
                          r"(?:\s+for\s+(?:errors|problems|mistakes|bugs))?[\s.!?]*", t, I)
             or re.fullmatch(r"(?:are\s+there\s+(?:any\s+)?|any\s+)(?:errors|problems|mistakes)\s+in\s+" + _TIDY_FILE + r"\s*\??",
                             t, I)):
        return Intent("tidy", "code_tidy", "codequality", {"action": "check", "path": path(m)})
    if re.fullmatch(r"(?:please\s+)?fix\s+(?:the|those|these|all\s+the|all)\s+(?:problems|lint\s+errors|errors|issues)"
                    r"(?:\s+(?:in\s+(?:this|my|the)\s+(?:file|code)|safely))?[\s.!]*", t, I):
        return Intent("tidy", "code_tidy", "codequality", {"action": "fix", "path": ""})
    return None


_NAV_OBJ = r"(?:function|func|method|class|definition|def|code|implementation|source)"


_PERIOD = (("today", r"\btoday|aaja|आज\b"), ("yesterday", r"\byesterday|hijo|हिजो\b"),
           ("last_month", r"\blast\s+month|previous\s+month|gayeko\s+mahina\b"),
           ("week", r"\b(?:this\s+|the\s+|per\s+|a\s+)?week(?:ly)?\b|\bhapta\b"),
           ("year", r"\b(?:this\s+|the\s+|per\s+)?year(?:ly)?\b|\bbarsa\b"),
           ("month", r"\b(?:this\s+|the\s+|per\s+)?month(?:ly)?\b|\bmahina\b|महिना"))
_MONEY_AMT = r"(?:rs\.?\s*|npr\s*|रु\.?\s*)?\d[\d,]*(?:\.\d+)?\s*(?:k\b|thousand|hajar)?\s*(?:rs|rupees?|npr)?"


def _money_period(t: str, default: str = "month") -> str:
    """A date range said in words ('from Oct 1 to Oct 15', 'on the 20th', 'last 10 days') wins over 'this month'."""
    from jarvis.core import expenses as ex
    if r := ex.dates_in(re.sub(r"\b(?:today|yesterday)\b", "", t, flags=I)):
        return ex.range_period(*r)
    return _period(t, default)


def _period(t: str, default: str = "month") -> str:
    return next((p for p, rx in _PERIOD if re.search(rx, t, I)), default)


def tracker_intent(t: str) -> Intent | None:
    """Money + habits, 0 tokens: 'spent 500 on food', 'got 20000 salary', 'how much did I spend this week',
    'how much on food this month', 'show my expenses', 'delete the last expense', 'the last one was 450',
    'set my food budget to 8000', 'remind me to pay internet 1500 every month on the 5th', 'paid internet';
    'add a habit: drink water 8 glasses a day', 'I drank 2 glasses of water', 'my habits', 'delete the water habit'."""
    if len(t.split()) > 30:
        return None
    from jarvis.core import expenses as ex, habits as hb
    def money(action, **kw):
        return Intent("money", "expenses", "tracker", {"action": action, **kw})
    def habit(action, text=""):
        return Intent("habit", "habits", "tracker", {"action": action, "text": text})
    low = t.lower().strip(" .!?")
    if re.fullmatch(r"(?:please\s+)?(?:give\s+me\s+|tell\s+me\s+|read\s+me\s+|send\s+(?:me\s+)?|show\s+(?:me\s+)?|what(?:'s|\s+is)\s+)?(?:my\s+|the\s+|today'?s\s+)?(?:morning\s+|daily\s+)?brief(?:ing)?"
                    r"(?:\s+(?:for\s+)?today)?|brief\s+me|how\s+does\s+my\s+day\s+look(?:\s+like)?|what\s+does\s+my\s+day\s+look\s+like", low, I):
        return Intent("brief", "_brief", "self", {})
    # --- habits ---
    if m := re.fullmatch(r"(?:please\s+)?(?:add|create|start|new|make|track)(?:\s+a)?(?:\s+new)?\s+habit(?:\s+(?:to|of|for|called|named))?[:\s]+(?P<x>.+)"
                         r"|(?:please\s+)?(?:start\s+)?track(?:ing)?\s+(?:my\s+)?(?P<y>.+?)\s+(?:daily|every\s+day|as\s+a\s+habit)(?P<r>.*)", low, I):
        return habit("add", (m.group("x") or (m.group("y") + (m.group("r") or ""))).strip())
    if re.fullmatch(r"(?:show\s+|check\s+|what\s+are\s+|how\s+are\s+|list\s+)?(?:me\s+)?(?:my\s+|all\s+(?:my\s+)?)?(?:habits?|habit\s+(?:streaks?|tracker|status|list)|streaks?)"
                    r"(?:\s+(?:today|status|going|doing|so\s+far))?|how\s+(?:are|is)\s+my\s+(?:habits?|streaks?)(?:\s+going)?|/habits?", low, I):
        return habit("status")
    if m := re.fullmatch(r"(?:please\s+)?(?:delete|remove|stop\s+tracking|drop)\s+(?:the\s+|my\s+)?(?P<x>.+?)\s+habit|(?:please\s+)?stop\s+tracking\s+(?P<y>.+)", low, I):
        if hb.names():
            return habit("delete", m.group("x") or m.group("y"))
    names = hb.names()
    if names and re.search(r"\b(?:didn'?t|did\s+not|haven'?t|have\s+not|undo)\b", low) and hb.find(low):
        return habit("undo", t)
    if names and hb._VERB.search(low) and hb.find(low) and not re.search(r"\b(?:spent|paid|rs|rupees|bought)\b", low):
        return habit("done", t)
    if names and (m := re.fullmatch(r"(?P<x>.+?)\s+(?:done|complete|completed|finished|ho\s+gayo|sakiyo)", low, I)) and hb.find(m.group("x")):
        return habit("done", t)
    # --- money ---
    if m := re.fullmatch(r"(?:please\s+)?remind\s+me\s+to\s+pay\s+(?:the\s+|my\s+)?(?P<n>[a-z ]+?)(?:\s+bill)?\s+(?P<a>" + _MONEY_AMT +
                         r")\s+(?:every|each)\s+month(?:\s+on)?(?:\s+the)?\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?", low, I):
        return money("bill", text=m.group("n").strip(), amount=ex._amount(m.group("a")) or 0, day=int(m.group("d")))
    if m := re.fullmatch(r"(?:i\s+)?(?:have\s+)?paid\s+(?:the\s+|my\s+)?(?P<n>[a-z ]+?)(?:\s+bill)?", low, I):
        from jarvis.core import expenses as _e
        if any(b.get("name") and b["name"] in m.group("n") for b in _e._book()[2]):
            return money("pay", text=m.group("n"))
    if m := re.fullmatch(r"(?:please\s+)?(?:set|make|change|keep)\s+(?:my\s+|the\s+)?(?:monthly\s+)?(?P<c>[a-z]+\s+)?budget(?:\s+for\s+(?P<c2>[a-z]+))?\s+(?:to|at|as)?\s*(?P<a>"
                         + _MONEY_AMT + r")(?:\s+(?:a|per|every)\s+month)?|my\s+(?:monthly\s+)?(?P<c3>[a-z]+\s+)?budget\s+is\s+(?P<a2>" + _MONEY_AMT + r")(?:\s+a\s+month)?", low, I):
        cat = (m.group("c") or m.group("c2") or m.group("c3") or "total").strip()
        cat = "total" if cat in ("monthly", "total", "whole", "overall", "my") else (ex.resolve_category(cat) or cat)
        return money("budget", category=cat, amount=ex._amount(m.group("a") or m.group("a2")) or 0)
    if m := re.fullmatch(r"set\s+(?:my\s+)?(?:monthly\s+)?budget\s+(?:for\s+)?(?:(?P<c>[a-z]+)\s+)?(?:to\s+)?(?P<a>" + _MONEY_AMT + r")", low, I):
        return money("budget", category=m.group("c") or "total", amount=ex._amount(m.group("a")) or 0)
    if re.fullmatch(r"(?:please\s+)?(?:delete|remove|undo|cancel)\s+(?:the\s+|my\s+)?last\s+(?:expense|entry|spending|one|transaction|income)", low, I):
        return money("delete", text="last")
    if m := re.fullmatch(r"(?:please\s+)?(?:delete|remove)\s+(?:the\s+)?(?:expense|entry|transaction)\s+(?:number\s+)?(?P<n>\d+)", low, I):
        return money("delete", text=m.group("n"))
    if re.fullmatch(r"(?:no\W+)?(?:the\s+)?last\s+(?:one|expense|entry)\s+(?:was|is|should\s+be)\s+.+|(?:change|make)\s+(?:the\s+)?last\s+(?:one|expense|entry)\s+(?:to|into)\s+.+", low, I):
        return money("edit", text=t)
    if re.search(r"\b(?:break\s*down|category[\s-]?wise|by\s+category|each\s+category|every\s+category|all\s+(?:the\s+)?categories|"
                 r"per\s+category|whole\s+(?:budget|expenses?|spending)|full\s+(?:expense|spending|money)\s+report|where\s+(?:did|does)\s+"
                 r"(?:my|all\s+my|the)\s+money\s+go)", low) and re.search(r"\b(?:spen[dt]|spending|expenses?|money|budget|kharcha|category|categories)\b", low):
        return money("breakdown", period=_money_period(low))
    if len(low.split()) <= 16 and re.search(r"\b(?:what\s+is|what'?s|tell\s+me|show|how\s+much\s+is)\b.{0,25}\b(?:my\s+)?(?:total\s+|monthly\s+|this\s+month'?s?\s+)?budget\b", low) \
            and not re.search(r"\b(?:set|make|change|is\s+\d)", low):
        return money("report", period=_money_period(low))  # the report ends with the budget used / left
    if len(low.split()) <= 18 and re.search(r"\b(?:tell\s+me|show|what|give|how)\b", low) and re.search(
            r"\b(?:my\s+)?(?:spending(?:\s+money)?|expenses?|expensive|expenc\w*|expecs\w*|money\s+spent)\b", low) \
            and re.search(r"\b(?:my|this\s+month|this\s+week|this\s+year|today|monthly|report|in\s+this|so\s+far)\b", low) \
            and not re.search(r"\b(?:most\s+expensive|expensive\s+(?:phone|laptop|car|house|city|country))\b", low) \
            and not re.match(r"(?:show|list|give\s+me)\s+(?:me\s+)?(?:my\s+|the\s+|all\s+)?(?:expenses|spendings?|transactions)\b", low):
        cat = next((c for c in ex.CATS if re.search(rf"\b{c}\b", low)), "")
        return money("report", period=_money_period(low), category=cat)
    if re.search(r"\b(?:how\s+much|kati)\b.{0,30}\b(?:spen[dt]|spending|expense|kharcha|खर्च|kharch)", low) or re.fullmatch(
            r"(?:show\s+|give\s+|tell\s+)?(?:me\s+)?(?:my\s+|the\s+)?(?:total\s+)?(?:expense|expenses|spending|money|kharcha)\s+(?:report|summary|total|so\s+far|breakdown)"
            r"(?:\s+(?:for|of)\s+.+|\s+(?:today|yesterday|this\s+\w+|last\s+month))?|(?:monthly|weekly|yearly|daily)\s+(?:expense|spending|money)\s+report", low, I):
        cat = next((c for c in ex.CATS if re.search(rf"\b{c}\b", low)), "")
        if not cat and (mm := re.search(r"\b(?:on|for|in|of)\s+(?:my\s+|the\s+)?([a-z]+)", low)):
            cat = ex.resolve_category(mm.group(1))
        return money("report", period=_money_period(low), category=cat)
    if re.fullmatch(r"(?:show|list|what\s+are|give\s+me)\s+(?:me\s+)?(?:my\s+|the\s+|all\s+)?(?:expenses|spendings?|transactions)(?:\s+(?:for\s+)?(?:today|yesterday|this\s+\w+|last\s+month))?"
                    r"|(?:show|list|give\s+me)\s+(?:me\s+)?(?:my\s+|the\s+|all\s+)?(?:expenses|spendings?|transactions)\s+(?:from|between|on|since|for|of|in)\s+.+", low, I):
        return money("list", period=_money_period(low, "today"))
    not_money = re.search(r"\b(?:time|minutes?|mins?|hours?|hrs?|seconds?|days?|weeks?|months?|years?|tokens?|ram|gb|mb|percent|"
                          r"remind|schedule|alarm|timer|how\s+much|points?|marks?|goals?|runs?|wickets?)\b|%", low)
    if not not_money and re.search(r"\d", low) and (
            re.search(r"\b(?:spent|spend|spending|paid|paying|bought|buying|kharcha|kharch|खर्च|salary|income)\b", low)
            or (re.search(r"\b(?:got|received|earned)\b", low) and re.search(
                r"\b(?:rs|rupees?|npr|money|paisa|salary|income|bonus|refund|payment|freelance)\b|रु|\$|\d\s*k\b", low))):
        return money("add", text=t)
    return None


def slash_intent(t: str) -> Intent | None:
    """'/weather pokhara', '/todo buy milk', '/def', '/list' (jarvis/core/slash.py): the command's phrase through the
    fast path, or its tool directly. Unknown '/word' -> the list hint (a path like /home/x is not a command)."""
    from jarvis.core import slash
    cmd, arg, typed = slash.lookup(t)
    if cmd is None:
        if typed and not arg and len(typed) <= 15:
            return Intent("say", "_say", "self", {"en": f"I don't know /{typed}. Type /list to see every command."})
        return None
    if cmd.name == "clear" and (tc := slash.tool_call(cmd, arg)) and tc[0] != "_cmd":  # /clear ram|storage|kurama
        return Intent("slash", tc[0], tc[1], tc[2], cmd.name)
    if cmd.tool and cmd.tool[0] == "_cmd":  # the Telegram commands, done on the laptop
        return Intent("cmd", "_cmd", "self", {"cmd": cmd.tool[2]["cmd"], "arg": arg}, cmd.name)
    if cmd.name == "list":
        return Intent("say", "_say", "self", {"en": slash.help_text("md")})
    if cmd.phrase and (p := slash.phrase_for(cmd, arg)):
        return match(p)
    if tc := slash.tool_call(cmd, arg):
        return Intent("slash", tc[0], tc[1], tc[2], cmd.name)
    if (cmd.tool or cmd.hint.startswith("<")) and not arg:  # '/search' alone
        return Intent("say", "_say", "self", {"en": f"Usage: /{cmd.name} {cmd.hint} — {cmd.desc}."})
    canon = f"/{cmd.name}" + (f" {arg}" if arg else "")
    return None if canon == t else match(canon)  # '/plya' -> '/play' (the media rules)


def coderun_intent(t: str) -> Intent | None:
    """'run this code' / 'run the selected code' / 'execute this' / '/run' -> code_nav run (0 tokens);
    'fix it' right after a failed run -> the code fixer with that error."""
    if re.fullmatch(r"/(?:run|exec|execute)", t, I) or re.fullmatch(
            r"(?:please\s+|kurama\W+|can\s+you\s+|hey\s+)*(?:run|execute|try)\s+(?:this|that|the\s+selected|the\s+highlighted|my|"
            r"selected|highlighted)(?:\s+(?:code|snippet|line|lines|part|block|function|script|program))?(?:\s+(?:for\s+me|now|please|"
            r"and\s+show\s+(?:me\s+)?(?:the\s+)?(?:output|result)))*[\s.!?]*", t, I):
        return Intent("codenav", "code_nav", "codequality", {"action": "run", "name": "", "request": t})
    from jarvis.core import coderun
    if coderun.pending_fix() and re.fullmatch(r"(?:please\s+|ok(?:ay)?\W+|yes\W+)*(?:fix|correct|repair|solve)\s+(?:it|this|that|the\s+(?:error|"
                                              r"bug|problem|code))(?:\s+(?:for\s+me|now|please))*[\s.!?]*", t, I):
        e = coderun.pending_fix()
        return Intent("assist", "text_assist", "clipboard",
                      {"action": "improve", "request": "Fix this code so it runs without this error:\n" + e["error"]})
    return None


def port_intent(t: str) -> Intent | None:
    """'what is running on port 8000' / 'is port 3000 free' / 'show my open ports' / '/ports' -> laptop_doctor port;
    'free port 8000' / 'kill the process on port 8000' -> laptop_doctor stop 'port 8000' (asks first). 0 tokens."""
    def show(n):
        return Intent("doctor", "laptop_doctor", "system", {"action": "port", "target": str(n) if n else ""})
    if m := re.fullmatch(r"/ports?(?:\s+(?P<n>\d{2,5}))?", t, I):
        return show(m.group("n"))
    if len(t.split()) > 16 or not re.search(r"\bports?\b", t, I):
        return None
    lead = r"(?:please\s+|kurama\W+|can\s+you\s+|hey\s+)*"
    if m := re.fullmatch(lead + r"(?:free(?:\s+up)?|kill|stop|close|release|clear)\s+(?:the\s+)?(?:(?:process|program|app|server|thing)\s+"
                         r"(?:on|using|that\s+uses|at)\s+|whatever\s+is\s+(?:on|using)\s+|what(?:'s|\s+is)\s+(?:on|using)\s+)?port\s+"
                         r"(?P<n>\d{2,5})[\s.!?]*", t, I):
        return Intent("doctor", "laptop_doctor", "system", {"action": "stop", "target": f"port {m.group('n')}"})
    if m := re.search(r"\bport\s+(?:number\s+)?(?P<n>\d{2,5})\b|\b(?P<n2>\d{2,5})\s+port\b", t, I):
        n = m.group("n") or m.group("n2")
        if re.search(r"\b(?:what|which|who|whats|is|check|show|tell|running|using|uses|used|free|busy|open|taken|available|occupied)\b", t, I) \
                or re.fullmatch(r"port\s+\d+[\s?]*", t, I):
            return show(n)
    if re.search(r"\b(?:show|list|which|what|check|all|my|open|used|busy)\b.{0,25}\bports\b|\bports\s+(?:in\s+use|open|used|are\s+(?:open|used|in\s+use))\b",
                 t, I) and not re.search(r"\b(?:usb|hdmi|serial|router|firewall)\b", t, I):
        return show(0)
    return None


def libhelp_ask(t: str) -> bool:
    """'help me with this library', 'what arguments does this take', 'is this correct syntax', 'did I use this
    function right', 'suggest a better way to call this' (about the highlighted code)."""
    sel = r"(?:this|that|the\s+selected|selected|highlighted|my|it)"
    return bool(re.search(
        r"\bhelp\s+(?:me\s+)?(?:with\s+)?" + sel + r"\s+(?:library|module|package|function|method|call|syntax|api)\b|"
        r"\bwhat\s+(?:are\s+the\s+|all\s+)?(?:arguments?|args|parameters?|params|options|inputs)\s+(?:does|do|of|for|in|can|this|that|it)\b|"
        r"\b(?:arguments?|args|parameters?|params)\s+(?:of|for)\s+" + sel + r"\b|"
        r"\bwhich\s+(?:arguments?|parameters?)\b|"
        r"\bis\s+(?:this|that|my|it)\s+(?:the\s+)?(?:correct|right|valid|proper|good)\s+(?:syntax|way|call|usage|code)\b|"
        r"\bis\s+(?:this|that|my|the)\s+(?:syntax|call|usage|function\s+call|code\s+line|line)\s+(?:correct|right|valid|ok|okay|fine)\b|"
        r"\b(?:did|am)\s+i\s+(?:use|using|call|calling|write|writing)\s+(?:this|that|it)\s+(?:function\s+|library\s+|method\s+)?"
        r"(?:correctly|right|properly|the\s+right\s+way)\b|"
        r"\b(?:suggest|show)\s+(?:me\s+)?(?:a\s+)?(?:better|correct|right)\s+(?:way|syntax|call)\s+(?:to\s+(?:use|call|write)\s+)?" + sel + r"\b", t, I)) \
        and not re.search(r"\b(?:command|terminal|cli|website|app|telegram|kurama)\b", t, I)


def codenav_intent(t: str) -> Intent | None:
    """'find this function' / 'go to definition' / 'take me to this function's code' / 'where is this function defined'
    / 'show me the real code of calc_total' / '/def calc_total' -> code_nav (opens it in VS Code, 0 tokens)."""
    if m := re.fullmatch(r"/(?:def|definition|goto|go|fn|func)(?:\s+(?P<n>[\w.]+))?", t, I):
        return Intent("codenav", "code_nav", "codequality", {"action": "find", "name": m.group("n") or ""})
    if m := re.fullmatch(r"/(?:args|lib|libhelp|syntax|params)(?:\s+(?P<n>.+))?", t, I):
        return Intent("codenav", "code_nav", "codequality", {"action": "help", "name": (m.group("n") or "").strip(), "request": ""})
    if len(t.split()) <= 30 and libhelp_ask(t):
        return Intent("codenav", "code_nav", "codequality", {"action": "help", "name": "", "request": t})
    if len(t.split()) > 18:
        return None
    sel = r"(?:this|that|the\s+selected|selected|highlighted|the\s+highlighted|my\s+selected)"
    verb = r"(?:find|show|open|go\s+to|goto|take\s+me\s+to|bring\s+me\s+to|jump\s+to|navigate\s+to|redirect\s+me\s+to|direct\s+me\s+to|get\s+me\s+to|search)"
    lead = r"(?:please\s+|kurama\W+|can\s+you\s+|could\s+you\s+|hey\s+)*(?:(?:show|give)\s+me\s+)?"
    if re.fullmatch(lead + r"(?:" + verb + r"\s+)?(?:the\s+)?definition(?:\s+of\s+" + sel + r"(?:\s+\w+)?)?(?:\s+please)?[\s.!?]*", t, I) \
            or re.fullmatch(lead + verb + r"(?:\s+me)?\s+(?:the\s+)?(?:real\s+|actual\s+|original\s+|full\s+|main\s+)?(?:code|source|"
                            r"definition|implementation)?\s*(?:of\s+|for\s+)?" + sel + r"(?:'s)?\s+" + _NAV_OBJ +
                            r"(?:'s)?(?:\s+(?:code|source|definition|implementation))?(?:\s+(?:in\s+vs\s*code|for\s+me|please))*[\s.!?]*", t, I) \
            or re.fullmatch(lead + r"where\s+(?:is|was|does)\s+" + sel + r"\s+" + _NAV_OBJ + r"\s+(?:defined|written|declared|"
                            r"come\s+from|from|implemented|made|located)[\s.!?]*", t, I) \
            or re.fullmatch(lead + r"(?:where\s+is\s+the\s+(?:code|definition)\s+of|what\s+is\s+the\s+(?:real|actual)\s+code\s+of)\s+"
                            + sel + r"(?:\s+" + _NAV_OBJ + r")?[\s.!?]*", t, I):
        return Intent("codenav", "code_nav", "codequality", {"action": "find", "name": ""})
    if m := re.fullmatch(lead + r"(?:" + verb + r"\s+(?:me\s+)?(?:the\s+)?(?:real\s+|actual\s+)?(?:code\s+of\s+|definition\s+of\s+)?"
                         r"(?:the\s+)?(?:function|method|class|def)\s+|where\s+is\s+(?:the\s+)?(?:function|method|class)\s+)"
                         r"(?P<n>[A-Za-z_][\w.]*)(?:\(\))?(?:\s+(?:defined|function|method|class))?[\s.!?]*", t, I):
        return Intent("codenav", "code_nav", "codequality", {"action": "find", "name": m.group("n")})
    return None


def assist_intent(t: str) -> Intent | None:
    """Highlighted text/code help, 0 tokens to route: explain / meaning / translate / fix code / write code / file."""
    from jarvis.core.assist import lang_of
    lang = lang_of(t)
    if m := _A_FILE.match(t):
        f = re.sub(r"^file\s+", "", m.group("f"), flags=I)
        return Intent("assist", "text_assist", "clipboard", {"action": "explain_file", "path": "this" if f.lower() ==
                                                             "this file" else f, "lang": lang})
    if m := re.match(r"^(?:please\s+|kurama\W+|kura\W+|can\s+you\s+)*(?:convert|change|turn|put|write|say|make)\s+(?P<x>.+?)\s+"
                     r"(?:in|into|to)\s+(?P<l>" + _LANG_ALT + r")(?:\s+language)?(?P<r>\s+and\s+replace(?:\s+it)?)?\s*[.!?]*$", t, I):
        x = m.group("x").strip()
        sel = bool(re.fullmatch(_SELREF + r"(?:\s+(?:word|sentence|paragraph|text|line|part))?", x, I)
                   or re.fullmatch(r"(?:the\s+)?(?:language|lang|text|words?|sentence)(?:\s+of\s+.*)?", x, I)  # 'the language of the selected sentence'
                   or re.search(r"\b(?:selected|highlighted|selection)\b", x, I))
        if sel or not re.search(r"\.\w{2,5}\b|\bfile\b", x, I):  # a language target: translation, not a file
            return Intent("assist", "text_assist", "clipboard", {"action": "translate", "lang": lang_of(m.group("l")) or "ne",
                                                                 "replace": bool(m.group("r")), "text": "" if sel else x})
    if re.search(r"\b(?:code|function|snippet|script|class|method)\b", t, I) and re.search(
            r"\b(?:meaning|mean|explain|explanation|what\s+(?:does|is)|understand|doing)\b", t, I) and re.search(
            r"\b(?:this|that|the\s+selected|selected|highlighted|i\s+select)\b", t, I) and len(t.split()) <= 20 \
            and not _A_CODEFIX.search(t):
        return Intent("assist", "text_assist", "clipboard", {"action": "code", "lang": lang})
    if m := _A_TRANSLATE.match(t):
        x, l = m.group("x").strip(), lang_of(m.group("l")) or "ne"
        sel = bool(re.fullmatch(_SELREF + r"(?:\s+(?:word|sentence|paragraph|text|line|part))?", x, I))
        return Intent("assist", "text_assist", "clipboard", {"action": "translate", "lang": l, "replace": bool(m.group("r")),
                                                             "text": "" if sel else x.strip("'\"")})
    # 'how can I use this function / give me the code to use (run, call) it' -> a run block added to the file
    if len(t.split()) <= 40 and re.search(r"\b(?:how\s+(?:can|do|should|would)\s+i\s+(?:use|run|call|execute)|(?:code|example|block)\s+(?:to|for)\s+"
                                          r"(?:use|using|run|running|call|calling|execute)|(?:use|run|call|execute)\s+(?:this|that|my|the)\s+(?:function|"
                                          r"code|class|method|script)|usage\s+(?:code|example)|example\s+of\s+using)\b", t, I) \
            and not re.search(r"\b(?:tests?|pytest|unit\s*tests?|terminal\s+command)\b", t, I):
        return Intent("assist", "text_assist", "clipboard", {"action": "use"})
    # 'complete this code' / 'finish my function' -> completed in the background, asks if unclear, then 'replace it?'
    if len(t.split()) <= 30 and re.search(r"\b(?:complete|finish|fill\s+in|implement)\s+(?:the\s+rest\s+of\s+)?(?:this|that|my|the|selected)?\s*"
                                          r"(?:code|function|class|method|script|program|todo|it)\b", t, I) \
            and not re.search(r"\b(?:task|to[\s-]?do\s+list|reading|book|goal)\b", t, I):
        return Intent("assist", "text_assist", "clipboard", {"action": "complete", "request": t})
    # anything NEW about the highlighted code/text: 'give me code to test this function', 'show an example of using this
    # class', 'write a docstring for the selected code', 'what inputs break this function?' -> selection + request
    if len(t.split()) <= 45 and re.search(r"\b(?:this|that|the\s+selected|selected|highlighted|my|the)\s+(?:python\s+)?(?:function|code|class|"
                                          r"method|snippet|script|program|loop|query)\b|\bi\s+(?:just\s+)?(?:selected|highlighted)\b", t, I) \
            and re.search(r"\b(?:tests?|testing|unit\s*tests?|pytest|test\s+cases?|examples?|usage|use\s+(?:it|this)|call\s+(?:it|this)|"
                          r"docstrings?|type\s+hints?|edge\s+cases?|inputs?|complexity|big\s*o|bugs?|security|time\s+complexity|"
                          r"flow\s*chart|diagram|pseudo\s*code|convert\s+(?:it|this|that)(?:\s+\w+)?\s+(?:to|into)|in\s+(?:javascript|java|c\+\+|rust|go))\b", t, I) \
            and not _A_CODEFIX.search(t) and not re.search(r"\b(?:replace|in\s+place|run\s+(?:the\s+|my\s+)?tests?)\b", t, I):
        return Intent("assist", "text_assist", "clipboard", {"action": "ask", "request": t})
    # 'can you give me the Nepali translation of this word?' / 'translation of the selected text in Hindi'
    if len(t.split()) <= 20 and re.search(r"\btranslat\w*\b", t, I) and (lm := re.search(r"\b(" + _LANG_ALT + r")\b", t, I)) and re.search(
            r"\b(?:this|that|the\s+selected|selected|highlighted)(?:\s+(?:whole|entire))?(?:\s+(?:word|words|sentence|paragraph|text|line|part|phrase))?\b", t, I) \
            and not re.search(r"\.\w{2,5}\b|\bfile\b", t, I):
        return Intent("assist", "text_assist", "clipboard", {"action": "translate", "lang": lang_of(lm.group(1)) or "ne",
                                                             "replace": bool(re.search(r"\breplace\b", t, I)), "text": ""})
    # 'what is the summary of this whole paragraph? what does it want to say to me?' -> the main points of the selection
    if len(t.split()) <= 30 and re.search(r"\b(?:summary|summari[sz]e|sum\s+(?:it\s+)?up|main\s+(?:points?|things?|ideas?|message)|gist|"
                                          r"tl;?\s*dr|in\s+short|want(?:s)?\s+to\s+(?:say|tell)|trying\s+to\s+(?:say|tell))\b", t, I) and re.search(
            r"\b(?:this|that|the|selected|highlighted)\s+(?:whole\s+|entire\s+|full\s+|long\s+)?(?:sentence|paragraph|paragraphs|passage|text|"
            r"article|section|para|part|message|email|selection|page\s+part)\b|\b(?:summari[sz]e|sum\s+up)\s+(?:this|that|it)\b", t, I) \
            and not re.search(r"\b(?:web\s*page|website|this\s+page|this\s+site|video|youtube|pdf|file|book|chapter|day|today|news)\b", t, I):
        return Intent("assist", "text_assist", "clipboard", {"action": "summary", "lang": lang})
    if re.search(r"\b(?:meaning|artha|matlab|explain|explanation)\b", t, I) and re.search(
            r"\b(?:this|that|the)\s+(?:whole\s+|entire\s+|full\s+)?(?:sentence|sentences|paragraph|paragraphs|passage|"
            r"question|line|lines|para|text|section)\b", t, I) and len(t.split()) <= 20:
        return Intent("assist", "text_assist", "clipboard", {"action": "explain", "lang": lang})
    if _A_BARE_SEL.match(t):  # "this word." / "the selected word" (answering "which word?")
        return Intent("assist", "text_assist", "clipboard", {"action": "meaning", "lang": lang or "en", "text": ""})
    if re.search(r"\b(?:explain|explanation|summari[sz]e|what\s+(?:does|is))\b", t, I) and WHOLE_CODE.search(t) \
            and len(t.split()) <= 16:  # "explain my whole code" = the file open in VS Code
        return Intent("assist", "text_assist", "clipboard", {"action": "explain_file", "path": "this", "lang": lang})
    if re.match(r"(?:please\s+|kurama\W+|can\s+you\s+)*(?:write\s+(?:a\s+|my\s+)?(?:reply|response|answer)|reply|respond|answer)"
                r"(?:\s+(?:to|for))?\s+(?:this|that|it|the\s+(?:selected|copied|last))(?!\s+question)(?:\s+(?:message|chat|conversation|"
                r"text|email|mail|messages|one))?\b|^(?:what\s+should\s+i\s+(?:reply|say|answer|write)(?:\s+(?:to\s+)?(?:this|that|him|her|them))?)"
                r"[\s?.!]*$", t, I) and len(t.split()) <= 30:  # 'reply to this, say I'm busy till Friday'
        return Intent("assist", "text_assist", "clipboard", {"action": "reply", "request": t, "lang": lang})
    if len(t.split()) <= 30 and re.search(
            r"\b(?:what|how)\s+(?:should|do|can|could|would|shall)\s+(?:be\s+)?(?:the\s+|my\s+|a\s+|i\s+)*(?:reply|respond|answer|say|write|text\s+back)\b"
            r"|\bwhat\s+(?:reply|response|answer)\s+(?:should|do|can|could|shall)\s+i\b|\bwhat\s+(?:to|should\s+i)\s+(?:reply|say|answer)\b"
            r"|\b(?:suggest|give\s+me|write|draft|make)\s+(?:me\s+)?(?:a\s+|the\s+|my\s+)?(?:good\s+|nice\s+|short\s+|polite\s+)?(?:reply|response|answer)\b"
            r"|\breply\s+(?:for|to)\s+(?:his|her|their|my\s+friend'?s?|this|that|the)\b", t, I) \
            and re.search(r"\b(?:friend|him|her|them|his|their|this|that|message|messages|chat|conversation|text|email|mail|"
                          r"whatsapp|messenger|viber|dm|reply|answer)\b", t, I) \
            and not re.search(r"\b(?:essay|exam|interview|speech|code|function|error|test)\b", t, I):
        return Intent("assist", "text_assist", "clipboard", {"action": "reply", "request": t, "lang": lang})
    if dc := decode_intent(t):  # decode / prettify the selection, 0 tokens
        return dc
    if ct := code_tidy_intent(t):  # format / check / fix with ruff, 0 tokens
        return ct
    if re.search(r"\b(?:fix|clean\s+up|refactor|improve|optimi[sz]e|correct)\b", t, I) \
            and WHOLE_CODE.search(t) and len(t.split()) <= 20:  # "fix this file" / "improve my whole code": the AI
        return Intent("assist", "text_assist", "clipboard", {"action": "improve", "request": t})
    if re.search(r"\b(?:meaning|means?|definition|define|artha|matlab)\b|अर्थ", t, I) and _A_POINT.search(t) \
            and len(t.split()) <= 16 and not _A_NOT_SEL.search(t):  # any way of asking what the selection means
        if re.search(r"\b(?:code|function|class|method|script|snippet|loop|regex)\b", t, I):
            return Intent("assist", "text_assist", "clipboard", {"action": "code", "lang": lang})
        if not re.search(r"\b(?:word|words|phrase|term|meaning|definition|define|artha|matlab)\b|अर्थ", t, I):
            return Intent("assist", "text_assist", "clipboard", {"action": "explain", "lang": lang})  # "what does this mean"
        return Intent("assist", "text_assist", "clipboard", {"action": "meaning", "lang": lang or "en", "text": ""})
    if m := _A_MEANING.match(t):
        x = (m.group("x") or m.group("y") or m.group("z") or "").strip(" '\"")
        if m.group("z") and x.lower() in ("this", "that", "it", "these"):  # "what does this mean" = explain it
            return Intent("assist", "text_assist", "clipboard", {"action": "explain", "lang": lang})
        sel = not x or bool(re.fullmatch(_SELREF + r"(?:\s+(?:word|sentence|line|phrase|paragraph))?", x, I))
        if x and not sel and (re.search(r"\b(?:my|your|it all|this world)\b", x, I) or x.lower() in ("life", "love", "existence")):
            return None  # "what is the meaning of my life" is a question, not a dictionary lookup
        return Intent("assist", "text_assist", "clipboard", {"action": "meaning", "lang": lang or "en",
                                                             "text": "" if sel else x})
    if re.match(r"^(?:please\s+)?(?:what\s+(?:does|is)\s+(?:this|that|the\s+selected)\s+(?:code|function|class|method|snippet|script|"
                r"loop|regex|query)\s+(?:do|doing|for|mean)|how\s+does\s+this\s+(?:code|function|class|method|work))\b", t, I):
        return Intent("assist", "text_assist", "clipboard", {"action": "code", "lang": lang})
    if re.match(r"^(?:please\s+)?what\s+does\s+(?:this|that|it)\s+mean\b", t, I) and not _A_MEANING.match(t + " x"):
        return Intent("assist", "text_assist", "clipboard", {"action": "explain", "lang": lang})
    if m := _A_EXPLAIN.match(t):
        rest = m.group("rest")
        if re.search(r"\b(?:file|folder|project|repo|repository|error|traceback)\b", rest, I):
            return None  # "explain this error" -> fix_error, "explain this project" -> knowledge
        if re.search(r"\b(?:code|function|class|method|snippet|script|loop|regex)\b", rest + t, I):
            return Intent("assist", "text_assist", "clipboard", {"action": "code", "lang": lang})
        if rest.strip() and not re.match(r"^\s*(?:" + _SELREF + r"|to\s+me|me|in\s+\w+|simply|please|\W)*\s*$", rest, I):
            return None  # "explain quantum physics" is a normal question for the AI, not about a selection
        return Intent("assist", "text_assist", "clipboard", {"action": "explain", "lang": lang})
    if re.search(r"\b(?:make|turn)\b.{0,40}\b(?:code|function|class|script)\b.{0,40}\b(?:better|cleaner|faster|detailed|readable|"
                 r"good|nicer|efficient|professional)\b|\breplace\s+(?:this|the|my|that)\s+(?:\w+\s+)?(?:code|function)\s+(?:with|from|by|into|to)\b", t, I) \
            and len(t.split()) <= 30:
        return Intent("assist", "text_assist", "clipboard", {"action": "improve", "request": t})
    if _A_CODEFIX.search(t) and len(t.split()) <= 25 and not re.search(r"\b(?:file|project|repo)\b", t, I):
        return Intent("assist", "text_assist", "clipboard", {"action": "improve", "request": t})
    if _A_WRITE.match(t) and len(t.split()) <= 40 and not re.search(r"\b(?:essay|story|poem|article|report|email|letter|"
                                                                    r"qr|barcode)\b", t, I):
        return Intent("assist", "text_assist", "clipboard", {"action": "write", "request": t})
    return None


def everyday_intent(t: str) -> Intent | None:
    """0-token replies for things that were costing an LLM call each (greetings, thanks, 'kill brave',
    'top memory processes', 'laptop is slow', 'status of training', 'summarise today', 'exact path of that folder')."""
    if _HELLO.match(t):
        from jarvis.core import phrases
        return Intent("say", "_say", "self", phrases.pick(phrases.HELLO))
    if _HOWRU.match(t):
        from jarvis.core import phrases
        return Intent("say", "_say", "self", phrases.pick(phrases.HOWRU))
    if _THANKS.match(t):
        from jarvis.core import phrases
        return Intent("say", "_say", "self", phrases.pick(phrases.THANKS))
    if _OKAY.match(t):
        return Intent("say", "_say", "self", {"en": "Okay.", "hi": "ठीक है।", "ne": "हुन्छ।"})
    if _BYE.match(t):
        from jarvis.core import phrases
        return Intent("say", "_say", "self", phrases.bye(t))
    if re.fullmatch(r"(?:please\s+)?(?:share|show|give\s+me)\s+(?:the\s+|my\s+)?(?:wi[\s-]*fi|wifi)(?:\s+(?:password|qr(?:\s+code)?|"
                    r"code))?(?:\s+(?:qr(?:\s+code)?))?(?:\s+(?:to|with)\s+.{1,30})?[\s.!]*|(?:wi[\s-]*fi|wifi)\s+qr(?:\s+code)?[\s.!]*", t, I):
        return Intent("wifiqr", "share_wifi", "desktop", {})
    if m := re.fullmatch(r"(?:please\s+)?(?P<a>lock|unlock|encrypt|decrypt|password\s+protect)\s+(?:the\s+|my\s+)?(?P<p>.+?)"
                         r"(?:\s+(?:folder|file|directory))?(?:\s+with\s+(?:a\s+)?password)?[\s.!]*", t, I):
        p = m.group("p").strip()
        if not re.fullmatch(r"(?:the\s+)?(?:(?:laptop|computer)(?:'s)?\s+)?(?:screen|laptop|computer|pc|kurama|phone|door|it\s+now)", p, I):
            act = "unlock" if m.group("a").lower() in ("unlock", "decrypt") else "lock"
            return Intent("lock", "folder_lock", "filesearch", {"action": act, "path": p}, p)
    if re.fullmatch(r"(?:nepali\s*ma|नेपालीमा|नेपाली\s*मा)\s+(?:type|lekha|lekh|लेख|लेखन|टाइप)\s*(?:gara|garnu|गर|गर्नु)?\w*[\s.!]*", t, I):
        return Intent("dictate", "dictate", "windows", {"action": "start", "lang": "ne"})
    _STT = r"(?:dictation|dictating|detection|voice\s+typing|typing|speech[\s-]+to[\s-]+text|stt|voice\s+input)"
    if m := re.fullmatch(r"(?:please\s+)?(?:(?P<stop>stop|end|finish|cancel|disable|turn\s+off|switch\s+off|close|exit)\s+(?:the\s+)?"
                         + _STT + r"(?:\s+mode)?|" + _STT + r"\s+(?P<stop2>off)|(?:start\s+|begin\s+|enable\s+|turn\s+on\s+|switch\s+on\s+|"
                         r"activate\s+)?(?:the\s+)?(?:dictat(?:e|ion|ing)|voice\s+typing|speech[\s-]+to[\s-]+text|stt)(?:\s+mode)?|"
                         r"(?:start\s+)?typ(?:e|ing)\s+what\s+i\s+(?:say|speak))"
                         r"(?:\s+(?:in|for)\s+(?P<lang>english|nepali|hindi))?(?:\s+mode)?[\s.!]*", t, I):
        if m.group("stop2"):
            return Intent("dictate", "dictate", "windows", {"action": "stop"})
        if m.group("stop"):
            return Intent("dictate", "dictate", "windows", {"action": "stop"})
        lang = {"english": "en", "nepali": "ne", "hindi": "hi"}.get((m.group("lang") or "").lower(), "auto")
        return Intent("dictate", "dictate", "windows", {"action": "start", "lang": lang})
    if re.search(r"\bundo\s+(?:the\s+)?(?:organi[sz]e|organi[sz]ing|sorting)\b", t, I):
        return Intent("organize", "organize_files", "daily", {"action": "undo"})
    if (m := re.search(r"\b(?:organi[sz]e|clean\s+up|sort\s+out|tidy\s+up|arrange|rename\s+and\s+sort)\s+(?:the\s+|my\s+|this\s+)?"
                       r"(?P<f>[\w .-]{2,40}?)(?:\s+(?:folder|files|directory))?(?:[,.!]|\s+(?:it\s+is|this\s+is|which|because|please)\b|$)",
                       t, I)) and not re.search(r"\b(?:tabs?|windows?|desktop\s+icons?|code|imports?|paragraphs?|sentences?|text|thoughts?|ideas?|notes?|essay|points?|this\s+(?:list|email|message))\b", m.group("f"), I):
        f = m.group("f").strip()
        from jarvis.core.paths import smart_path
        if f.lower() in ("this", "it", "here", "folder", "files", "directory") or smart_path(f, want="dir") is None:
            f = "this"  # not a real folder name ('folder make less', 'file bro'): the folder in use, never a guess
        return Intent("organize", "organize_files", "daily", {"action": "organize", "folder": f})
    if m := re.fullmatch(r"(?:please\s+)?(?:(?:run|train|start)\s+(?:the\s+|my\s+)?(?P<p>.+?)\s+(?:on|in|using|with)\s+"
                         r"(?:a\s+|the\s+)?(?:free\s+)?(?:kaggle(?:'s)?(?:\s+(?:free\s+)?gpu)?|gpu|cloud\s+gpu)|(?:train|run)\s+(?:it|this)\s+on\s+gpu)"
                         r"[\s.!]*", t, I):
        p = re.sub(r"\s+(?:project|folder|script|notebook|code)$", "", (m.group("p") or "this").strip(), flags=I)
        return Intent("kaggle", "kaggle_train", "watch", {"action": "run", "path": p})
    if re.fullmatch(r"(?:please\s+)?(?:(?:show|check|what(?:'s|\s+is))\s+(?:the\s+|my\s+)?)?kaggle\s+(?:run\s+)?(?:status|runs?)"
                    r"[\s?.!]*|(?:is\s+)?(?:my\s+)?kaggle\s+(?:training|run)\s+(?:done|finished)\??", t, I):
        return Intent("kaggle", "kaggle_train", "watch", {"action": "status"})
    if re.fullmatch(r"(?:please\s+)?(?:set\s*up|install|configure)\s+kaggle(?:\s+(?:gpu|tool|cli))?[\s.!]*", t, I):
        return Intent("kaggle", "kaggle_train", "watch", {"action": "setup"})
    if ai := assist_intent(t):
        return ai
    if _RW_VERB.search(t) and _RW_OBJ.search(t) and not _RW_NOT.search(t) and len(t.split()) <= 22:
        return Intent("assist", "text_assist", "clipboard", {"action": "improve", "request": t})
    if m := _REWRITE.match(t):
        ins = re.sub(r"\s+(?:this|it|that|the\s+selected\s+text|the\s+selection|selected\s+text|selection)\b", "",
                     m.group(0), count=1, flags=I).strip(" .!")
        return Intent("assist", "text_assist", "clipboard", {"action": "improve", "request": ins})
    if _WHERE_PATH.match(t):
        return Intent("where", "_where", "filesearch", {})
    if (m := _KILL.match(t)) and not re.search(r"\b(?:it|this|that|time|me|process\s+\d+)\b", m.group("a"), I):
        return Intent("kill", "kill_app", "apps", {"name": m.group("a").strip()}, m.group("a").strip())
    if _TOP_PROC.search(t):
        return Intent("doctor", "laptop_doctor", "system", {"action": "check"})
    if _SLOW.search(t) and len(t.split()) <= 16:
        free = re.search(r"\b(?:ram|memory)\b", t, I) and re.search(r"\b(?:clean|clear|free)\b", t, I)
        return Intent("doctor", "laptop_doctor", "system", {"action": "free_ram" if free else "check"})
    if re.search(r"\btokens?\b.{0,15}\b(?:usage|used|spent|left|budget)\b|\bhow\s+many\s+tokens?\b", t, I) and len(t.split()) <= 10 \
            and not re.search(r"\b(?:week|month|year|yesterday|all|total|ever)\b", t, I):
        return Intent("tokens", "token_usage", "usage", {"period": "today"})
    if re.fullmatch(r"(?:please\s+)?(?:enable|run|start|open|use)\s+(?:the\s+)?laptop\s+doctor[\s.!]*", t, I):
        return Intent("doctor", "laptop_doctor", "system", {"action": "check"})
    if _TRAIN_ST.match(t):
        return Intent("training", "training", "watch", {"action": "status"})
    if _CUR_STATUS.match(t):
        return Intent("status", "status_now", "usage", {})
    if _DIGEST2.match(t):
        return Intent("digest", "daily_digest", "usage", {"date": "today"})
    return None


_WS_READ = re.compile(r"\b(?:summar\w*|sumar\w*|sumamr\w*|read|what|result|tell|says?|explain|answer|check|k\s+cha|ke\s+hai|kya\s+hai)\b", I)
_WS_NOT = re.compile(r"\b(?:audio|mp3|speech|launch|open|start|create|switch|coding|study|close)\b", I)


def workspace_read_intent(t: str) -> Intent | None:
    """'from workspace, give me summary .. what is result' / 'what does the workspace say' / 'read the previous
    workspace item' -> read_workspace; a short item is answered straight away, a long one goes to the LLM."""
    if not re.search(r"\bwork\s?space\b", t, I) or not _WS_READ.search(t) or _WS_NOT.search(t):
        return None
    item = 2 if re.search(r"\b(?:previous|before|second|earlier|older)\b", t, I) else 1
    return Intent("wsread", "read_workspace", "self", {"item": item})


def live_intent(t: str) -> Intent | None:
    """'what is the result of today inter miami match', 'barcelona score', 'did real madrid win', 'news about Nepal'."""
    if _LIVE_PRICE.match(t) and not re.search(r"\b(?:my|your|this|that|ticket|plan|interest)\b|\d+(?:\.\d+)?\s*"
                                              r"(?:usd|dollars?|euros?|rs|rupees?|npr|inr|pounds?|%|kg|km|gb)\b", t, I):
        return Intent("live", "live_search", "web", {"query": t, "kind": "auto"})
    if m := _LIVE_NEWS.match(t):
        topic = (m.group("t") or "top stories").strip()
        return Intent("live", "live_search", "web", {"query": f"news {topic}", "kind": "news"})
    if re.search(r"\bvs\s*code\b|\bvisual\s+studio\b", t, I):
        return None
    for rx in _LIVE_SPORT:
        if (m := rx.match(t)) and (team := m.group("t").strip(" ,?")) and not _NOT_TEAM.match(team) \
                and len(team.split()) <= 6:
            return Intent("live", "live_search", "web", {"query": t, "kind": "sports"})
    if _LIVE_SPORT_MIX.search(t) and _MIX_ASK.search(t):  # 'aja arsenal ko match ko result k vayo'
        from jarvis.core import live
        team = live.team_query(t)
        if team and len(team.split()) <= 3 and not _NOT_TEAM.match(team):
            return Intent("live", "live_search", "web", {"query": t, "kind": "sports"})
    return None


def video_dl_intent(t: str) -> Intent | None:
    """'download this youtube video in 1080p', 'download <link> as mp3', 'download interstellar trailer in 4k'."""
    m = _VDL.match(t)
    if not m:
        return None
    src, kind, q = (m.group("src") or "").strip(), (m.group("kind") or "").lower(), m.group("q") or ""
    if qm := re.fullmatch(r"(?:in|at|with)\s+(?:the\s+)?(4k|2k|\d{3,4}\s*p?|full\s+hd|hd|fhd|best|high|good|extra\s+high|highest|max(?:imum)?|ultra(?:\s+hd)?|top)(?:\s+qu\w*)?", src, I):
        src, q = "", qm.group(1)  # "download this video in 1080p": no words left, the quality was all of it
    if (u := re.search(r"https?://\S+", src)) and u.start() > 0:  # "<words> <link>": the link is the video, the words
        rest = src[:u.start()] + " " + src[u.end():]  # only add details ("in 1080p", "then", "from youtube") — they
        if not q and (qm := re.search(r"\b(4k|2k|\d{3,4}\s*p|full\s+hd|fhd)\b", rest, I)):  # used to replace the link
            q = qm.group(1)  # with the browser's open tab (trace 4ad71202be1b)
        src = u.group(0)
    is_url = bool(re.match(r"https?://", src))
    if is_url and not re.search(_VID_SITES, src, I) and not (kind or q or m.group("aud")):
        return None  # a plain file link -> download_file
    if not is_url and not (kind or q or m.group("aud") or re.search(r"\byoutube\b", t, I)):
        return None  # "download the dataset" etc. are not videos
    if re.search(r"\b(?:link|url)$", src, I) or re.match(r"(?:link|url)\b", src, I):  # "save this video link as X"
        return None  # "save this video link" keeps the link (saved_links), it doesn't download the video
    if src.lower() in ("", "it", "this", "that", "one") or \
            (not is_url and (m.group("det") or "").strip().lower() in ("this", "that") and kind):
        src = ""  # "download this youtube video (now / please)": the video open in the browser, not a search
    audio = bool(m.group("aud")) or kind in ("mp3", "audio")  # "this song" = its video (with sound) unless MP3/audio
    return Intent("vdl", "video_download", "media", {"source": src, "quality": q.replace(" ", ""),
                                                      "audio": audio,
                                                      "playlist": bool(m.group("pl")) or kind == "playlist"})


_YES_PLAN = re.compile(r"^(?:ok(?:ay)?\s+|yes\s+|yeah\s+)*(?:yes|yeah|yep|yup|sure|ok(?:ay)?|go\s+ahead|do\s+it|apply(?:\s+it|\s+the\s+plan)?|"
                       r"looks\s+good|perfect|fine|good|great|haan|ho|हो|हुन्छ|गर)(?:[\s,.!]+(?:yes|good|do\s+it|go\s+ahead|"
                       r"please|apply\s+it|organi[sz]e(?:\s+it)?|thanks?))*[\s.!]*$", I)
_NO_PLAN = re.compile(r"^(?:no|nope|nah|cancel(?:\s+it|\s+the\s+plan)?|don'?t|do\s+not|stop|leave\s+it|forget\s+it|hoina|होइन|"
                      r"नगर)(?:[\s,.!]+(?:thanks?|please|don'?t\s+do\s+it))*[\s.!]*$", I)
_YES_WORDS = {"yes", "yeah", "yea", "yep", "yup", "ya", "y", "sure", "ok", "okay", "k", "please", "haan", "han", "ho", "hajur",
              "हो", "हुन्छ", "हजुर", "हाँ", "correct", "right", "definitely", "absolutely", "fine", "good", "great", "perfect"}
_YES_LEADS = re.compile(r"(?:go\s+ahead|do\s+it|add\s+it|write\s+it|replace\s+it|apply\s+it|put\s+it|try\s+again|of\s+course|"
                        r"why\s+not|sounds\s+good|let'?s\s+do\s+it|yes\s+please)\b", I)
_NO_WORDS = {"no", "nope", "nah", "n", "cancel", "stop", "nahi", "nahin", "hoina", "होइन", "नाइ", "नहीं", "never"}
_NO_LEADS = re.compile(r"(?:don'?t|do\s+not|not\s+now|not\s+this|leave\s+it|forget\s+it|no\s+thanks?|skip\s+it|never\s*mind)\b", I)


def yes_no(t: str) -> str:
    """'yes' / 'no' / '' for a reply to one of KURAMA's own questions. Robust to voice punctuation and repeats
    ('Yes? Yes?', 'Yeah, yeah, add it.', 'No no, leave it'); a long new request is neither."""
    s = re.sub(r"[^\w\s'\u0900-\u097f]", " ", (t or "").lower()).split()
    if not s or len(s) > 14:
        return ""
    while len(s) > 1 and s[0] in ("okay", "ok", "so", "well", "hmm", "kurama", "hey", "and", "then", "actually"):
        if s[1] in _YES_WORDS or s[1] in _NO_WORDS or s[1] in ("go", "do", "add", "dont", "don't", "not", "leave"):
            s = s[1:]
        else:
            break
    joined = " ".join(s)
    if s[0] in _NO_WORDS or _NO_LEADS.match(joined):
        return "no"
    if s[0] in _YES_WORDS or _YES_LEADS.match(joined):
        return "" if re.search(r"\b(?:but|instead|change|make\s+it|shorter|longer|different)\b", joined) and s[0] != "yes" else "yes"
    return ""


_EDIT_PLAN = re.compile(r"\b(?:change|keep|don'?t\s+move|do\s+not\s+move|leave|put|move|skip|instead|exclude|except|rename|"
                        r"separate|together|into|folder)\b", I)


_SELECTED_NOW = re.compile(r"^(?:(?:ok(?:ay)?|now|yes|kurama|see|look)\W+)*(?:done|ok(?:ay)?|now|try\s+(?:it\s+)?again|"
                           r"(?:i\s+(?:have\s+|just\s+)?(?:select(?:ed)?|highlight(?:ed)?)|(?:it'?s|it\s+is|the\s+\w+\s+is)\s+"
                           r"(?:selected|highlighted))(?:\s+(?:it|that|this|the\s+\w+|them))?(?:\s+now)?)\s*[.!]*$", I)


_YES_START = re.compile(r"^(?:yes|yeah|yep|yup|ya|sure|ok(?:ay)?|haan|ho|हो|हुन्छ)\b", I)
_APPLY_CODE = re.compile(r"\b(?:replace|apply|put|use|paste|change)\b.{0,30}\b(?:it|new|improved|updated|that|this\s+one|"
                         r"now|there)\b|\b(?:you\s+can|go\s+and|please)\s+(?:replace|apply|change)\b|^replace[\s.!]*$", I)


def plan_answer_intent(t: str) -> Intent | None:
    """While an organize plan is waiting: 'yes good' applies it, 'no' cancels it, anything that sounds like a
    change ('keep the pictures where they are') edits it. Costs one kv read when no plan waits."""
    from jarvis.core import assist, organizer
    stage = assist.use_waiting()  # the run block: "Should I add it?" / "Should I try again?"
    if stage:
        yn = yes_no(t)
        yes, no = yn == "yes", yn == "no"
        if stage == "add" and yes and not no:
            return Intent("assist", "text_assist", "clipboard", {"action": "use_yes"})
        if stage == "add" and no:
            return Intent("assist", "text_assist", "clipboard", {"action": "use_no"})
        if stage == "retry" and yes and not no:
            return Intent("assist", "text_assist", "clipboard", {"action": "use_retry", "request": t})
        if stage == "retry" and no:
            return Intent("assist", "text_assist", "clipboard", {"action": "use_cancel"})
    if assist.ask_back_waiting() and len(t.split()) <= 40 and not t.strip().endswith("?"):  # its question to the user
        return Intent("assist", "text_assist", "clipboard", {"action": "answer_back", "request": t})
    if assist.file_ref_waiting() and (yn := yes_no(t)):  # "Do you mean the whole test.py?"
        return Intent("assist", "text_assist", "clipboard", {"action": "file_yes" if yn == "yes" else "file_no"})
    if assist.more_waiting():  # "This needs a longer explanation. Want me to write it?"
        if (yn := yes_no(t)) == "yes":
            return Intent("assist", "text_assist", "clipboard", {"action": "more"})
        if yn == "no" or re.fullmatch(r"that'?s\s+(?:enough|fine|ok)[\s.!]*", t, I):
            return Intent("assist", "text_assist", "clipboard", {"action": "cancel_more"})
    if assist.retry_active() and _SELECTED_NOW.match(t):  # 'nothing highlighted' earlier; now it is
        return Intent("assist", "text_assist", "clipboard", {"action": "retry"})
    if assist.pending_code_active():  # an improved code is waiting in the workspace
        if _NO_PLAN.match(t) or re.fullmatch(r"(?:no|nope|nah)\b[\s,.!]*(?:(?:don'?t|do\s+not|keep|leave)\b.*)?", t, I):
            return Intent("assist", "text_assist", "clipboard", {"action": "cancel_code"})
        fresh = re.search(r"\b(?:better|good|improve|fix|optimi[sz]e|detail|clean|faster|simpl|short|long|more|less|"
                          r"but|instead|add|remove|comment)", t, I)
        if _YES_PLAN.match(t) or (not fresh and (yes_no(t) == "yes" or _YES_START.match(t) or _APPLY_CODE.search(t))):
            return Intent("assist", "text_assist", "clipboard", {"action": "apply_code"})
        if fresh and (_YES_START.match(t) or re.match(r"(?:no|but|and|now|also|instead)\b|make\s+it\b", t, I)) \
                and len(t.split()) <= 16:  # 'yes but make it shorter': a new version of the same selection
            return Intent("assist", "text_assist", "clipboard", {"action": "improve", "request": t})
    if not organizer.pending_active():
        return None
    if _YES_PLAN.match(t):
        return Intent("organize", "organize_files", "daily", {"action": "apply"})
    if _NO_PLAN.match(t):
        return Intent("organize", "organize_files", "daily", {"action": "cancel"})
    if _EDIT_PLAN.search(t) and len(t.split()) <= 30:
        return Intent("organize", "organize_files", "daily", {"action": "edit", "change": t})
    return None


def _ui_intent(t: str) -> Intent | None:
    """In-app control at 0 tokens: tab/page shortcuts, 'press ctrl t', 'type hello', 'click Wi-Fi'."""
    from jarvis.core import uiagent as ui
    if re.fullmatch(r"(?:please\s+)?(?:enable|turn\s+on|set\s*up|activate)\s+(?:the\s+)?screen\s+(?:control|agent)", t, I):
        return Intent("ui", "app_control", "windows", {"action": "enable"})
    if sc := ui.parse_shortcut(t):
        name = f"tab:{sc['n']}" if sc["action"] == "tab" else sc["action"]
        return Intent("ui", "app_control", "windows", {"action": "shortcut", "text": name, "app": sc["app"]})
    if p := ui.parse_press(t):
        return Intent("ui", "app_control", "windows", {"action": "press", "text": p["keys"], "app": p["app"]})
    if p := ui.parse_type(t):
        return Intent("ui", "app_control", "windows", {"action": "type", "text": p["text"], "app": p["app"]})
    if p := ui.parse_click(t):
        return Intent("ui", "app_control", "windows", {"action": "click", "text": p["name"], "app": p["app"]})
    return None


_OCR_VERB = r"(?:read|ocr|scan|extract|copy|get|grab|pull|type\s+out|transcribe|convert)"
_OCR_PIC = r"(?:photo|picture|pic|image|img|screenshot|screen\s*shot|handwriting|handwritten\s+\w+|scan|snap)"
_OCR_AREA = re.compile(r"^(?:please\s+|kurama\W+|can\s+you\s+)*(?:" + _OCR_VERB + r"\s+(?:the\s+)?(?:text\s+(?:from|in|on|of)\s+)?"
                       r"(?:this|a|an|the|my|that)?\s*(?:screen\s+)?(?:area|region|part(?:\s+of\s+(?:the|my)\s+screen)?|box|"
                       r"selection\s+of\s+the\s+screen)|ocr(?:\s+(?:this|it|that|the\s+screen))?)[\s.!?]*$", I)
_OCR_SCREEN = re.compile(r"^(?:please\s+)?(?:" + _OCR_VERB + r"\s+(?:all\s+)?(?:the\s+)?text\s+(?:on|from|in)\s+(?:the\s+|my\s+)?"
                         r"(?:whole\s+)?screen|what\s+(?:does|is)\s+(?:written\s+on\s+)?(?:my|the)\s+screen\s+(?:say|says))[\s.!?]*$", I)
_OCR_FILE = re.compile(r"\b(?:" + _OCR_VERB + r"|what\s+(?:does|is)|what's)\b.{0,40}\b" + _OCR_PIC + r"\b", I)


_QR = r"(?:qr(?:\s+code)?|q\.?\s?r\.?(?:\s+code)?|barcode|bar\s+code|scanner\s+code|cure\s+code|queue\s+are\s+code)"


URL_RE = re.compile(r"https?://\S+", I)
_RL_LIST = r"(?:reading\s+list|read[\s-]+later(?:\s+list)?|saved\s+(?:links|articles|pages))"
_ORD = {"first": 1, "1st": 1, "one": 1, "second": 2, "2nd": 2, "two": 2, "third": 3, "3rd": 3, "three": 3, "fourth": 4,
        "4th": 4, "four": 4, "fifth": 5, "5th": 5, "five": 5, "last": -1, "next": 1, "top": 1, "newest": 1, "latest": 1}


def _nth(t: str) -> int:
    if m := re.search(r"\b(?:number|no\.?|item|#)?\s*(\d{1,3})\b", t):
        return int(m.group(1))
    m = re.search(r"\b(" + "|".join(_ORD) + r")\b", t, I)  # (_NUM further down is the cardinal-number table)
    return _ORD[m.group(1).lower()] if m else 1


_WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
            "half an": 0.5, "an": 1, "a": 1}


def copy_history_intent(t: str) -> Intent | None:
    """'what did I copy 10 minutes ago', 'show my clipboard history', 'find the link I copied',
    'copy back number 2', 'clear my copy history' -> clipboard history (0 tokens)."""
    if re.fullmatch(r"(?:please\s+)?(?:what(?:'s|\s+is)\s+(?:on|in)\s+(?:my|the)\s+clipboard(?:\s+now)?|(?:read|show)\s+(?:me\s+)?"
                    r"(?:my|the)\s+clipboard)[\s?.!]*", t, I):
        return Intent("clip", "clipboard", "clipboard", {"action": "read"})
    hist = r"(?:clipboard|copy|copied)\s+history|(?:what|which)\s+(?:did|have)\s+i\s+(?:copy|copied)|things\s+i\s+copied|my\s+copies"
    if re.fullmatch(r"(?:please\s+)?(?:clear|delete|forget|erase)\s+(?:my\s+|the\s+)?(?:clipboard|copy|copied)\s+history[\s.!]*", t, I):
        return Intent("clip", "clipboard", "clipboard", {"action": "clear_history"})
    if m := re.fullmatch(r"(?:please\s+)?(?:copy|put|bring)\s+(?:back\s+)?(?:the\s+)?(?:number|item|no\.?)?\s*(\d{1,2}|" +
                         "|".join(_ORD) + r")(?:\s+(?:one|item))?(?:\s+(?:back|again))?(?:\s+(?:to|on)\s+(?:the\s+)?clipboard)?[\s.!]*", t, I):
        if re.search(r"\b(?:back|again|number|item|no)\b", t, I):
            return Intent("clip", "clipboard", "clipboard", {"action": "history", "restore": _nth(m.group(0))})
    if m := re.search(r"\b(?:the\s+)?(?P<q>[\w.-]+(?:\s+[\w.-]+)?)\s+(?:that\s+)?i\s+copied\b", t, I):
        if re.match(r"(?:please\s+)?(?:find|show|get|what\s+(?:was|is)|give\s+me|copy\s+back|where\s+is)\b", t, I):
            q = re.sub(r"^(?:the|a|that)\s+", "", m.group("q"), flags=I)
            if not re.search(r"\b(?:what|me|everything|all|thing|things|text|stuff|something|it)\b", q, I):
                return Intent("clip", "clipboard", "clipboard", {"action": "history", "query": q, "limit": 5})
    general = (re.search(r"\b(?:copy|copies|copied|clipboard)\b", t, I)
               and re.search(r"\bago\b|\b(?:history|last|earlier|before|previous|previously|recent|recently|today|list|"
                             r"all)\b|\bmy\s+cop(?:y|ies)\b|\bwhat\s+(?:did|have|was|were)\b", t, I)
               and not re.search(r"\b(?:file|files|folder|path|this|that|it)\s*(?:to|into|$)|\bcopy\s+(?:this|that|the\s+(?:file|"
                                 r"folder|link|text|code))\b|\bon\s+(?:my|the)\s+clipboard\s*\??$|^(?:read|what(?:'s|\s+is)\s+on)\b", t, I))
    if not (re.search(hist, t, I) or general) or len(t.split()) > 16:
        return None
    args: dict = {"action": "history", "limit": 8}
    if m := re.search(r"\blast\s+(\d{1,2})\b", t, I):
        args["limit"] = min(20, int(m.group(1)))
    if m := re.search(r"\b(\d{1,3}|" + "|".join(_WORDNUM) + r")\s+(min(?:ute)?s?|hours?|hrs?)\s+ago\b", t, I):
        n = int(m.group(1)) if m.group(1).isdigit() else _WORDNUM[m.group(1).lower()]
        args["minutes_ago"] = n * (60 if m.group(2).lower().startswith("h") else 1)
    return Intent("clip", "clipboard", "clipboard", args)


# --- saved links: 'this is the link for Claude Code, save it', 'give me my Facebook link' (0 tokens) ---
_L_WORD = r"(?:link|url|page|site|website|address)"
_L_STORE = r"(?:\s+(?:in|to|into|at)\s+(?:your\s+|my\s+|the\s+)?(?:memory|link\s+stor(?:e|er)|links?|store|bookmarks?|saved\s+links))?"
_L_SAVE = r"(?:save|store|keep|remember|bookmark|add)"


def links_intent(t: str) -> Intent | None:
    from jarvis.core import links
    low = t.strip(" .!?").lower()
    L = lambda a, **k: Intent("links", "saved_links", "links", {"action": a, **k})  # noqa: E731
    u = links.URL.search(t)
    url = {"url": u.group(0)} if u and re.search(r"https?://|www\.", u.group(0), I) else {}
    if links.pending():  # 'What should I call this link?' was asked
        if re.fullmatch(r"(?:no|cancel|never\s*mind|don'?t\s+save(?:\s+it)?|forget\s+it|leave\s+it)", low) or re.search(
                r"\b(?:already\s+(?:have|saved|got)|we\s+have\s+(?:it|this)|don'?t\s+(?:save|store)|remove\s+this\s+link)\b", low):
            return L("cancel")
        if m := re.fullmatch(r"(?:call|name|save|label)\s+it\s+(?:as\s+)?(?P<n>.+)|(?:it'?s|it\s+is|this\s+is)\s+(?:my\s+|the\s+)?(?P<n2>.+)", t.strip(" .!"), I):
            return L("name", name=m.group("n") or m.group("n2"))
        if len(low.split()) <= 5 and not t.strip().endswith("?"):
            return L("name", name=t.strip(" .!"))
    # save with a name
    for rx in (r"(?:this|that|it)\s+is\s+(?:the\s+|my\s+|a\s+)?" + _L_WORD + r"\s+(?:for|of|to)\s+(?:my\s+|the\s+)?(?P<n>[^,.;]+?)"
               r"(?:\s*[,.;]?\s*(?:so\s+|please\s+|and\s+|just\s+|can\s+you\s+)*(?:" + _L_SAVE + r")\b.*)?",
               r"(?:please\s+|can\s+you\s+)*" + _L_SAVE + r"\s+(?:(?:this|that|the|it)\s*" + _L_WORD + r"?|" + _L_WORD + r")\s*(?:of\s+(?:this|it)\s*)?" + _L_STORE
               + r"\s*(?:,\s*)?(?:as|called|named|under|with\s+(?:the\s+)?name|for)\s+(?:my\s+|the\s+)?(?P<n>.+?)" + _L_STORE,
               r"(?:please\s+|can\s+you\s+)*" + _L_SAVE + r"\s+(?:(?:this|that|the|it)\s*" + _L_WORD + r"?|" + _L_WORD + r")\s*(?:of\s+(?:this|it)\s*)?" + _L_STORE
               + r"\s*(?:,\s*)?(?:and\s+)?(?:call|name|say|label|title)\s+it\s+(?:as\s+)?(?P<n>.+)",
               r"(?:please\s+|can\s+you\s+)*" + _L_SAVE + r"\s+(?:my\s+|the\s+)(?P<n>[\w .+#-]{2,30}?)\s+" + _L_WORD + _L_STORE):
        if m := re.fullmatch(rx, links.URL.sub(lambda x: x.group(0) if not url else "", t.strip(" .!?")), I):
            n = links.clean_name(m.group("n"))
            if n and not re.fullmatch(r"(?:this|that|it)", n, I) and not re.search(r"\blater\b|\breading\b|\bread\b", n, I):
                return L("save", name=n, **url)
    # save, no name: KURAMA asks for one
    if re.fullmatch(r"(?:please\s+|can\s+you\s+)*" + _L_SAVE + r"\s+(?:the\s+)?(?:" + _L_WORD + r"\s+of\s+)?(?:this|that|the|it)\s*(?:"
                    + _L_WORD + r")?(?:\s+of\s+this)?" + _L_STORE[:-1] + r"(?:\s+please)?", low, I) or (
            re.fullmatch(r"(?:please\s+)?" + _L_SAVE + r"\s+(?:this\s+)?" + _L_WORD, low, I)):
        return L("save", **url)
    if re.fullmatch(r"(?:show|list|see|open|what\s+are|give\s+me|tell\s+me)?\s*(?:me\s+)?(?:all\s+)?(?:my\s+|the\s+)?(?:saved\s+links|links|"
                    r"link\s+stor(?:e|er)|bookmarks)(?:\s+(?:i|you)\s+(?:saved|have|kept))?", low, I) or re.fullmatch(
            r"what\s+links\s+(?:did\s+i|have\s+i|do\s+i\s+have|did\s+you)\s*(?:save|saved|keep|kept)?", low, I):
        return L("list")
    if m := re.fullmatch(r"(?:please\s+)?(?:delete|remove|forget)\s+(?:the\s+|my\s+)?(?P<n>.+?)\s+" + _L_WORD + _L_STORE, low, I):
        if links.lookup(m.group("n")):
            return L("delete", name=m.group("n"))
    if m := re.fullmatch(r"rename\s+(?:the\s+|my\s+)?(?P<n>.+?)\s+" + _L_WORD + r"\s+(?:to|as)\s+(?P<x>.+)", t.strip(" .!?"), I):
        if links.lookup(m.group("n")):
            return L("rename", name=m.group("n"), new_name=m.group("x"))
    # get / open by name; not saved -> None (the AI answers from its own knowledge)
    m = (re.fullmatch(r"(?:please\s+|can\s+you\s+)*(?P<v>give|send|show|tell|get|copy|share|open|find|what(?:'s|\s+is))\s+(?:me\s+)?(?:the\s+|my\s+)?"
                      + _L_WORD + r"\s+(?:of|for|to)\s+(?:my\s+|the\s+)?(?P<n>.+?)(?:\s+from\s+.+)?", low, I)
         or re.fullmatch(r"(?:please\s+|can\s+you\s+)*(?P<v>give|send|show|tell|get|copy|share|open|find|what(?:'s|\s+is))\s+(?:me\s+)?(?:the\s+|my\s+)"
                         r"(?P<n>[\w .+#-]{2,30}?)(?:'s)?\s+" + _L_WORD + r"(?:\s+from\s+.+)?", low, I))
    if m and links.lookup(m.group("n")):
        return L("open" if m.group("v").startswith("open") else "get", name=m.group("n"))
    return None


# --- the to-do list = short tasks for today / soon (reminders + to-dos); long tasks are goals; the code is the project ---
_TD_CMD = re.compile(r"\b(?:shut\s*down|restart|reboot|run|command|script|backup|open|launch|start|turn\s+(?:on|off)|lock|suspend|"
                     r"sleep|kill|close|install|download|send|message|email|every|daily|weekly|hourly)\b", I)


def todo_now_intent(t: str) -> Intent | None:
    """Three separate lists, 0 tokens: the TO-DO list (tasks to do; never rings), REMINDERS (alerts at a time) and the
    READING list. 'schedule reading the book at 11:45 pm' -> a reminder (NOT schedule_command, which runs computer
    commands); 'is there anything in my to-do', 'what is the current work I have to do' -> the to-do list; 'what are
    my reminders' -> the reminders; 'remove/move/rename X' -> whichever list X is on."""
    from jarvis.core import readlater, reminders, todos
    low = t.strip(" .!?").lower()
    T = lambda a, **k: Intent("todo", "todo", "todo", {"action": a, **k})  # noqa: E731  (to-do list)
    R = lambda a, **k: Intent("readlater", "read_later", "links", {"action": a, **k})  # noqa: E731  (reading list)
    S = lambda a, **k: Intent("schedules", "schedules", "schedule", {"action": a, **k})  # noqa: E731  (reminders)
    lead = r"(?:okay\W+|ok\W+|so\W+|please\W+|kurama\W+|can\s+you\s+|could\s+you\s+|now\W+)*"
    from jarvis.core import pageread
    if pageread.waiting() and yes_no(t) == "no":
        return Intent("page", "page_summary", "browser", {"action": "cancel"})
    if pageread.waiting() and yes_no(t) == "yes":
        return Intent("page", "page_summary", "browser", {"action": "detail"})
    if pageread.waiting():  # "Want a detailed overview?" was just asked
        if re.fullmatch(r"(?:yes|yeah|yep|sure|ok(?:ay)?|please|go\s+ahead|do\s+it|haan|ho)(?:\W+(?:please|do\s+it|give\s+(?:it|me)|"
                        r"detail(?:ed)?(?:\s+overview)?|show\s+me))*|(?:give|show|write)\s+(?:me\s+)?(?:the\s+|a\s+)?(?:detail(?:ed)?|full)"
                        r"(?:\s+(?:overview|summary|version))?", low, I):
            return Intent("page", "page_summary", "browser", {"action": "detail"})
        if re.fullmatch(r"(?:no|nope|nah|not\s+now|no\s+thanks?|that'?s\s+(?:it|enough))", low, I):
            return Intent("page", "page_summary", "browser", {"action": "cancel"})
    if len(low.split()) <= 24 and re.search(r"\b(?:web\s*site|web\s*page|this\s+(?:page|site|tab|article)|current\s+(?:page|tab|site))\b", low) \
            and re.search(r"\b(?:about|showing|shows|summar|explain|overview|what|tell)\w*", low) \
            and not re.search(r"\b(?:link|save|store|bookmark|open|close|read\s+later|reading\s+list|qr|screenshot|copy|when|changes?|"
                              r"updates?|watch|monitor|notify|alert|https?)\b", low):
        return Intent("page", "page_summary", "browser", {"action": "summary"})
    # 'I already read the attention is all you need paper' = that reading-list link is done
    if (m := re.fullmatch(lead + r"i\s+(?:have\s+|had\s+)?(?:already\s+|just\s+)?(?:read|finished(?:\s+reading)?|completed|done\s+reading)\s+"
                          r"(?:the\s+)?(?P<x>.+?)(?:\s+(?:already|now|today))?", low, I)) and readlater.find(m.group("x")):
        return R("remove", text=m.group("x"))
    if (m := re.fullmatch(lead + r"(?:mark|set|tick)\s+(?:the\s+)?(?P<n>first|second|third|last|1st|2nd|3rd|\d{1,2})\s*(?:one|task|item|link|article)?"
                          r"\s+(?:in|on|from)\s+(?:my\s+|the\s+)?(?:read(?:ing)?[\s-]*later(?:\s+list)?|reading\s+list)\s+(?:as\s+)?(?:done|read|finished|complete(?:d)?)", low, I)):
        n = _nth(m.group("n"))
        return R("done", n=n if n > 0 else len(readlater.unread()))
    # 'add a task' was asked without details: this short reply is the task (with an optional due date)
    if todos.pending() and len(low.split()) <= 14 and not t.strip().endswith("?") and not re.match(
            r"(?:no|cancel|never\s*mind|stop|what|why|how|open|close|show)\b", low):
        extra, rest = _extras(t.strip(" .!"))
        task = re.sub(r"^(?:it'?s|it\s+is|to|for)\s+", "", rest.strip(" ,."), flags=I)
        if len(task) >= 2:
            return T("add", task=task, **_todo_extra(extra))
    if todos.pending() and re.match(r"(?:no|cancel|never\s*mind)\b", low):
        todos.clear_pending()
    # 'what's on today' = the whole day: to-dos, reminders, classes, long tasks
    if re.fullmatch(lead + r"(?:what(?:'s|\s+is)\s+(?:on\s+)?(?:for\s+)?today|what\s+(?:do\s+i\s+have|have\s+i\s+got)\s+today|"
                    r"(?:my|today'?s)\s+(?:plan|schedule|day)(?:\s+today)?|what(?:'s|\s+is)\s+(?:my|the)\s+(?:plan|schedule)\s+(?:for\s+)?today|"
                    r"how\s+(?:does|is)\s+my\s+day\s+look(?:ing)?)", low, I):
        return T("today")
    # remove everything: the to-do list or the reading list (reminders are cancelled one by one)
    if m := re.fullmatch(lead + r"(?:remove|delete|clear|cancel|erase|empty)\s+(?:all|every|everything)?\s*(?:of\s+)?(?:the\s+|my\s+)?"
                         r"(?P<k>tasks?|to[\s-]?dos?|to[\s-]?do\s*list|list|reading\s+list|read\s+later(?:\s+list)?)(?:\s+for\s+me)?", low, I):
        if re.search(r"\ball\b|\bevery|\bclear\b|\bempty\b|\blist\b", low):
            return R("clear", text="read") if re.search(r"read", m.group("k")) else T("clear")
    rm = r"(?:remove|delete|cancel|drop|forget|take|cross|strike|tick|clear|done|finish(?:ed)?|complete(?:d)?)"
    if m := re.fullmatch(lead + r"(?P<v>" + rm + r")\s+(?:off\s+|with\s+)?(?:the\s+|my\s+)?(?P<n>first|second|third|fourth|fifth|last|1st|2nd|3rd|4th|5th|"
                         r"(?:number|no\.?|item)\s*\d{1,2}|\d{1,2})(?:\s+(?:one|task|item|reminder|to[\s-]?do|work))?(?P<tail>\s+(?:from|in|on|off)\s+.*)?", low, I):
        n = _nth(m.group("n"))
        if re.search(_RL_LIST, m.group("tail") or "", I):
            return R("done", n=n if n > 0 else len(readlater.ordered()))
        done = re.match(r"(?:done|finish|complete|tick)", m.group("v"))
        return T("done" if done else "delete", item=str(n if n > 0 else len(todos.items())))
    if m := re.fullmatch(lead + r"(?:no\W+)*(?:actually\W+)?" + rm + r"\s+(?:off\s+|out\s+)?(?:the\s+|my\s+)?(?P<x>.+?)\s+"
                         r"(?:from|off|out\s+of|in)\s+.*?\b(?P<k>to[\s-]?do(?:\s*list)?|list|tasks?|reminders?)\b.*", low, I):
        if m.group("k").startswith("reminder"):
            return S("cancel", item=m.group("x"))
        return T("delete", item=m.group("x"))
    if (m := re.fullmatch(lead + r"(?:no\W+)*(?:actually\W+)?" + rm + r"\s+(?:the\s+|my\s+)?(?P<x>.+?)(?:\s+(?P<k>task|reminder|to[\s-]?do|alarm))?", low, I)) \
            and not _LONG_WORDS.search(low):
        x = m.group("x")
        if m.group("k") not in ("reminder", "alarm") and todos.find(x):
            return T("done" if re.match(r"(?:done|finish|complete|tick)", low.split()[0] if low else "") else "delete", item=x)
        if reminders.named(x):
            return S("cancel", item=x)
    if (m := re.fullmatch(lead + r"(?:move|change|shift|reschedule|update|push|postpone|set)\s+(?:the\s+|my\s+)?(?P<x>.+?)(?:\s+(?P<k>task|reminder|to[\s-]?do|alarm))?"
                          r"\s+(?:to|for|at|till|until)\s+(?P<w>.+)", low, I)) and not _LONG_WORDS.search(low):
        from jarvis.core import when
        x, w = m.group("x"), m.group("w")
        if when.resolve(w, use_llm=False):
            if m.group("k") not in ("reminder", "alarm") and todos.find(x):
                return T("edit", item=x, due=w)
            if reminders.named(x):
                return S("move", item=x, when=w)
            if readlater.find(x):
                return R("reschedule", text=x, when=w)
    if m := re.fullmatch(lead + r"rename\s+(?:the\s+|my\s+)?(?P<x>.+?)(?:\s+(?P<k>task|reminder|to[\s-]?do))?\s+(?:to|as)\s+(?P<y>.+)", t.strip(" .!?"), I):
        x, y = m.group("x"), m.group("y")
        if (m.group("k") or "").lower() != "reminder" and todos.find(x):
            return T("edit", item=x, task=y)
        if reminders.named(x):
            return S("rename", item=x, text=y)
        if readlater.find(x):
            return R("rename", text=x + " » " + y)
    if (m := re.fullmatch(lead + r"(?:i\s+(?:have\s+)?(?:finished|completed|did|done)|i'?m\s+done\s+with|done\s+with|mark)\s+(?:the\s+)?(?P<x>.+?)"
                          r"(?:\s+as\s+(?:done|complete(?:d)?|finished))?", low, I)) and not re.search(r"\d", m.group("x")[:3]) \
            and todos.find(m.group("x")):
        return T("done", item=m.group("x"))
    # 'what's on my to-do', 'any task for me today' -> the to-do list; 'my reminders' -> the reminders; both -> the day
    if len(low.split()) <= 18 and re.search(r"\breminders?\b", low) and re.search(r"\b(?:tasks?|work|to[\s-]?dos?)\b", low) \
            and re.search(r"\b(?:show|what|tell|give|list|any)\b", low) and not re.search(r"\b(?:add|remove|delete|cancel|set)\b", low):
        return T("today")
    if re.fullmatch(lead + r"(?:what(?:'s|\s+is|\s+are)?\s+(?:my|the)\s+reminders?(?:\s+(?:for\s+)?today)?|(?:show|list|tell|give)\s+(?:me\s+)?"
                    r"(?:my\s+|the\s+|all\s+)?(?:reminders?|alarms?)(?:\s+(?:for\s+)?today)?|(?:is|are)\s+there\s+any\s+reminders?(?:\s+(?:today|for\s+me))?|"
                    r"(?:my\s+)?reminders?(?:\s+today)?)", low, I):
        return S("list")
    if re.fullmatch(lead + r"(?:"
                    r"(?:is|are)\s+there\s+(?:anything|something|any\s+(?:tasks?|work|to[\s-]?dos?))\s+(?:in|on|for)\s+(?:me\s+)?(?:my\s+|the\s+)?"
                    r"(?:to[\s-]?do(?:\s*list)?|list|today|now)(?:\s+(?:for\s+)?today)?"
                    r"|(?:is|are)\s+there\s+any\s+(?:tasks?|work|to[\s-]?dos?)(?:\s+for\s+me)?(?:\s+(?:today|now|left))?"
                    r"|what(?:'s|\s+is|\s+are)?\s+(?:in|on)\s+my\s+to[\s-]?do(?:\s*list)?(?:\s+today)?"
                    r"|what(?:'s|\s+is|\s+are)?\s+(?:my|the|today'?s)\s+(?:tasks?|to[\s-]?dos?)(?:\s+(?:for\s+)?today)?"
                    r"|what(?:'s|\s+is|\s+are)?\s+(?:the\s+)?(?:current\s+|next\s+)?(?:work|tasks?|things?)\s+(?:that\s+)?i\s+(?:have|need|got)\s+to\s+do(?:\s+(?:today|now|next))?"
                    r"|what\s+do\s+i\s+(?:have|need)\s+to\s+do(?:\s+(?:today|now|next))?"
                    r"|(?:show|tell|give)\s+(?:me\s+)?(?:my\s+|the\s+|today'?s\s+)?(?:tasks?|to[\s-]?dos?)(?:\s+(?:for\s+)?today)?"
                    r"|(?:my\s+)?(?:tasks?|to[\s-]?dos?)\s+(?:for\s+)?today)", low, I):
        return T("list")
    if len(low.split()) <= 12 and re.search(r"\b(?:tasks?|todos?|to-dos?|(?:my|any|the)\s+to\s+dos?)\b", low) and re.search(
            r"\b(?:any|anything|is\s+there|are\s+there|what|which|show|list|tell|have\s+i|do\s+i)\b", low) and not re.search(
            r"\b(?:long|code|coding|add|schedule|plan|remove|delete|clear|cancel|set|create|make|remind\s+me)\b", low):
        return T("list")
    if re.fullmatch(lead + r"(?:schedule|plan|add)\s+(?:a|the|my|one|new)?\s*(?:task|work|to[\s-]?do|thing)(?:\s+for\s+(?:me|the\s+task))?", low, I):
        return T("add", task="")  # asks what; the next short reply is the task
    # 'schedule reading the book at 11:45 pm' = an alert at that time: a reminder (a to-do never rings)
    m = re.fullmatch(r"(?:okay\W+|ok\W+|so\W+|please\W+|kurama\W+|can\s+you\s+|could\s+you\s+)*(?:schedule|plan)\s+(?P<x>.+)", low, I)
    if not m or _TD_CMD.search(m.group("x")) or re.search(r"\b(?:timer|alarm|meeting\s+with\s+kurama)\b", low):
        return None
    extra, rest = _extras(m.group("x"))
    if not extra.get("when"):
        return None
    task = re.sub(r"^(?:a|an|the|my|one)?\s*(?:new\s+)?(?:work|task|to[\s-]?do|job|thing|reminder)?\s*(?:for|to|of|:)?\s*", "", rest, flags=I)
    task = re.sub(r"\s+(?:for|to)\s*$", "", task, flags=I)
    task = re.sub(r"^(?:for|to)\s+", "", task.strip(" ,.-"), flags=I).strip(" ,.-")
    task = re.sub(r"\b(for|to)\s+\1\b", r"\1", task, flags=I)  # STT doubles: 'for for reading'
    task = re.sub(r"^\d+(?:-\d+)?\s+(?:tasks?|works?|things?)\s+(?:for|to)\s+", "", task, flags=I)  # '2-2 task for reading'
    task = re.sub(r"^(?:tasks?|works?)\s+(?:for|to)\s+", "", task, flags=I)
    if len(task) < 2:
        return None
    return Intent("remind", "add_reminder", "schedule", {"text": task, "when": extra["when"]}, task)


def _todo_extra(extra: dict) -> dict:
    """_extras() {'tag', 'when'} -> the todo tool's {'tag', 'due'}."""
    return {k: v for k, v in (("tag", extra.get("tag", "")), ("due", extra.get("when", ""))) if v}


# --- goals: long tasks (weeks-months): countdowns, daily check-ins, progress, report (0 tokens) ---
_G_NOUN = (r"exams?|tests?|finals|interview|deadline|submission|presentation|competition|trip|wedding|project|thesis|"
           r"course|semester|hackathon|internship|dissertation|goal|long[\s-]?(?:term\s+)?task|countdown")
_G_STOP = r"(?!(?:is|are|was|my|the|an?|our|will|and|to|in|on|of|that|which|for|it|i|starts?|ends?|after|within)\b)"
_G_PROGRESS = re.compile(
    r"(?:today\s*,?\s*|so\s+far\s*,?\s*)?(?:i|we)\s+(?:have\s+|had\s+|just\s+|only\s+)?(?:did|done|worked|finished|completed|"
    r"made|wrote|written|studied|learn(?:ed|t)|fixed|built|added|read|practi[cs]ed|started|spent|revised|solved|designed|"
    r"tested|deployed|coded|implemented|watched|attended|prepared|covered|reviewed|cleaned|planned|researched)\b"
    r"|(?:nothing|not\s+much|no\s+progress|didn'?t\s+do|i\s+didn'?t|i\s+could\s*n[o']t)\b", I)
_G_DEFAULT_Q = re.compile(r"(?:what|how)\b.*\b(?:do|doing|did|done|progress|going|work(?:ing|ed)?)\b", I)


def _goal(name: str):
    from jarvis.core import goals
    name = re.sub(r"\s+(?:goal|long\s+task|countdown|tracking)$", "", (name or "").strip(" ,.?!'"), flags=I)
    try:
        return goals.find(name) if name and len(name) <= 50 else None
    except Exception:
        return None


def _last_span(low: str) -> str:
    """'it's not 40 days, it's actually 30 days' -> 'in 30 days' (the LAST length/date said is the right one)."""
    spans = re.findall(r"\b\d{1,3}[\s-]*(?:days?|weeks?|months?|years?)\b", low)
    return f"in {spans[-1]}" if spans else low


def _goal_name(low: str, raw: str) -> str:
    m = re.search(r"(?:called|named|titled|(?:goal|long\s+task|project)\s*[:\-])\s*[\"']?(?P<n>[\w .'+#-]{2,40}?)[\"']?"
                  r"(?=\s*(?:,|\.|$|\s+(?:which|that|and|it|ends?|starts?|for|in|by|until|till|is|will)\b))", raw, I)
    if m:
        return m.group("n").strip()
    m = re.search(r"\b(?:my|an?|the|our)\s+(?P<n>(?:" + _G_STOP + r"[\w+#-]+\s+){0,3}?(?:" + _G_NOUN + r"))\b", low, I)
    n = m.group("n") if m else (re.search(r"\b(?:" + _G_NOUN + r")\b", low, I) or [""])[0]
    n = re.sub(r"^(?:new|big|long|long-term|upcoming|coming|next|own)\s+", "", n, flags=I)
    n = re.sub(r"\bexams\b", "exam", n, flags=I)
    return re.sub(r"\s*long[\s-]?(?:term\s+)?task$", "", n, flags=I) or "Goal"


_MONEYISH = re.compile(r"\b(?:spen[dt]|spending|expens\w*|expenc\w*|expecs\w*|money|budget|cost|costs|paid|rupees?|rs|"
                       r"income|salary|savings?|saved|kharcha|bills?)\b|खर्च", I)
_LONG_WORDS = re.compile(r"\b(?:long[\s-]?(?:term\s+)?(?:tasks?|works?|workers?|projects?)|goals?|monthly|countdowns?|"
                         r"(?:this|my|the|for\s+(?:the|my|this))\s+month)\b", I)


def goal_intent(t: str) -> Intent | None:
    """Long tasks only when the user says so: 'task / work / reminder' means the short to-do (owner). A sentence
    that names an item of the to-do list goes to the to-do unless 'long task / monthly / goal' is said."""
    i = _goal_intent(t)
    if i is None or i.args.get("action") in ("list", "add", "overview") or i.tool != "goals":
        return i
    low = t.strip(" .!?").lower()
    if _LONG_WORDS.search(low):
        return i
    from jarvis.core import reminders, todos
    if todos.find(low) or reminders.named(low) or re.search(r"\b(?:to[\s-]?do|reminders?|tasks?)\b", low):
        return None
    return i


def _goal_intent(t: str) -> Intent | None:
    """Long goals. 'my exam starts in 30 days, remind me every day', 'I started a project that ends in 6 months, ask
    me every day what I did', 'show my goals', 'how many days until my exam', 'what did we do today in the project',
    'Thesis update: wrote chapter 2', a plain 'today I fixed the login' right after a check-in question, 'move my
    exam to December 2', 'remind me about the exam twice a day', 'stop asking about the project', 'pause the X goal',
    'the exam is over', 'make the project report', 'link the project to this repo'."""
    from jarvis.core import goals
    low = t.strip(" .!?").lower()
    G = lambda a, **k: Intent("goals", "goals", "schedule", {"action": a, **k})  # noqa: E731
    # the Coding card's projects: list / pin / unpin / stop watching (the code itself is never deleted)
    if re.fullmatch(r"(?:show|list|what\s+are|which\s+are|give\s+me)?\s*(?:me\s+)?(?:all\s+)?(?:my\s+|the\s+)?(?:coding|code|git)\s+projects?"
                    r"(?:\s+(?:list|you\s+watch|you\s+track))?|which\s+projects?\s+(?:do\s+you|are\s+you)\s+(?:watch|track)\w*", low, I):
        return Intent("code", "time_machine", "git", {"action": "list"})
    if m := re.fullmatch(r"(?:pin|focus\s+on|always\s+show|show\s+only)\s+(?:the\s+|my\s+)?(?P<p>.+?)\s+(?:project|repo)(?:\s+on\s+the\s+coding\s+card)?"
                         r"|(?:my\s+)?main\s+(?:coding\s+)?project\s+is\s+(?P<p2>.+)", low, I):
        return Intent("code", "time_machine", "git", {"action": "pin", "project": m.group("p") or m.group("p2")})
    if re.fullmatch(r"unpin\s+(?:the\s+|my\s+)?(?:coding\s+)?project|(?:go\s+back\s+to\s+)?automatic\s+project", low, I):
        return Intent("code", "time_machine", "git", {"action": "unpin"})
    if re.fullmatch(r"(?:please\s+)?stop\s+(?:watching|tracking|looking\s+at|snapshotting)(?:\s+(?:a|the|my|this|that|some|all\s+the)?\s*(?:projects?|repos?|folders?))?", low, I):
        return Intent("code", "time_machine", "git", {"action": "forget", "project": ""})  # no name: show the list to pick from
    if m := re.fullmatch(r"(?:please\s+)?stop\s+(?:watching|tracking|looking\s+at)\s+(?:the\s+)?(?:project\s+)?(?:number\s+|no\.?\s*)?(?P<n>\d{1,2}|first|second|third|last)"
                         r"(?:\s+(?:one|project))?", low, I):
        return Intent("code", "time_machine", "git", {"action": "forget", "project": "#" + str(_nth(m.group("n")))})
    if m := re.fullmatch(r"(?:stop\s+(?:watching|tracking|looking\s+at)|forget|hide|remove|delete)\s+(?:the\s+|my\s+)?(?P<p>.+?)\s+(?:project|repo)"
                         r"(?:\s+from\s+(?:the\s+)?(?:coding(?:\s+card)?|list|kurama))?", low, I):
        return Intent("code", "time_machine", "git", {"action": "forget", "project": m.group("p")})
    if m := re.fullmatch(r"(?:watch|track)\s+(?:the\s+|my\s+)?(?P<p>.+?)\s+(?:project|repo)\s+again", low, I):
        return Intent("code", "time_machine", "git", {"action": "watch", "project": m.group("p")})
    # 'watch the project at ~/code/app', 'look at this project /media/.../X', 'start watching my KURAMA project', 'watch this project'
    if m := re.fullmatch(r"(?:please\s+)?(?:start\s+)?(?:watch(?:ing)?|track(?:ing)?|protect|monitor|look\s+at|keep\s+an\s+eye\s+on|snapshot)\s+"
                         r"(?:the\s+|my\s+|this\s+)?(?:(?:coding\s+)?(?:project|folder|repo)\s*)?(?:(?:at|in|from|called|named|:)\s+)?(?P<p>[~/].+|.+?)"
                         r"(?:\s+(?:project|folder|repo))?", t.strip(" .!?"), I):
        p = m.group("p").strip()
        if p.startswith(("/", "~")) or re.search(r"\b(?:project|folder|repo)\b", low):
            return Intent("code", "time_machine", "git", {"action": "protect", "project": "" if p.lower() in ("this", "it", "project", "this project") else p})
    # the CODE work (what you're doing in your project): 'code work for today', 'code worker', 'what do I have to do
    # in my code', 'related to code' -> where was I (git changes, errors, next step)
    if len(low.split()) <= 20 and (re.search(r"\b(?:code|coding|programming)\s+(?:work(?:er)?s?|tasks?|jobs?|progress|to[\s-]?dos?)\b", low)
                                   or re.search(r"\b(?:related\s+to|in|on|for)\s+(?:my\s+|the\s+)?(?:code|coding|project\s+code)\b", low)
                                   and re.search(r"\b(?:work|do|doing|task|left|pending|today)\b", low)) \
            and not re.search(r"\b(?:write|explain|fix|format|improve|review|run|test|commit|error)\b", low):
        return Intent("code", "where_was_i", "git", {})
    # an answer to the open check-in question
    if _G_PROGRESS.match(low) and len(low.split()) <= 80 and (w := goals.waiting()):
        return G("log", goal=w["id"], text=t.strip())
    # an explicit progress note: 'Thesis update: ...', 'update for the project: ...', 'today on KURAMA app, I ...'
    for rx in (r"(?P<g>[\w .'+#-]{2,40}?)\s+(?:update|progress|log)\s*[:\-–]\s*(?P<x>.+)",
               r"(?:progress\s+)?(?:update|log|note)\s+(?:for|on|to)\s+(?:the\s+|my\s+)?(?P<g>[\w .'+#-]{2,40}?)\s*[:\-–]\s*(?P<x>.+)",
               r"today\s+(?:in|on|for)\s+(?:the\s+|my\s+)?(?P<g>[\w .'+#-]{2,40}?)\s*,?\s+(?P<x>(?:i|we)\s+.+)"):
        if (m := re.fullmatch(rx, t.strip(), I)) and (g := _goal(m.group("g"))):
            return G("log", goal=g["id"], text=m.group("x").strip())
    if re.fullmatch(r"(?:please\s+)?(?:show|list|see|open|check|tell\s+me|what\s+are|what'?s|give\s+me)?\s*(?:me\s+)?(?:all\s+)?"
                    r"(?:my\s+|the\s+)?(?:goals?|long[\s-]?(?:term\s+)?tasks?|countdowns?)(?:\s+list)?", low, I):
        return G("list")
    # 'this month' is only a time: it means the long tasks only next to work words ('what do I have to do this month',
    # 'my tasks for the month'), never with money, weather, news... ('my spending this month' is the money tracker)
    month_work = re.search(r"\b(?:this|my|the|for\s+(?:the|my|this))\s+month\b", low) and re.search(
        r"\b(?:tasks?|works?|to\s+do|doing|plans?|planned|goals?|projects?|targets?|to[\s-]?dos?|deadlines?)\b", low)
    long_words = re.search(r"\bmonthly\s+(?:tasks?|work|goals?|targets?)\b|\blong[\s-]?(?:term\s+)?(?:tasks?|work(?:ers?)?|projects?)\b", low)
    if (month_work or long_words) and re.search(r"\b(?:what|which|show|list|tell|any|have\s+to|need\s+to|running)\b", low) \
            and len(low.split()) <= 18 and not goals.end_in(low) and not _MONEYISH.search(low):
        return G("list")
    # the whole Work card: 'what is in my working list right now? what project?', 'what am I working on'
    if len(low.split()) <= 22 and re.search(r"\b(?:what|show|tell|list|give|which|see|check)\b", low) and re.search(
            r"\b(?:work(?:ing)?\s+(?:list|card|section|board|plan)|my\s+work\b|working\s+on|on\s+my\s+plate|my\s+projects?|"
            r"what\s+projects?|which\s+projects?|my\s+goals?\s+and|everything\s+i\s+(?:have|need)\s+to\s+do)", low) \
            and not re.search(r"\b(?:about|explain|code|repo|function|files?|folders?|errors?|bug|git|commit|branch|ask\s+me|"
                              r"remind|was|were|last|yesterday|left\s+off)\b", low) and not goals.end_in(low):  # 'working on a project for 6 months, ask me' = new goal
        return G("overview")
    if m := re.fullmatch(r"how\s+many\s+(?:more\s+)?days\s+(?:are\s+|is\s+)?(?:left\s+|remaining\s+)?(?:until|till|to|before|for|in)\s+"
                         r"(?:my\s+|the\s+)?(?P<g>.+?)(?:\s+(?:left|remaining|now))?|when\s+is\s+(?:my\s+|the\s+)?(?P<g2>.+)", low, I):
        if g := _goal(m.group("g") or m.group("g2")):
            return G("status", goal=g["id"])
    if m := re.fullmatch(r"what\s+(?:did|have|has)\s+(?:we|i)\s+(?:do|done|did|work(?:ed)?\s+on|achieved?|finish(?:ed)?)\s+(?:today\s+|this\s+week\s+)?"
                         r"(?:in|on|for|with)\s+(?:the\s+|my\s+|this\s+|our\s+)?(?P<g>.+?)(?:\s+(?:today|so\s+far|till\s+now|until\s+now|"
                         r"this\s+week|yet))*|(?P<k>today'?s|daily|weekly|this\s+week'?s)\s+(?:summary|progress|update|report)\s+(?:of|for|on)\s+"
                         r"(?:the\s+|my\s+)?(?P<g2>.+)", low, I):
        if g := _goal(m.group("g") or m.group("g2")):
            return G("week" if re.search(r"week", low) else "today", goal=g["id"])
    if m := re.fullmatch(r"how\s+(?:is|are)\s+(?:my\s+|the\s+|our\s+)?(?P<g>.+?)\s+going|(?:my\s+|the\s+)?(?P<g2>.+?)\s+progress|"
                         r"(?:show\s+(?:me\s+)?)?(?:the\s+)?progress\s+(?:of|on|for)\s+(?:my\s+|the\s+)?(?P<g3>.+)", low, I):
        if g := _goal(m.group("g") or m.group("g2") or m.group("g3")):
            return G("status", goal=g["id"])
    if m := re.fullmatch(r"(?:please\s+)?(?:make|write|create|generate|prepare|give\s+me)\s+(?:the\s+|a\s+|my\s+)?(?:(?P<g>.+?)\s+)?"
                         r"(?:full\s+|final\s+|formatted\s+)?(?:report|documentation|document)(?:\s+(?:for|of|on)\s+(?:the\s+|my\s+)?(?P<g2>.+))?", low, I):
        n = m.group("g2") or m.group("g") or ""
        if n and (g := _goal(n)) and g["kind"] == "project":
            return G("report", goal=g["id"])
    if m := re.fullmatch(r"link\s+(?:the\s+|my\s+)?(?P<g>.+?)\s+(?:goal\s+)?(?:to|with)\s+(?:this\s+|my\s+|the\s+)?(?:git\s+)?"
                         r"(?:repo(?:sitory)?|git|code|coding\s+project|project\s+folder)", low, I):
        if g := _goal(m.group("g")):
            return G("link", goal=g["id"])
    # remove / delete / cancel a goal named anywhere in the sentence ('can we remove that 30 day exam routing')
    _FILEISH = r"\b(?:files?|folders?|photos?|pictures?|images?|pdfs?|docs?|documents?|trash|downloads?|screenshots?|videos?|songs?)\b|\.\w{2,4}\b"
    if re.search(r"\b(?:remove|delete|cancel|drop|clear|forget|erase|discard|get\s+rid\s+of|don'?t\s+need|no\s+longer\s+need)\b", low) \
            and not re.search(_FILEISH, low) and len(low.split()) <= 25 and _LONG_WORDS.search(low):
        g = goals.named_in(low) or (goals.last_touched() if re.search(r"\b(?:that|this|the)\s+(?:goal|countdown|long\s+task|"
                                                                        r"routine|tracking)\b", low) else None)
        if g:
            return G("delete", goal=g["id"])
    # postponed / moved: a new date -> change it, no date -> ask for it
    if re.search(r"\b(?:postponed?|delayed|pushed\s+back|rescheduled|shifted|moved|changed)\b", low) \
            and not re.search(r"\b(?:remove|delete|cancel|drop|clear|forget)\b", low) \
            and not re.search(_FILEISH, low) and (g := goals.named_in(low)):
        return G("edit", goal=g["id"], end=low) if goals.end_in(low) else G("postponed", goal=g["id"])
    # a correction right after adding/changing a goal: 'no, it's actually 30 days', 'make it 2 months'
    if len(low.split()) <= 25 and re.search(r"\b(?:not|actually|sorry|no|wrong|mistake|instead|make\s+it|change\s+it|set\s+it|"
                                            r"it'?s|it\s+is)\b", low) and goals.end_in(low) and (g := goals.last_touched()):
        other = goals.named_in(low)
        if not (re.search(r"\b(?:" + _G_NOUN + r")\b", low, I) and (not other or other["id"] != g["id"])):
            return G("edit", goal=g["id"], end=_last_span(low))  # (a different goal named = a new goal, not a fix)
    # changes to an existing goal
    if m := re.fullmatch(r"(?:please\s+)?(?:move|change|shift|push|postpone|set)\s+(?:the\s+|my\s+)?(?P<g>.+?)(?:'s)?\s+(?:date\s+|deadline\s+|"
                         r"end\s+date\s+)?to\s+(?P<d>.+)|(?:my\s+|the\s+)?(?P<g2>.+?)\s+(?:is\s+now|has\s+moved\s+to|moved\s+to|is\s+moved\s+to|"
                         r"date\s+is\s+now)\s+(?:on\s+)?(?P<d2>.+)", low, I):
        d = m.group("d") or m.group("d2")
        if goals.end_in(d) and (g := _goal(m.group("g") or m.group("g2"))):
            return G("edit", goal=g["id"], end=d)
    if m := re.fullmatch(r"(?:please\s+)?remind\s+me\s+(?:about|of|for)\s+(?:the\s+|my\s+)?(?P<g>.+?)\s+(?P<r>(?:only\s+)?(?:once|twice|thrice|"
                         r"\w+\s+times?|at\s+).*)", low, I):
        if goals.times_in(m.group("r")) and (g := _goal(m.group("g"))):
            return G("edit", goal=g["id"], remind=m.group("r"))
    if m := re.fullmatch(r"(?:please\s+)?(?:stop|turn\s+off|disable|no\s+more|cancel)\s+(?:the\s+|my\s+|all\s+)?(?P<g>.+?)\s+(?:reminders?|messages?|"
                         r"countdown)(?:\s+(?:please|now))?", low, I):
        if g := _goal(m.group("g")):
            return G("edit", goal=g["id"], remind="off")
    if m := re.fullmatch(r"(?:please\s+)?(?:stop|don'?t|do\s+not|no\s+need\s+to)\s+ask(?:ing)?\s+(?:me\s+)?(?:about\s+)?(?:the\s+|my\s+)?(?P<g>.+?)"
                         r"(?:\s+(?:any\s*more|every\s*day|daily))*", low, I):
        if g := _goal(m.group("g")):
            return G("edit", goal=g["id"], ask="off")
    if (m := re.fullmatch(r"(?:please\s+)?ask\s+me\s+about\s+(?:the\s+|my\s+)?(?P<g>.+?)\s+(?:every\s*day\s+|daily\s+)?(?P<r>at\s+.+)", low, I)) \
            and not goals.end_in(low) and goals.times_in(m.group("r")) and (g := _goal(m.group("g"))):
        return G("edit", goal=g["id"], ask_at=m.group("r"))
    if m := re.fullmatch(r"(?:please\s+)?(?P<a>pause|resume|restart|unpause|continue|delete|remove|finish|complete|end|stop)\s+(?:the\s+|my\s+)?"
                         r"(?P<g>.+?)\s+(?:goal|long\s+task|countdown|tracking)|(?:my\s+|the\s+)?(?P<g2>.+?)\s+(?:is|are)\s+(?:done|finished|over|"
                         r"complete(?:d)?|cancel(?:led|ed))(?:\s+now)?", low, I):
        if g := _goal(m.group("g") or m.group("g2")):
            a = (m.group("a") or "done").lower()
            a = {"pause": "pause", "resume": "resume", "restart": "resume", "unpause": "resume", "continue": "resume",
                 "delete": "delete", "remove": "delete"}.get(a, "done")
            return G(a, goal=g["id"])
    # a new goal: a long-task word + an end date ('in 30 days', 'for 6 months', 'on November 28')
    if not re.search(r"\b(?:" + _G_NOUN + r")\b", low, I) and not re.search(
            r"\b(?:ask|remind)\s+me\s+(?:every\s*day|daily)\b.*\bdays?\s+(?:left|remaining)\b", low, I):
        return None
    end = goals.end_in(low)
    if not end or re.match(r"(?:how|when|what|which|is|are|do|does)\b", low) or t.strip().endswith("?"):
        return None
    if not re.search(r"\b(?:remind|ask|track|countdown|count\s+down|goal|notify|message|tell\s+me|keep|report|document|"
                     r"start|create|add|new|set\s+up|follow)", low, I):
        return None  # 'I have an interview in 2 weeks' is just talk
    if re.search(r"\bremind\s+me\s+to\b", low, I) and not re.search(r"\bevery\s*day|daily|each\s+day|countdown|days?\s+left\b", low, I):
        return None  # 'remind me to submit the project in 3 days' = one reminder
    if m := re.search(r"\bask\s+me\s+(?:every\s*day|daily|each\s+day|every\s+evening|every\s+night)?\s*(?:,\s*)?(?P<q>.*?)(?=[,.;]|\s+and\s+(?:remind|make|send|write)|$)", low, I):
        q = m.group("q").strip()
        if q and not _G_DEFAULT_Q.search(q) and not re.fullmatch(r"(?:about\s+(?:it|this|the\s+progress)|at\s+.+)", q, I):
            return None  # a custom question: the AI words it (goals tool via the router)
    args: dict = {"name": _goal_name(low, t), "end": end.isoformat()}
    ask = re.search(r"\bask\s+me\b|\bcheck\s+(?:in|on)\s+(?:with\s+)?me\b|\breport\b|\bdocument", low, I)
    if ask:
        args["ask"] = "yes"
    for clause in re.split(r"[,.;]|\s+and\s+(?=(?:also\s+)?(?:ask|remind|make|write|send|keep|check)\b)", low):
        if re.search(r"\bask\b|\bcheck\s+in\b", clause) and (tt := goals.times_in(clause)):
            args["ask_at"] = tt[0]
        elif re.search(r"\bremind|\bmessage|\bnotif|\btimes?\s+a\s+day|\bonce\b|\btwice\b", clause) and goals.times_in(clause):
            args["remind"] = clause
    return G("add", **args)


_RL_CUE = r"(?:read(?:ing)?\s*later|reading\s+list|for\s+later|to\s+read\s+later)"
_TODO = r"(?:to[\s-]?do|todo)(?:\s*list)?"
_LIST_ANY = r"(?:" + _RL_LIST + r"|(?:to[\s-]?do|todo)\s*list|my\s+list|task\s+list)"
_MONS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
_WHEN_BIT = re.compile(
    r"\b(?:(?:in|after)\s+(?:\d+(?:\.\d+)?|an?|one|two|three|four|five|six|ten|fifteen|twenty|thirty|half\s+an?)\s*"
    r"(?:min(?:ute)?s?|hours?|hrs?|days?)\b|day\s+after\s+tomorrow|tomorrow|tonight|today"
    r"|(?:at|by|around)\s+\d{1,2}(?:[:.]\d\d)?(?:\s*(?:am|pm|a\.m\.|p\.m\.))?|\d{1,2}(?:[:.]\d\d)?\s*(?:am|pm|a\.m\.|p\.m\.)"
    r"|(?:on\s+)?" + _MONS + r"\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+20\d\d)?|(?:on\s+)?(?:the\s+)?\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONS
    + r"|(?:on\s+|next\s+|this\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"|(?:this|in\s+the)\s+(?:morning|afternoon|evening)|at\s+night)\b", I)
_TAG = re.compile(r"(?:\s+(?:with\s+(?:the\s+)?)?(?:tag(?:ged)?|label(?:led)?)\s+(?:as\s+|it\s+)?#?(?P<t>[\w-]{2,20})"
                  r"|\s*#(?P<t2>[a-z][\w-]{1,20}))", I)


def _take_tag(t: str) -> tuple[str, str]:
    m = _TAG.search(t)
    if not m:
        return "", t
    return (m.group("t") or m.group("t2")).lower(), (t[:m.start()] + t[m.end():]).strip()


def _take_when(t: str) -> tuple[str, str]:
    """'... after 2 hours' / 'at 2 pm' / 'tomorrow 2 pm' / 'November 28, 5 PM' -> (when text, the rest)."""
    hits = list(_WHEN_BIT.finditer(t))
    if not hits:
        return "", t
    a, b = hits[0].start(), hits[-1].end()
    phrase = t[a:b].strip(" ,")
    from jarvis.core import when
    if when.resolve(phrase, use_llm=False) is None:
        return "", t
    rest = (t[:a] + " " + t[b:]).strip()
    rest = re.sub(r"\s+(?:and\s+)?(?:i\s+(?:will|can|'ll|want\s+to|need\s+to)|i'll|remind\s+me\s+to|to)\s+(?:read|do|check)"
                  r"(?:\s+(?:this|it|that))?(?:\s+(?:link|page|article))?\s*$", "", rest, flags=I)
    return phrase, " ".join(rest.split()).strip(" ,.")


def _extras(t: str) -> tuple[dict, str]:
    tag, t = _take_tag(t)
    w, t = _take_when(t)
    return {k: v for k, v in (("tag", tag), ("when", w)) if v}, t


def todo_intent(t: str) -> Intent | None:
    """To-do list (its own list, not the reading list): add (with tag/due date, 'and remind me' = a linked reminder),
    show, done N."""
    low = t.strip(" .!?")
    # done / complete: 'done 2', 'mark 2 as done', 'I finished number 3', 'complete 1 from my list', 'tick 2'
    if re.fullmatch(r"(?:please\s+)?(?:(?:mark|set)\s+(?:number\s+|item\s+|no\.?\s*)?\d{1,3}\s+(?:as\s+)?(?:done|complete(?:d)?|finished|read)"
                    r"|(?:done|complete|completed|finished|tick|check\s+off)\s+(?:with\s+)?(?:number\s+|item\s+|no\.?\s*)?\d{1,3}"
                    r"|i\s+(?:have\s+)?(?:finished|completed|did|done)\s+(?:number\s+|item\s+|no\.?\s*)?\d{1,3}"
                    r"|(?:number\s+|item\s+)?\d{1,3}\s+is\s+(?:done|complete(?:d)?|finished))"
                    r"(?:\s+(?:in|on|from)\s+(?:my\s+|the\s+)?" + _LIST_ANY + r")?", low, I):
        if re.search(_RL_LIST + r"|\bread\b", low, I):
            return Intent("readlater", "read_later", "links", {"action": "done", "n": _nth(low)})
        return Intent("todo", "todo", "todo", {"action": "done", "item": str(_nth(low))})
    if re.fullmatch(r"(?:please\s+)?(?:remove|delete)\s+(?:number\s+|item\s+)?\d{1,3}\s+(?:from|in|on)\s+(?:my\s+|the\s+)?" + _LIST_ANY, low, I):
        if re.search(_RL_LIST, low, I):
            return Intent("readlater", "read_later", "links", {"action": "remove", "n": _nth(low)})
        return Intent("todo", "todo", "todo", {"action": "delete", "item": str(_nth(low))})
    # show
    if m := re.fullmatch(r"(?:please\s+|kurama\W+)*(?:show(?:\s+me)?|what(?:'s|\s+is|\s+are)?(?:\s+(?:on|in))?|list|open|see|check|give\s+me|read)?"
                         r"\s*(?:all\s+)?(?:my\s+|the\s+)?(?P<k>" + _TODO + r"|list|tasks|task\s+list)(?:\s+items?)?(?P<x>(?:\s+(?:for\s+)?today|"
                         r"\s+(?:tagged|with\s+tag|for)\s+#?[\w-]+|\s*#[\w-]+)?)", low, I):
        tag = re.search(r"#?([\w-]+)$", m.group("x").strip()).group(1).lower() if m.group("x").strip() and \
            not m.group("x").strip().endswith("today") else ""
        k = m.group("k").lower()
        if (k == "list" or not re.search(r"list|todo|-", k)) and not re.search(r"\bmy\b", low):
            return None  # 'what to do' is a question, 'my to do' / 'to-do list' is the list
        return Intent("todo", "todo", "todo", {"action": "list"} | ({"tag": tag} if tag else {}))
    # add
    m = (re.fullmatch(r"(?:please\s+|kurama\W+|can\s+you\s+)*(?:add|put|save|note|write|keep|include)\s+(?:down\s+)?(?P<x>.+?)\s+"
                      r"(?:to|in|on|into|onto)\s+(?:my\s+|the\s+)?" + _TODO + r"(?P<r>.*)", low, I)
         or re.fullmatch(r"(?:please\s+|kurama\W+)*(?:add|new|create|make)\s+(?:a\s+)?(?:new\s+)?(?:to[\s-]?do|todo)(?:\s+item)?\s*[:,-]?\s+(?P<x>.+?)(?P<r>)", low, I)
         or re.fullmatch(r"(?:to[\s-]?do|todo)\s*:\s*(?P<x>.+?)(?P<r>)", low, I))
    if m:
        body = m.group("x") + " " + m.group("r")
        remind = re.search(r"\b(?:and\s+)?remind\s+me\b(?P<w>.*)$", body, I)  # '... and remind me Thursday at 6'
        if remind:
            body = body[:remind.start()]
        extra, task = _extras(body)
        task = re.sub(r"^(?:a\s+(?:task|reminder)\s+(?:to\s+)?|to\s+)", "", task, flags=I).strip(" ,.")
        pr = "high" if re.search(r"\b(?:urgent|important|high\s+priority|asap)\b", task, I) else ""
        task = re.sub(r"[\s,]*\b(?:it'?s\s+)?(?:urgent|important|high\s+priority|asap)\b", "", task, flags=I).strip(" ,.")
        if task:
            args = {"action": "add", "task": task, **_todo_extra(extra)} | ({"priority": pr} if pr else {})
            if remind:
                args["remind"] = (remind.group("w").strip(" ,.") or extra.get("when", "")).strip()
            return Intent("todo", "todo", "todo", args)
    return None


def read_later_intent(t: str) -> Intent | None:
    """'read this later', 'I will read this later', 'save this link for later', 'add this to my reading list',
    'can you keep this link for read later', 'give me the read later link I gave you', 'what's on my reading list',
    'open the first article from my reading list', 'mark 2 as read'. A time ('save this to read later, I'll read it
    after 2 hours / at 2 pm / tomorrow 2 pm / November 28 5 pm') and a tag (#work) are passed on."""
    if td := todo_intent(t):
        return td
    if re.search(_RL_CUE, t, I) and len(t.split()) <= 24:
        if re.search(r"\b(?:give|show|tell|send|what(?:'s|\s+is|\s+was)|which|where)\b.{0,40}\b(?:link|links|url|page|article)\b"
                     r"|\b(?:link|links|url)\b.{0,30}\b(?:i\s+(?:gave|give|saved|save|added|kept)|you\s+saved)\b", t, I):
            return Intent("readlater", "read_later", "links", {"action": "last" if not re.search(
                r"\b(?:links|all|list|everything)\b", t, I) else "list"})
        if re.search(r"\b(?:keep|save|store|add|put|bookmark|remember|note)\b", t, I) and not re.search(
                r"\b(?:open|show|remove|delete|mark)\b", t, I):
            u = URL_RE.search(t)
            extra, _ = _extras(URL_RE.sub(" ", t))
            return Intent("readlater", "read_later", "links", {"action": "add", "url": u.group(0) if u else "", **extra})
    plain = URL_RE.sub(" ", t)
    extra, rest = _extras(plain)
    if re.fullmatch(r"(?:please\s+|kurama\W+)*(?:i(?:'ll|\s+will)\s+read\s+(?:this|it|that)(?:\s+(?:link|page|article|post|video))?\s+later|"
                    r"read\s+(?:this|it|that)(?:\s+(?:link|page|article|post|video))?\s+later|"
                    r"(?:save|keep|bookmark|add)\s+(?:this|that|it|the|these)?\s*(?:link|links|page|article|tab|post|video)?\s*"
                    r"(?:for\s+later|to\s+(?:my\s+)?" + _RL_LIST + r"|(?:to\s+)?read\s+later)|read\s+later)[\s.!]*", t, I) or (
            extra.get("when") and re.fullmatch(
                r"(?:please\s+|kurama\W+)*(?:(?:i(?:'ll|\s+will|\s+want\s+to)|let\s+me|remind\s+me\s+to)\s+)?read\s+(?:this|it|that)"
                r"(?:\s+(?:link|page|article|post|video))?(?:\s+later)?[\s.!]*", rest, I)):
        u = URL_RE.search(t)
        return Intent("readlater", "read_later", "links", {"action": "add", "url": u.group(0) if u else "", **extra})
    if not re.search(_RL_LIST, t, I):
        return None
    if re.search(r"\b(?:open|read|show\s+me\s+the)\b.*\b(?:article|link|item|page|one|number|\d)\b", t, I):
        return Intent("readlater", "read_later", "links", {"action": "open", "n": _nth(t)})
    if re.search(r"\bmark\b.*\bread\b|\b(?:done|finished)\s+(?:with|reading)\b", t, I):
        return Intent("readlater", "read_later", "links", {"action": "done", "n": _nth(t)})
    if re.search(r"\b(?:remove|delete)\b", t, I):
        return Intent("readlater", "read_later", "links", {"action": "remove", "n": _nth(t)})
    if re.search(r"\b(?:show|what|list|open|see|check|my)\b", t, I) and len(t.split()) <= 12:
        return Intent("readlater", "read_later", "links", {"action": "list", "text": "read"})
    return None
    if re.search(r"\b(?:open|read|show\s+me\s+the)\b.*\b(?:article|link|item|page|one|number|\d)\b", t, I):
        return Intent("readlater", "read_later", "links", {"action": "open", "n": _nth(t)})
    if re.search(r"\bmark\b.*\bread\b|\b(?:done|finished)\s+(?:with|reading)\b", t, I):
        return Intent("readlater", "read_later", "links", {"action": "read", "n": _nth(t)})
    if re.search(r"\b(?:remove|delete)\b", t, I):
        return Intent("readlater", "read_later", "links", {"action": "remove", "n": _nth(t)})
    if re.search(r"\b(?:show|what|list|open|see|check|my)\b", t, I) and len(t.split()) <= 12:
        return Intent("readlater", "read_later", "links", {"action": "list"})
    return None


def qr_intent(t: str) -> Intent | None:
    """'scan the qr code on my screen', 'read this qr', 'scan the qr and open it', 'scan the wifi qr and connect',
    'scan the qr in this photo', 'scan the qr in this area' -> scan_qr (0 tokens)."""
    if not re.search(r"\b" + _QR + r"\b", t, I) or not re.search(r"\b(?:scan|read|open|decode|what(?:'s|\s+is)|check|"
                                                                r"connect|join|get)\b", t, I) or len(t.split()) > 18:
        return None
    if re.search(r"\b(?:make|create|generate|share|show\s+(?:my|the)\s+wifi)\b", t, I):
        return None  # making a QR (share_wifi / wifi_share) is not scanning one
    args: dict = {"source": "screen"}
    if re.search(r"\b(?:area|region|part|box)\b", t, I):
        args["source"] = "area"
    elif re.search(r"\b(?:copied|clipboard)\b", t, I):
        args["source"] = "clipboard"
    elif re.search(r"\b(?:photo|picture|pic|image|img|screenshot)\b", t, I):
        f = re.search(r"([\w.~/-]+\.(?:png|jpe?g|webp|bmp|gif))\b", t, I)
        args.update(source="file", path=f.group(1) if f else "this")
    if re.search(r"\b(?:and|then)\s+open\b|\bopen\s+(?:the|this|that)\s+" + _QR, t, I):
        args["open_link"] = True
    if re.search(r"\b(?:connect|join)\b", t, I):
        args["connect"] = True
    return Intent("qr", "scan_qr", "screen", args)


def ocr_intent(t: str) -> Intent | None:
    """Reading the text in a picture. 'read this area' / 'the selected part of this image' -> drag a box;
    'what is written in this paper / image / on my screen' -> the window the user looks at; 'the copied image'
    -> clipboard; a named file / 'my latest photo' -> that file. (Tesseract, 0 tokens; the AI only for handwriting.)"""
    if re.match(r"i\s+(?:have\s+|had\s+)?(?:already\s+|just\s+)?(?:read|finished)\b", t.strip(), I):
        return None  # 'I already read X' = news about the user's reading, not 'read the screen'
    if _OCR_AREA.match(t):
        return Intent("ocr", "read_text", "screen", {"source": "area"})
    if _OCR_SCREEN.match(t):
        return Intent("ocr", "read_text", "screen", {"source": "window" if re.search(r"\b(?:whole|entire|full|all)\b", t, I)
                                                     else "area"})
    reading = re.search(r"\b(?:writ(?:ten|ing|e)|says?|text|read|ocr|transcribe|type\s+out|words?|letters?)\b|लेखिएको|लेखेको", t, I)
    picture = re.search(r"\b(?:" + _OCR_PIC + r"|paper|page|note|notes|board|whiteboard|slide|screen|document|letter)\b", t, I)
    if not (reading and picture) or len(t.split()) > 22:
        return None
    if re.search(r"\b(?:take|capture)\s+(?:a\s+)?screenshot\b|\b(?:describe|caption|who\s+is|where\s+is|of\s+what|is\s+this\s+"
                 r"(?:photo|picture|image)\s+of)\b|\b(?:send|share|delete|open|resize|compress|rename|organi[sz]e|move|"
                 r"set\s+as|write\s+(?:a|an|the|my)|word\s+document|text\s+file|screen\s+(?:time|brightness|lock))\b", t, I):
        return None  # about the picture itself / a file / writing something new, not reading its text
    if re.search(r"\b(?:copied|clipboard)\b", t, I):
        return Intent("ocr", "read_text", "screen", {"source": "clipboard"})
    if f := re.search(r"([\w.~/-]+\.(?:png|jpe?g|webp|bmp|tiff?|gif|heic))\b", t, I):
        return Intent("ocr", "read_text", "screen", {"source": "file", "path": f.group(1)})
    if re.search(r"\b(?:latest|newest|last|downloaded|recent)\b", t, I):
        return Intent("ocr", "read_text", "screen", {"source": "file", "path": "latest"})
    if re.search(r"\b(?:whole|entire|full|all\s+of)\b|\bwithout\s+select", t, I):
        return Intent("ocr", "read_text", "screen", {"source": "window"})
    return Intent("ocr", "read_text", "screen", {"source": "area"})  # the owner wants to drag a box first


_NO_GATE = {"unlock", "error", "study", "say", "slash", "assist", "agent", "coding"}  # exact answers / commands, not guesses


def meaning_ok(text: str, it: Intent) -> bool:
    """A shortcut's pattern matched; it runs only if the MEANING agrees: its area is within MEANING_GATE_MARGIN of the
    best area for the request, and no earlier correction said this wording isn't this shortcut. Model not loaded
    yet: the pattern decides this once (the model starts in the background)."""
    from jarvis.core import learn, semantic
    if it.name in _NO_GATE or it.tool.startswith("_") or it.group in ("self", ""):
        return True
    if not semantic.ready():
        semantic.warm_soon()
        return True
    if it.known and len(it.known) >= 2:  # 'Open setting.' -> 'Open X.': the name's own meaning (window settings,
        text = re.sub(re.escape(it.known), "X", text, flags=I)  # the Telegram area) used to veto opening the app
    ranked = [(g, s) for g, s in semantic.scores(text) if g != semantic.CHAT]
    if not ranked:  # non-English script: the model can't judge
        return True
    if semantic.last_vec is not None and learn.vetoed(semantic.last_vec, it.name):
        return False
    best = dict(ranked)
    top = ranked[0][1]
    # always by meaning (Phase C): it used to apply only when the model was >= 0.85 sure, and most requests score
    # 0.70-0.80, so in practice the pattern alone decided
    return best.get(it.group, 0.0) >= top - config.MEANING_GATE_STRICT.get(it.name, config.MEANING_GATE_MARGIN)


_CODE_THING = re.compile(r"\b(?:function|method|class|def|variable|func)\b", I)


def _code_not_file(it: Intent | None) -> Intent | None:
    """'where is this function' / 'find this function in this code base' is code, not a file on the disk: go to
    where it is defined in the VS Code project (the highlighted name when none is given)."""
    if it is None or it.tool != "find_files":
        return it
    q = f"{it.args.get('query', '')} {it.args.get('path', '')}"
    if not _CODE_THING.search(q):
        return it
    name = re.sub(r"\b(?:this|that|the|my|a|in|code\s*base|codebase|project|repo|file|function|method|class|def|"
                  r"variable|func)\b", " ", it.args.get("query", ""), flags=I).strip(" .?")
    return Intent("codenav", "code_nav", "codequality", {"action": "find", "name": name})


_LINK = re.compile(r"https?://(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)/\S+", I)
_PLAY_LINK = re.compile(r"(?:please\s+)?(?:play|listen\s+to|start)(?:\s+(?:this|it|that))?(?:\s+(?:song|music|track|"
                        r"video|audio))?(?:\s+(?:only|just))?(?:\s+(?:in|on|with|using)\s+(?:your|the|my|kurama'?s?)?\s*"
                        r"(?:own\s+)?(?:music\s+)?player)?(?:\s+(?:please|now))?", I)


def link_play_intent(text: str) -> Intent | None:
    """A YouTube link + 'play this (song) (in your music player)' as the WHOLE request: KURAMA's own player
    (sound only), never the browser. The link keeps its exact letters (video ids are case-sensitive)."""
    m = _LINK.search(text or "")
    if not m:
        return None
    rest = " ".join((text[:m.start()] + " " + text[m.end():]).split()).strip(" .,!?")
    if not rest or not _PLAY_LINK.fullmatch(rest):
        return None
    return Intent("music", "music", "media", {"action": "url", "query": m.group(0)})


_CLEAN_ASK = re.compile(r"(?:please\s+)?(?:can\s+you\s+)?(?:clean|clear|optimi[sz]e|free|boost|speed\s+up|tidy)(?:\s+up)?"
                    r"(?:\s+(?:my|the|your|all))?\s+(?P<w>ram|memory|storage|disk(?:\s+space)?|space|drive|cache|caches|"
                    r"kurama|yourself|kurama'?s?\s+cache)(?:\s+(?:please|now|too))?", I)


def clean_intent(text: str) -> Intent | None:
    """'clean my RAM' / 'optimize ram' / 'clean my storage' / 'clean KURAMA' as the WHOLE request: the safe cleanup."""
    t = " ".join((text or "").split()).strip(" .!?")
    if sl := re.fullmatch(r"/clean(?:\s+(\S+))?", t, I):  # before the name is stripped as a wake word
        from jarvis.core import cleanup
        return Intent("cleanup", "cleanup", "system", {"action": cleanup.word(sl.group(1) or "ram")})
    m = _CLEAN_ASK.fullmatch(t)
    if not m:
        return None
    w = m.group("w").lower()
    action = "ram" if w in ("ram", "memory") else "kurama" if w.startswith(("kurama", "yourself")) else "storage"
    return Intent("cleanup", "cleanup", "system", {"action": action})


_TO_FILE = re.compile(r"(?:please\s+)?(?:write|put|paste|insert|save|add|copy|replace)\s+(?:this|the|that|it|your|all)?\s*"
                      r"(?:new\s+|generated\s+|whole\s+)?(?:code|script|module|it)?\s*(?:in|into|to|on|inside|at)\s+"
                      r"(?:the\s+|my\s+|this\s+)?(?:open(?:ed)?\s+|oopen\s+|current\s+)?(?:file|path|vs\s*code|editor)?\s*"
                      r"(?P<p>[\w./~-]+\.\w{1,5}|/\S+)?\s*(?:file)?\s*(?:\.\.?\s*)?(?:(?:only|just)\s+(?:the\s+)?code)?", I)


_VSCODE_NAME = re.compile(r"\b(?:vs\s*code|vscode|visual\s+studio\s+code)\b", I)
_CODE_ASK = re.compile(r"\b(?:write|writ|generate|create|make|put|paste|insert|add|save|copy|replace|implement|code)\b", I)
_CODE_WORD = re.compile(r"\b(?:code|codes|function|module|script|class|program|it)\b", I)
_INTO_FILE = re.compile(r"\b(?:in|into|to|on|inside)\s+(?:the\s+|this\s+|my\s+|that\s+)?(?:open(?:ed)?\s+|oopen\s+|"
                        r"current\s+)?(?:file|path|vs\s*code|editor)\b|\b(?:in|into|to|on)\s+(?:this\s+|the\s+)?"
                        r"(?:path\s+)?(?:/\S+|[\w-]+\.(?:py|js|ts|sh|go|rs|java|cpp|c|rb|php|html|css|sql))\b", I)


def to_file_intent(text: str) -> Intent | None:
    """Code into a file, like an editor assistant: '<what the code should do> ... write it in this file / test.py /
    on this path /x/test.py' or 'write the generated code in the open file'. The tool writes into the file open in
    VS Code (or the path): it generates from the description, or uses the last code request's code."""
    t = " ".join((text or "").split())
    from jarvis.core import assist
    if assist.pending_code_active():  # a change waits: 'yes / replace it' applies THAT one
        return None
    if re.fullmatch(r"(?:please\s+)?(?:replace|put|add|use|apply|insert|paste)\s+(?:it|this|that|the\s+code|this\s+code)"
                    r"(?:\s+(?:in|into|to)\s+(?:the\s+|my\s+)?(?:file|code|editor))?(?:\s+(?:please|now))?[\s.!]*", t, I):
        from jarvis.core import context
        from jarvis.tools.general.code_to_file import latest_code
        if context.editor_open() and latest_code().strip():  # the code KURAMA just wrote -> the open file (asks yes)
            return Intent("tofile", "code_to_file", "clipboard", {"request": ""})
    if re.search(r"\b(?:complete|finish)\b", t, I) and re.search(r"\b[\w-]+\.(?:py|js|ts)\b|\b(?:code|function|file|"
                                                                  r"class|method)\b", t, I) and len(t) < 300:
        from jarvis.core import context
        if not context.snapshot()["selection"] and context.editor_open():  # selected code: assist completes that
            return Intent("tofile", "code_to_file", "clipboard", {"request": t})
    bare = _VSCODE_NAME.sub(" ", t)  # the 'code' in 'VS Code' is the app's name, not a request for code
    from jarvis.core.planner import split_clauses  # the ask and 'into the file' must be in ONE part: 'create a folder
    one = any(_CODE_ASK.search(_VSCODE_NAME.sub(" ", c)) and _INTO_FILE.search(c)  # X and OPEN it in vs code' is two
              for c in split_clauses(t))  # tasks, not code: the part saying 'into the file' must ask to write (11-01)
    if not (one and _CODE_ASK.search(bare) and _CODE_WORD.search(bare) and _INTO_FILE.search(t)):
        return _TO_FILE.fullmatch(t.strip(" .!?")) and Intent("tofile", "code_to_file", "clipboard", {"request": t}) or None
    p = re.search(r"(?<!\w)(/[^\s]+\.\w{1,5})\b", t)
    return Intent("tofile", "code_to_file", "clipboard", {"request": t, "path": p.group(1) if p else ""})


# The everyday laptop commands, said as the WHOLE request (typos ok: "shutodwn"): 0 tokens, never the AI.
# Power ones still ask yes/no (their tools are `confirm`).
_DAILY: list[tuple[tuple[str, ...], Intent]] = [
    (("shutdown", "shut down", "power off", "turn off"), Intent("control", "power_off", "power", {"action": "shutdown"})),
    (("restart", "reboot"), Intent("control", "power_off", "power", {"action": "restart"})),
    (("log out", "logout", "sign out"), Intent("control", "power_off", "power", {"action": "logout"})),
    (("sleep", "suspend", "go to sleep laptop"), Intent("sleep", "suspend_computer", "power", {})),
    (("lock", "lock screen", "lock the screen"), Intent("lock", "lock_screen", "system", {})),
    (("time", "what time is it", "what is the time"), Intent("time", "get_time", "general", {})),
    (("date", "what is the date", "today date"), Intent("date", "get_date", "general", {})),
    (("weather", "what is the weather"), Intent("weather", "weather", "web", {})),
    (("battery", "battery status", "battery percentage"), Intent("battery", "battery_status", "system", {})),
    (("ram", "ram usage", "memory usage"), Intent("cleanup", "cleanup", "system", {"action": "ram"})),
    (("laptop status", "system status", "laptop health", "pc status"), Intent("doctor", "laptop_doctor", "system", {"action": "check"})),
    (("wifi speed", "internet speed", "speed test", "net speed"), Intent("internet", "internet_doctor", "system", {"action": "speed"})),
    (("internet", "is internet working", "check internet"), Intent("internet", "internet_doctor", "system", {"action": "check"})),
]
_FILLER = re.compile(r"\b(?:please|pls|now|the|my|this|laptop|computer|pc|system|kurama|hey|ok|okay|can\s+you|do|a)\b", I)


_LATER = re.compile(r"(?:please\s+)?(?P<k>shut\s*down|shutdown|turn\s+off|power\s+off|switch\s+off|restart|reboot)"
                    r"(?:\s+(?:the|my))?(?:\s+(?:laptop|computer|pc|system))?\s+(?P<w>(?:(?:after|in|at|within)\s+)?.+)", I)
_CANCEL_OFF = re.compile(r"(?:please\s+)?(?:cancel|stop|abort|don'?t|do\s+not)\s+(?:the\s+)?(?:scheduled\s+)?"
                         r"(?:shut\s*down|shutdown|restart|reboot|power\s+off)(?:\s+(?:timer|the\s+laptop|laptop))?|"
                         r"(?:shut\s*down|shutdown|restart|reboot)\s+(?:cancel|stop|off)", I)  # '/shutdown cancel'
_WHEN_OFF = re.compile(r"(?:shut\s*down|shutdown|restart|reboot)\s+(?:status|time\s+left|when)|when\s+(?:will|is)\s+(?:the\s+|my\s+)?(?:laptop|computer|pc|it)\s+(?:going\s+to\s+)?"
                       r"(?:shut\s*down|shutdown|restart|turn\s+off)|(?:is\s+)?(?:a\s+)?shutdown\s+(?:timer\s+)?"
                       r"(?:set|scheduled|timer)", I)


def shutdown_later_intent(text: str) -> Intent | None:
    """'shutdown after 90 min' / 'restart the laptop in 2 hours' / 'cancel shutdown' / 'when will the laptop shut
    down': Ubuntu's scheduled shutdown (asks first)."""
    t = " ".join((text or "").split()).strip(" .!?")
    if (m := _LATER.fullmatch(t)) and re.search(r"\d|half|an?\s+hour", m.group("w"), I):
        kind = "restart" if m.group("k").lower() in ("restart", "reboot") else "shutdown"
        return Intent("shutdown_timer", "shutdown_timer", "power", {"action": "set", "when": m.group("w"), "kind": kind})
    if _CANCEL_OFF.fullmatch(t):
        return Intent("shutdown_timer", "shutdown_timer", "power", {"action": "cancel"})
    if _WHEN_OFF.fullmatch(t):
        return Intent("shutdown_timer", "shutdown_timer", "power", {"action": "status"})
    return None


def daily_intent(text: str) -> Intent | None:
    """'shutodwn', 'shutdown laptop', 'wifi speed', 'ram' ...: the whole request (fillers aside) is one of the
    everyday commands, allowing a typo or two."""
    import difflib
    t = re.sub(r"[^\w\s]", " ", (text or "").lower())
    core = " ".join(_FILLER.sub(" ", t).split()) or " ".join(t.split())
    if not core or len(core) > 30:
        return None
    names = {n: it for ns, it in _DAILY for n in ns}
    hit = names.get(core) or names.get(" ".join(t.split()))
    if hit is None and len(core) >= 5:
        close = difflib.get_close_matches(core, list(names), n=1, cutoff=0.79 if len(core) >= 6 else 0.84)
        hit = names[close[0]] if close and abs(len(close[0]) - len(core)) <= 2 else None  # a typo, not another word
    return Intent(hit.name, hit.tool, hit.group, dict(hit.args)) if hit else None


def semantic_ensure() -> bool:
    from jarvis.core import semantic
    return semantic.ensure_ready()


def _bare_yes_no(t: str) -> bool:
    """'yes', 'yeah do it', 'ok go ahead', 'no thanks': an answer with no action of its own."""
    return bool(yes_no(t)) and len(re.findall(r"[\w']+", t)) <= 4


_TG_TO = re.compile(r"\b(?:send|text|message|forward)\s+(?:me\s+)?(?:a\s+message\s+)?(?:saying\s+)?"
                    r"(?P<m>.+?)\s+(?:to|on|in|via|through)\s+(?:my\s+)?(?:telegram|phone|mobile)$", I)
_TG_SAYING = re.compile(r"\b(?:telegram|phone|mobile)\s*[,:]?\s+(?:me\s+)?(?:saying|that\s+says|says|that)?\s*:?\s*(?P<m>.+)$", I)


def tg_message_text(raw: str) -> str | None:
    """The message in 'send hello to telegram' / 'message me on telegram saying X' (None when it is a FILE or 'it':
    'send the essay to telegram' sends the essay, never the word 'the essay')."""
    from jarvis.core import focus, workmem
    t = " ".join((raw or "").split()).strip(" .!?")
    m = _TG_TO.search(t) or _TG_SAYING.search(t)
    if not m:
        return None
    msg = m.group("m").strip(" \"'")
    if re.match(r"(?:this|that|these|those|the|my|your|its|it)\b", msg, I):
        return None  # 'my location', 'this link', 'the result': a THING to send, not the words themselves
    if not msg or len(msg) > 500 or focus.is_anaphora(msg) or workmem.kind_named(msg) \
            or re.search(r"(?:^|\s)(?:/|~/)|\b[\w-]+\.[a-z0-9]{2,5}\b|https?://", msg, I):
        return None  # a file, a path, a link or 'it': the send-file / send-last tools
    return msg


_IN_PLACE = re.compile(r"\b(?:in|inside|into|under|at)\s+(?:the\s+|my\s+)?(?P<loc>[\w.-]+(?:\s+[\w.-]+){0,3}?)"
                       r"(?:\s+(?:folder|directory|dir))?(?=\s*(?:$|[,.!]|\b(?:and|then|named|name|called|with)\b))", I)


def player_intent(text: str) -> Intent | None:
    """While KURAMA's music player is on, a SHORT request that MEANS a player control ('pause', 'continue', 'continue
    play', 'next one', 'louder', 'volume max', 'stop it') controls it: 0 tokens, whatever the words. The player being
    on is the context that makes 'continue' mean the music (11-01: 'continue' rewrote the highlighted text, 'pause'
    and 'continue play' went to the AI). Off: nothing here runs."""
    from jarvis.core import music, semantic
    t = " ".join((text or "").split()).strip(" .!?")
    if not t or len(t.split()) > config.PLAYER_CONTROL_MAX_WORDS or not music.running() or not semantic.ready():
        return None
    best = semantic.best_of(t, "player", {**config.PLAYER_CONTROL_EXAMPLES, "other": config.PLAYER_NOT_EXAMPLES})
    if not best or best[0] == "other" or best[1] < config.PLAYER_CONTROL_MIN:
        return None
    act = best[0]
    if act in ("pause", "resume", "next", "previous"):
        return Intent("media", "media_control", "media", {"action": "play" if act == "resume" else act}, "media")
    if act == "stop":
        return Intent("music", "music", "media", {"action": "stop", "query": ""})
    if act in ("volume_up", "volume_down"):
        return Intent("music", "music", "media", {"action": act, "query": ""})
    return Intent("music", "music", "media", {"action": "volume_set", "query": "100" if act == "volume_max" else "30"})


def registry_group(tool: str) -> str:
    from jarvis.core import registry
    t = registry.REGISTRY.get(tool)
    return registry.group_of(t) if t is not None else ""


def match(text: str) -> Intent | None:
    """The single high-confidence intent for text whose meaning agrees (meaning_ok), or None."""
    from jarvis.core import workmem
    if (picked := workmem.choose(text)) is not None:  # "2" / "the second one" after "I found 3 copies: 1. ... 2. ..."
        tool, args = picked
        return Intent("choice", tool, registry_group(tool), args)
    if (played := player_intent(text)) is not None:  # 'pause' / 'continue' while KURAMA's music is on
        return played
    it = agent_intent(text) or agent_coding_intent(text) or link_play_intent(text) or clean_intent(text) \
        or shutdown_later_intent(text) or to_file_intent(text) or selection_intent(text) \
        or _code_not_file(_match(text)) or daily_intent(text)
    if it is not None and it.tool == "read_later" and semantic_ensure():  # "add a job for later: write a poem" is
        from jarvis.core import semantic  # KURAMA's job list, not the reading list: by meaning, job wins -> the AI
        best = semantic.best_of(text, "job_vs_readlater", {"job": config.QUEUE_EXAMPLES["later"],
                                                           "readlater": config.READLATER_EXAMPLES})
        if best and best[0] == "job":
            return None
    if it is not None and meaning_ok(text, it):
        return it
    semantic_ensure()  # a freed model loads in ~0.6 s: cheaper than an AI request that guesses (it wrote kt1.txt)
    if _bare_yes_no(text):
        return None  # a bare yes/no names no action: it answers a question (the AI reads it with that question)
    return meaning_intent(text)  # no pattern, or its meaning disagreed ('Open VS Code from this folder' is not a
    #                              folder named 'VS Code from this'): an action picked by meaning, else the AI


_AGENT_ON = re.compile(r"(?:please\s+|kurama\W+)?(?:start|open|turn\s+on|switch\s+(?:on|to)|enable|activate|use|"
                       r"go\s+to)\s+(?:the\s+)?(?:coding|code|programming)(?:\s+(?:agent|mode))?(?:\s+(?:on|now|please))*|"
                       r"(?:coding|code)\s+(?:agent|mode)\s+on|/agent\s+(?:coding|code)", I)
_AGENT_OFF = re.compile(r"(?:please\s+|kurama\W+)?(?:(?:stop|close|turn\s+off|exit|disable|leave|quit)\s+(?:the\s+)?"
                        r"(?:coding|code|programming)(?:\s+(?:agent|mode))?|(?:switch|go)\s+(?:back\s+)?to\s+general"
                        r"(?:\s+mode)?|general\s+mode|back\s+to\s+general|(?:coding|code)\s+(?:agent|mode)\s+off|"
                        r"/agent\s+(?:general|off))", I)


def agent_intent(text: str) -> Intent | None:
    """Turning an agent on / off: a fixed command said as the whole request (0 tokens)."""
    t = " ".join((text or "").split()).strip(" .!?")
    if _AGENT_ON.fullmatch(t):
        return Intent("agent", "_agent", "self", {"name": "coding"})
    if _AGENT_OFF.fullmatch(t):
        return Intent("agent", "_agent", "self", {"name": "general"})
    if re.fullmatch(r"/agents?|which agent(?: is on)?|what agent(?: is (?:on|active))?", t, I):
        return Intent("agent", "_agent", "self", {"name": ""})
    return None


def agent_coding_intent(text: str) -> Intent | None:
    """While the coding agent is on, its requests by MEANING (agents.coding.EXAMPLES, 0 tokens); its waiting change
    takes yes / no. Off: nothing here runs. (It was named coding_intent too, which silently replaced the older
    coding_intent above: 'generate requirements.txt', 'notebook to script', 'check dependencies' stopped working.)
    It only takes a request that is clearly its own: an assist question waiting ('replace it?') keeps its answer;
    a request whose meaning is closer to the selection/editing actions goes to them; undo needs a near-exact match
    (it once undid fixes for 'update code', 'add comments', 'clean and complete this code')."""
    from jarvis import agents
    t = " ".join((text or "").split())
    if not t or t.startswith("/") or agents.current() != "coding":
        return None
    from jarvis.agents.coding import EXAMPLES, changes, terminal

    def act(a: str, **kw) -> Intent:
        return Intent("coding", "coding", "coding_agent", {"action": a, **kw})
    yn = yes_no(t)
    if (changes.waiting() or changes.cost_waiting()) and yn:
        return act("yes" if yn == "yes" else "no")
    if _assist_waiting(t):  # 'replace it' / 'yes' answer the assist's own question
        return None
    crash = terminal.last(600)
    if crash and yn == "yes":  # "Crashed: ... Want me to fix it?" -> yes
        return act("fix")
    if len(t) > 300:
        return None
    from jarvis.core import semantic  # the agent keeps the model loaded; cold (just started) it loads now (~2 s)
    best = semantic.best_of(t, "coding", EXAMPLES)
    ranked = semantic.scores(t)
    if best is None or not ranked:
        return None
    label, score = best
    other = next((s for g, s in ranked if g not in (semantic.CHAT, "clipboard", "dev", "codequality",
                                                    *config.AGENT_GROUPS)), 0.0)
    need = {"undo": config.AGENT_UNDO_MIN, "project": config.AGENT_PROJECT_MIN}.get(label, config.AGENT_MIN)
    if score < need or score < other - config.SELECTION_MARGIN:
        return None
    if label != "project" and (sel := semantic.best_of(t, "selection", config.SELECTION_EXAMPLES)) \
            and sel[1] >= score - config.AGENT_OVER_SELECTION:
        return None  # 'add comments to this code', 'clean and complete it': editing, not the agent's actions
    if label in ("fix", "run") and not crash:
        return None  # nothing crashed: 'fix this' is about the selection / the AI
    site = (re.search(r"\b(chatgpt|gemini|claude)\b", t, I) or [None, ""])[1].lower()
    return act(label, request=t, **({"site": site} if label == "bridge" and site else {}))


def _assist_waiting(t: str) -> bool:
    """One of the assist questions waits for this reply (a code change / run block / question / 'which file'); an
    offer ('want the long version?', 'try again?') only takes a yes or no, anything else is a new request."""
    from jarvis.core import assist
    text_offer = assist.pending_code_active() and assist._pending.get("text")  # 'replace it?' after a text rewrite
    return bool((assist.pending_code_active() and (not text_offer or yes_no(t) or _APPLY_CODE.search(t)))
                or assist.use_waiting() or assist.ask_back_waiting()
                or assist.file_ref_waiting() or ((assist.more_waiting() or assist.retry_active()) and yes_no(t)))


# words that add nothing to a request ("bro", "please", the assistant's name): they don't count as naming something
_NO_DETAIL = {"bro", "pls", "plz", "please", "hey", "ok", "okay", "now", "can", "could", "you", "will", "just",
           "for", "me", "my", "the", "a", "an", "of", "in", "to", "it", "this", "that", "here", "current", "selected",
           "and", "yaar", "dai", "na", "quickly", "again", "also", "all", "i", "want", "need", "your", "with", "on",
           "from", "is", "are", "what", "which", "some", "mean", "no", "not", "said", "say", "its", "it's"}
_vocab: dict[str, set[str]] = {}


def _words(t: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", t.lower()))


def _known(word: str, vocab: set[str]) -> bool:
    """The word belongs to the action (or is filler), allowing a typo ('names' ~ name, 'sabe' ~ save, 'webiste')."""
    w = word.lower().strip("'.")
    if any(c.isdigit() for c in w):  # 'job 2', 'abc123': a detail, never filler
        return w in vocab
    if len(w) < 2 or w in vocab or w in _NO_DETAIL or w.endswith("'s") and w[:-2] in vocab:
        return True
    if w + "s" in vocab or w.endswith("s") and w[:-1] in vocab:  # 'tab' / 'tabs'
        return True
    from difflib import SequenceMatcher
    return len(w) >= 4 and any(len(v) >= 4 and SequenceMatcher(None, w, v).ratio() >= 0.75 for v in vocab)


_SHARED: dict[str, set[str]] = {}


def _shared(label: str) -> set[str]:
    """Content words every example of a name-slot action has ('tab' for switch_tab / close_tab): the request must
    say them too, else the name slot swallows a different request."""
    if label not in _SHARED:
        sets = [_words(e) - {"x"} for e in config.MEANING_SHORTCUTS[label]]
        _SHARED[label] = {w for w in set.intersection(*sets) if len(w) > 2 and w not in _NO_DETAIL} if sets else set()
    return _SHARED[label]


def meaning_label(t: str) -> tuple[str, float] | None:
    """The closest config.MEANING_SHORTCUTS action and how close. Words no action knows (a name: 'whatsapp',
    'night melody song') become X, like in the examples, so a name never pulls the meaning away
    ('save this website names whatsapp' -> 'save this website names X')."""
    from jarvis.core import semantic
    if "" not in _vocab:
        _vocab[""] = set().union(*(_words(e) for exs in config.MEANING_SHORTCUTS.values() for e in exs)) - {"x"}
    masked = re.sub(r"\bX(?:\s+X\b)+", "X", " ".join(w if _known(w, _vocab[""]) else "X"
                                                     for w in re.findall(r"[\w'.+#-]+", t)))
    return semantic.best_of(masked, "meaning_shortcuts", config.MEANING_SHORTCUTS)


def meaning_intent(text: str) -> Intent | None:
    """0-token actions picked by MEANING (config.MEANING_SHORTCUTS), not by word patterns: the request must be close to
    one action's examples (MEANING_SHORTCUT_MIN, and nearer than plain chat) AND name nothing those examples don't —
    'start job 2' or 'open vs code from the kurama folder' carry a detail only the AI can use, so they go to the AI.
    'this' is resolved like every tool: a pasted path > the Files app's selection / open folder > the last folder."""
    from jarvis.core import router, semantic
    raw = " ".join((text or "").split()).strip(" .!?")
    t = router.fix_typos(raw)
    if not t or len(t) > 120 or not semantic.ready():
        return None
    # words no action knows (a name: 'whatsapp', 'watest') become X, like in the examples, so the name never pulls
    # the meaning away ('save this website names whatsapp' -> 'save this website names X')
    best = meaning_label(t)
    if best is None or best[1] < config.MEANING_SHORTCUT_MIN_BY.get(best[0], config.MEANING_SHORTCUT_MIN):
        return None
    label, score = best
    chat = next((s for g, s in semantic.scores(t) if g == semantic.CHAT), 0.0)
    if score < chat + config.SEMANTIC_OVER_CHAT:
        return None
    if label not in _vocab:
        _vocab[label] = set().union(*(_words(e) for e in config.MEANING_SHORTCUTS[label])) - {"x"}
    said = re.sub(r"^\W*(?:(?:hey|hi|ok)\s+)?(?:" + "|".join(config.ASSISTANT_NAMES) + r")\b\W*", "", raw, flags=I)
    toks = re.findall(r"[\w'.+#-]+", said)
    pos = [i for i, w in enumerate(toks) if not _known(w, _vocab[label])]
    extra = [toks[i] for i in pos]
    if label == "new_folder":  # 0 tokens, in the folder in use (Files app / pasted path / last folder)
        from jarvis.core import focus
        from jarvis.core.paths import smart_path
        here, said = None, raw
        for m in _IN_PLACE.finditer(raw):  # "in download folder", "inside my documents": a REAL folder named
            loc = m.group("loc").strip()
            if not focus.is_anaphora(loc) and (p := smart_path(loc, want="dir")) is not None:
                here, said = p, raw[:m.start()] + " " + raw[m.end():]
                break
        if here is None:
            here = focus.refer("this")
            if here is None:
                return None
            here = here if here.is_dir() else here.parent
        said = " ".join(said.split())
        nm = re.search(r"\b(?:named|name(?:\s+it)?|called|call\s+it|as)\s+(?P<n>[\w .()-]{1,60}?)\s*[.!]*$", said, I)
        rest = said[:nm.start()] if nm else said
        if any(not _known(w, _vocab[label]) for w in re.findall(r"[\w'.+#-]+", rest)):
            return None  # words that aren't a new-folder request (or a place that isn't a real folder): the AI
        it = Intent("mkdir", "make_folder", "files", {"path": str(here / (nm.group("n").strip() if nm else "New folder"))},
                    known=raw[m.start():m.end()].strip() if said != raw else "")
        return it if meaning_ok(t, it) else None
    if label == "tg_message":  # "send hello to telegram", "message me on telegram saying I'm late": the message
        msg = tg_message_text(raw)
        if msg is None:
            return None
        it = Intent("tgmsg", "send_message_telegram", "telegram", {"text": msg}, known=msg)
        return it if meaning_ok(t, it) else None
    if label in ("save_link", "switch_tab", "close_tab"):  # the words left over ARE the name ("save this website names
        if pos and (pos[-1] - pos[0] + 1 != len(pos) or pos[0] == 0):  # whatsapp" -> whatsapp)
            return None  # two unknown parts ('save this FILE as REPORT') or a leading one (the request starts with
            #              what to do: 'show me link stroe' is not a link named 'show'): not just a name -> the AI
        if any(not any(_known(w, {need}) or w.lower().rstrip("s") == need.rstrip("s") for w in toks)
               for need in _shared(label)):
            return None  # a word EVERY example of this action has is missing: 'Open sitting.' is not 'open the X
            #              tab' (it switched to a tab named 'sitting'; the owner meant Settings)
        if label in ("switch_tab", "close_tab"):
            if not extra:
                return None
            verb = "tab:" if label == "switch_tab" else "close_tab:"
            it = Intent("tab", "app_control", "windows", {"action": "shortcut", "text": verb + " ".join(extra)})
        else:
            it = Intent("links", "saved_links", "links", {"action": "save", **({"name": " ".join(extra)} if extra else {})})
        return it if meaning_ok(t, it) else None
    if extra:  # something the examples don't cover: a number, a name, a place -> the AI
        return None
    if label == "list_links":
        it = Intent("links", "saved_links", "links", {"action": "list"})
        return it if meaning_ok(t, it) else None
    if label == "read_later_add":
        it = Intent("readlater", "read_later", "links", {"action": "add", "url": ""})
        return it if meaning_ok(t, it) else None
    if label == "colab_setup":  # the ready-made notebook cell (Colab / Kaggle), copied: 0 tokens
        it = Intent("colab", "training", "watch", {"action": "colab"})
        return it if meaning_ok(t, it) else None
    if label == "close_all_tabs":  # every tab = the browser window (11-01 'Close all tab.' cost an AI call)
        it = Intent("close", "close_app", "windows", {"name": "browser"})
        return it if meaning_ok(t, it) else None
    if label == "list_tabs":
        it = Intent("tabs", "app_control", "windows", {"action": "shortcut", "text": "tabs"})
        return it if meaning_ok(t, it) else None
    if label in ("scroll_down", "scroll_up"):  # 'a lot' / 'more' = three pages (the words give the amount only)
        n = 3 if re.search(r"\b(?:lot|more|fast|much|far)\b", t, I) else 1
        it = Intent("ui", "app_control", "windows", {"action": "shortcut", "text": f"{label}:{n}", "app": ""})
        return it if meaning_ok(t, it) else None
    if label == "show_desktop":
        it = Intent("desktop", "window", "windows", {"action": "desktop"})
        return it if meaning_ok(t, it) else None
    if label.startswith("clean_"):
        it = Intent("clean", "cleanup", "system", {"action": label[6:]})
        return it if meaning_ok(t, it) else None
    if label == "jobs_start":
        return Intent("jobs", "jobs", "jobs", {"action": "start"})
    if label == "jobs_list":
        return Intent("jobs", "jobs", "jobs", {"action": "list"})
    from jarvis.core import focus
    p = focus.refer("this")
    if p is None:
        return None
    if p.is_file() and re.search(r"\b(?:folder|directory|dir)\b", t, I):
        p = p.parent  # "this folder" while the last thing used was a file: the folder it is in
    if label == "copy_path":
        return Intent("copypath", "write_clipboard", "clipboard", {"text": str(p)})
    return Intent("openpath", "open_path", "files", {"path": str(p), "app": "vscode"}, "VS Code")


def selection_intent(text: str) -> Intent | None:
    """Selection first (0 tokens): when code/text is highlighted, a request whose MEANING is one of the selection
    actions (config.SELECTION_EXAMPLES: explain, improve, complete, translate, summary, use, run, ask) is about the
    highlight, whatever the words ("what this code about", "make it better", "what is this in hindi"). Requests
    that mean something else ("open youtube", "what is the time") keep their own area. The words only give
    details (the language, 'replace it')."""
    t = " ".join((text or "").split())
    if not config.CONTEXT or not t or len(t) > 300 or t.startswith("/") or _assist_waiting(t):
        return None
    if _bare_yes_no(t):  # 'yes' answers MY question; it never means 'use the highlight' (it once rewrote .env)
        return None
    if re.search(r"https?://|(?<!\w)[~/][\w.-]+/|\b[\w-]+\.(?:py|js|ts|md|txt|json|ipynb|html|css|sh)\b", t, I):
        return None  # a link, a path or a file named in the request: it is about THAT, not the highlight
    from jarvis.core import context, rewrite, semantic
    try:
        sel = rewrite.peek()
        f = context.snapshot().get("file") if not sel.strip() else None  # nothing highlighted: the open file?
    except Exception:  # noqa: BLE001 - context is a bonus
        return None
    if not sel.strip() and f is None:
        return None
    if not semantic.ready():  # never wait seconds for the model: the patterns decide this once, it loads meanwhile
        semantic.warm_soon()
        return None
    ranked = semantic.scores(t)
    best = semantic.best_of(t, "selection", config.SELECTION_EXAMPLES)
    if not ranked or best is None:
        return None  # the meaning model isn't ready / not English: the patterns below decide
    action, score = best
    chat = next((s for g, s in ranked if g == semantic.CHAT), 0.0)
    other = next((s for g, s in ranked if g not in (semantic.CHAT, "clipboard")), 0.0)  # clipboard = this tool's area
    if score < config.SELECTION_MIN or score < max(other, chat) - config.SELECTION_MARGIN:
        return None
    from jarvis.core.assist import is_code, lang_of
    if not sel.strip():  # it means "this code / this" but nothing is highlighted: ask before using the whole file
        if action in ("translate", "run", "ask", "use"):  # a general request ('open the docs folder ..') is not
            return None  # about the file open in VS Code when nothing is highlighted (test round 1, 11-01)
        return Intent("assist", "text_assist", "clipboard", {"action": "file_ask", "request": t, "path": str(f),
                                                             "text": action, "lang": lang_of(t) or ""})
    code = is_code(sel)
    if action == "run":
        return Intent("codenav", "code_nav", "codequality", {"action": "run", "name": "", "request": t}) if code else None
    if action == "explain":
        args = {"action": "code"} if code else {"action": "meaning" if len(sel.split()) <= 3 else "explain"}
    elif action == "translate":
        args = {"action": "translate", "lang": lang_of(t) or "ne", "replace": bool(re.search(r"\breplace\b", t, I)),
                "text": ""}
    elif action in ("complete", "use") and not code:
        args = {"action": "ask", "request": t}  # text: no code to finish or call; do what was asked with it
    else:
        args = {"action": action, "request": t}
    if action in ("explain", "summary"):
        args["lang"] = lang_of(t) or ""
    return Intent("assist", "text_assist", "clipboard", args)


def _match(text: str) -> Intent | None:
    """The single high-confidence intent for text (by pattern), or None."""
    from jarvis.core import selfknow
    if selfknow.looks_like_password_try(text):  # raw text: the password answer is checked before anything else
        return Intent("unlock", "_unlock", "self", {"text": text})
    if ei := error_intent(text):
        return ei
    if len(study_mod.parse(text)) >= 2:  # a pasted timetable
        return Intent("study", "timetable", "study", {"action": "set", "text": text})
    t = normalize(text)
    if not t:  # "Hi" / "ok" are stripped as lead-in filler: answer them without the LLM
        return everyday_intent(" ".join((text or "").split()).strip(" ,"))
    if len(t) > 200:
        return None
    raw = " ".join((text or "").split())  # a command's words are kept as typed: normalize() drops a trailing
    if raw.startswith("/") and (sl := slash_intent(raw)):  # "KURAMA" ('/clear KURAMA' became '/clear')
        return sl
    if si := _self_intent(t):
        return si
    if wr := workspace_read_intent(t):
        return wr
    from jarvis.core import templates
    if ans := templates.match(t) or templates.small_talk(text):  # small talk + setup guides: a ready answer, 0 tokens
        return Intent("say", "_say", "self", ans)
    if pi := plan_answer_intent(t):
        return pi
    if cn := codenav_intent(t):
        return cn
    if po := port_intent(t):
        return po
    if cr := coderun_intent(t):
        return cr
    if mi := music_intent(t):
        return mi
    if mv := video_make_intent(t):
        return mv
    if au := audio_intent(t):
        return au
    if dg := diagram_intent(t):
        return dg
    if ch := chart_intent(t):  # before the money words: 'chart my expenses' is a chart
        return ch
    if tr := tracker_intent(t):
        return tr
    if li := links_intent(t):
        return li
    if tn := todo_now_intent(t):
        return tn
    if gi := goal_intent(t):
        return gi
    if rl := read_later_intent(t):
        return rl
    if ch := copy_history_intent(t):
        return ch
    if qi := qr_intent(t):
        return qi
    if oi := ocr_intent(t):
        return oi
    if ui := _ui_intent(t):
        return ui
    if cv := convert_intent(t):
        return cv
    if ws := wifi_share_intent(t):
        return ws
    if ct := contacts_intent(t):
        return ct
    if ev := everyday_intent(t):
        return ev
    if lv := live_intent(t):
        return lv
    if di := _daily_intent(t):
        return di
    if ci := _control_intent(t):  # shutdown/restart/sleep, timers, alarms, stopwatch, Wi-Fi...
        return ci
    if ti := time_weather_intent(t):  # "time and weather (in X)" -- also the misheard "time in the weather"
        return ti
    if _full(DATE_LOCAL, t):
        ad = bool(re.search(r"\b(?:a\.?d\.?|english|gregorian|international|angreji|अंग्रेजी|अङ्ग्रेजी|ईस्वी)\b", t, I))
        args = {"calendar": "ad" if ad else "bs"}
        if re.search(r"\b(?:week|hapta|हप्ता|हफ्ता)\b", t, I) and not re.search(r"day of the week", t, I):
            args["week"] = True  # the week number only when asked ("which week is this")
        return Intent("date", "get_date", "general", args)
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
    if sf := sendfile_intent(t):
        return sf
    if li := listdir_intent(t):
        return li
    if si := search_intent(t):
        return si
    if ff := findfile_intent(t):
        return ff
    if m := _full(FOLDER_OPEN, t):
        if fi := _folder_intent(m.group("target")):
            return fi
    if m := _full(OPEN, t):
        return _open_intent(m.group("target").strip(" ,"), m.group("verb").lower())
    if m := _full(CLOSE, t):
        return _close_intent(m.group("target").strip(" ,"))
    return fresh_intent(t)


def _close_intent(target: str) -> Intent | None:
    if not target or len(target.split()) > 4 or _BAD_TARGET.search(target):
        return None
    from jarvis.tools.general import _apps

    entry, score = _apps.find_app(target)
    if entry is None or score < _apps.FASTPATH_MIN_SCORE:
        return None
    return Intent("close", "close_app", "apps", {"name": target}, target)  # say it the way the user did


_FM = r"(?:the |my )?(?:file manager|files|file explorer|explorer|nautilus|files app)"
_FOLDLEAD = r"(?:me |us |the |my )*"  # "show me the X folder" -> X
FOLDER_OPEN = _rx(
    r"(?:open|show|go to|goto|browse|reveal|take me to)(?: up)? " + _FOLDLEAD + r"(?P<target>.+?) (?:folder|directory|dir)(?: in " + _FM + r")?",
    r"(?:open|show|go to|goto|browse|reveal)(?: up)? " + _FOLDLEAD + r"folder (?:called |named )?(?P<target>.+?)",
    r"(?:open|show|go to|goto|browse|reveal|take me to)(?: up)? " + _FOLDLEAD + r"(?P<target>.+?) in " + _FM,
    # "open file manager in downloads", "open files from the kurama folder" (the app named first, then where)
    r"(?:open|launch|start|show)(?: up)? " + _FM + r" (?:in|from|at|on|for|to|inside)(?: the| my)? (?P<target>.+?)(?: folder| directory| dir)?",
)


def _folder_intent(target: str) -> Intent | None:
    target = (target or "").strip(" ,'\"")
    target = re.sub(r"^(?:the |my )?(?:file manager|files app|file explorer|nautilus|files)\s+(?:in|from|at|on|for)\s+(?:the |my )?", "",
                    target, flags=I)  # "open file manager from kurama folder" -> kurama
    if not target or len(target.split()) > 6 or re.fullmatch(r"(?:it|this|that|here|there)", target, I):
        return None
    from jarvis.core.paths import smart_path  # a folder that really exists: the gate judges "open X folder", not the
    real = smart_path(target, want="dir") is not None  # name ("open kurama folder" is not about KURAMA itself)
    return Intent("openfolder", "open_folder", "filesearch", {"name": target}, target, known=target if real else "")


def _open_intent(target: str, verb: str) -> Intent | None:
    if not target or len(target.split()) > 4 or _BAD_TARGET.search(target):
        return None
    from jarvis.tools.general import _apps, open_url  # lazy: desktop index only when needed

    url = open_url.resolve(target)
    if url:
        return Intent("open", "open_url", "browser", {"target": target}, target, known=target)
    if verb == "go to":
        return None
    entry, score = _apps.find_app(target)
    need = 100 if verb in ("start", "run") else _apps.FASTPATH_MIN_SCORE
    if entry is None or score < need:
        place = re.sub(r"\s+(?:in|on)\s+(?:my\s+|the\s+)?(?:laptop|computer|pc|file\s+manager)$", "", target, flags=I).strip()
        from jarvis.core.paths import smart_path
        if verb == "open" and place and smart_path(place, want="dir") is not None:
            return Intent("openfolder", "open_folder", "filesearch", {"name": place}, place)
        return None
    return Intent("open", "open_app", "apps", {"name": target}, entry["name"], known=target)


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
    "no_player": {"en": "Nothing is playing right now. Say 'play <name> on YouTube' to start a video.",
                  "hi": "अभी कुछ नहीं चल रहा है।", "ne": "अहिले केही चलिरहेको छैन।"},
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
        if action in ("pause", "play"):
            return _say({"pause": "paused", "play": "playing"}[action], lang, "")
        return out[:1].upper() + out[1:].rstrip(".") + "."  # next / previous / stop: the tool's own words
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
    if intent.name == "say":
        return intent.args.get(lang) or intent.args["en"]
    if intent.name == "copypath" and ok:
        return {"hi": f"पाथ कॉपी कर दिया: {intent.args['text']}", "ne": f"पाथ कपी गरें: {intent.args['text']}"}.get(
            lang, f"Copied the path: {intent.args['text']}")
    if intent.name == "where" and ok:
        return {"hi": f"पूरा पाथ: {output}", "ne": f"पूरा पाथ: {output}"}.get(lang, f"The full path is {output}")
    if intent.name == "date" and ok:
        if lang in ("ne", "hi"):
            from datetime import date as _d

            from jarvis.core import nepdate
            d = _d.today()
            if intent.args.get("calendar") == "ad":
                return f"आज {nepdate.ad_phrase(d)} {'हो' if lang == 'ne' else 'है'}।"
            bs = nepdate.bs_phrase(d, nepali_script=True)
            if not intent.args.get("week"):
                return f"आज {bs}।"
            wk = str(nepdate.week_of_year(d)).translate(str.maketrans("0123456789", "०१२३४५६७८९"))
            return (f"आज {bs}, वर्षको {wk} औं हप्ता।" if lang == "ne"
                    else f"आज {bs}, साल का {wk}वाँ हफ्ता।")
        return output
    if intent.name == "weather" and intent.args.get("_time") and ok and not output.strip().lower().startswith("error"):
        from jarvis.tools.general.echo_time import get_time
        rest = render(Intent(intent.name, intent.tool, intent.group,
                             {k: v for k, v in intent.args.items() if k != "_time"}, intent.label), ok, output, lang)
        t_out = get_time(intent.args.get("place") or "")
        t_txt = render(Intent("time", "get_time", "general", {}, intent.label), True, t_out, lang)
        return f"{t_txt} {rest}"
    out = output.strip()
    err = (not ok) or out.lower().startswith("error")
    if intent.name in ("time", "weather") and err and "couldn't find a place" in out:
        return _say("no_place", lang, intent.label)
    if err:
        if intent.name == "media" and "no media player" in out:
            return _say("no_player", lang, "")
        if intent.name in ("open", "search"):
            return _say("open_fail", lang, intent.label.split("|")[0])
        if out.startswith("The user declined"):  # you said no: that's not a failure
            return {"en": "Okay, I didn't do it.", "hi": "ठीक है, नहीं किया।", "ne": "ठिक छ, गरिनँ।"}.get(lang, "Okay, I didn't do it.")
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
    if intent.tool == "_say":
        return True, "ok"
    if intent.tool == "_agent":
        from jarvis import agents
        name = intent.args.get("name")
        return True, agents.switch(name) if name else f"{agents.status()['title']} is on."
    if intent.tool == "_cmd":
        from jarvis.core import phonecmds
        return True, phonecmds.run(intent.args["cmd"], intent.args.get("arg", ""))
    if intent.tool == "_brief":
        from jarvis.core import brief
        return True, brief.build()
    if intent.tool == "_where":
        from jarvis.core import focus
        p = focus.get_path(config.FOCUS_TTL_H * 3600)
        return (True, p) if p else (False, "error: I don't know which folder you mean yet. Name it first.")
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
    started: list[int] = []  # background jobs the tool started
    if intent.tool.startswith("_"):
        ok, output = _internal(intent)
    else:
        shelf: list[str] = []  # files the tool put in the Workspace
        res = safety.execute(intent.tool, {k: v for k, v in intent.args.items() if not k.startswith("_")},
                              confirm=confirm, ctx={**(ctx or {}), "user_text": text, "published": shelf,
                                                    "jobs": started})
        ok, output = res.ok, res.output
        if shelf:
            from jarvis.core import workspace
            output = workspace.strip_note(output)  # "[The full result ... is shown in the workspace]" is for the AI
            intent.args.setdefault("_published", shelf[-1])
    if intent.name in ("time", "weather") and "couldn't find a place" in (output or ""):
        return None  # unknown place: let the LLM path try (it can fix spelling)
    if m := re.match(r"Still working after \d+ s, so this keeps running in the background as job #(\d+)", output or ""):
        answer = safety.BACKGROUND_SAID.format(id=m.group(1))  # that note is for the AI; the user gets a sentence
        return FastResult(answer, intent, ok, int((time.monotonic() - t0) * 1000), [], started)
    direct = False  # a short answer that belongs in the chat, never the workspace
    if ok and intent.name == "wsread":
        from jarvis.core import workspace
        b = workspace.brief(output.partition("\n")[2])
        if b is None:
            return None  # long item: the LLM path reads it (read_workspace) and summarizes
        output, direct = b, True
    answer = render(intent, ok, output, lang or "en")
    if ok and intent.name == "live" and intent.args.get("kind") != "news":
        from jarvis.core import workspace  # scores, prices: the answer itself in the chat, not "it's in the workspace"
        if b := workspace.brief(answer):
            answer, direct = b, True
    published = [intent.args.pop("_published")] if "_published" in intent.args else []
    if published and ok:
        from jarvis.core import workspace  # the tool already saved the full text: one short line in the chat
        if workspace.too_long(answer):
            answer = workspace.short_line(answer, lang or "en")
    if ok and not direct and not published and not intent.tool.startswith("_") and (ctx or {}).get("channel") != "telegram":
        from jarvis.core import workspace  # long answers: one line in the chat, the full text in the workspace
        answer, path = workspace.to_workspace(intent.label or text[:60] or intent.name, answer, lang or "en")
        if path is not None:
            published = [str(path)]
    if mode == "voice" and intent.name in _VOICE_FIRST_LINE:
        answer = answer.split("\n", 1)[0]
    ms = int((time.monotonic() - t0) * 1000)
    try:
        store.log_routing(text, [intent.group], "fastpath", ms)
    except Exception as e:
        log.warning("could not log routing: %s", e)
    return FastResult(answer, intent, ok, ms, published, started)


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
_WHEN_NOW = r"(?:\s+(?:now|right\s+now|for\s+now|for\s+today|please|immediately))*"
_SHUTDOWN = re.compile(r"^(?:shut\s*down|power\s*off)(?:" + _DEV + r")?" + _WHEN_NOW + r"$|^(?:turn|switch)\s+off" + _DEV + _WHEN_NOW + r"$", I)
_RESTART = re.compile(r"^(?:restart|reboot)(?:" + _DEV + r")?" + _WHEN_NOW + r"$", I)
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
                         r"notify|tell|ping|alert|inform|say|remind)\b.{0,40}?\b(?:telegram|telegra|phone|mobile)\b.*$", I)


_WALL_CHANGE = re.compile(r"^(?:(?:i\s+mean|actually|please|can\s+you|could\s+you|i\s+want\s+(?:you\s+)?to)\W+)*"
                          r"(?:change|switch|set\s+(?:a\s+)?(?:new|different)|give\s+me\s+a\s+new|new)\s+(?:the\s+|my\s+)?(?:image\s+in\s+my\s+)?"
                          r"(?:desktop\s+)?(?:wallpaper|background)(?:\s+(?:image|picture))?$", I)
_CHART = re.compile(r"^(?:(?:can|could)\s+you\s+)?(?:make|create|draw|show|give)\s+(?:me\s+)?(?:a\s+)?(?P<k>pie|bar|line)?\s*"
                    r"(?:chart|graph|plot)\s+(?:of|for|about|showing)\s+(?P<x>.+)$", I)
_TRAINING_Q = re.compile(r"\b(?:training|traning|trainning|traing)\b.*\b(?:happening|running|going|status|progress|done|finished)\b|"
                         r"^(?:is\s+there\s+)?any\s+(?:training|traning|trainning)\b", I)
_HABIT_DONE = re.compile(r"^i\s+(?:have\s+|just\s+)?(?:complete[d]?|did|done|finished|drank|drink|dring|had)\s+(?P<x>.+)$", I)
_HI_WAKE = re.compile(r"(?P<w>.+?)\s+(?:utha|uthaa|jaga|jagaa)\s*(?:dena|do|dijiye|dijie|dijiega)$|"
                      r"(?P<w2>.+?)\s+(?:uthaidinu|uthai\s+dinu|uthaunu|उठाइदिनु|उठा\s*देना|जगा\s*देना)$", I)
_HI_TIME = ((r"\bkal\b|\bभोलि\b|\bकल\b", "tomorrow"), (r"\baaj\b|\baja\b|\bआज\b", "today"),
            (r"\b(?:subah|bihana|सुबह|बिहान)\b", "am"), (r"\b(?:shaam|sham|beluka|साँझ|शाम|बेलुका)\b", "pm"),
            (r"\b(?:raat|rati|रात|राति)\b", "pm"), (r"\b(?:baje|bajey|bajay|बजे|बजे)\b", ""), (r"\b(?:mujhe|malai|मुझे|मलाई)\b", ""))


def _hinglish_when(text: str) -> str:
    """'kal subah 6 baje' -> 'tomorrow 6 am'."""
    t = " " + text.lower() + " "
    ampm = "am" if re.search(_HI_TIME[2][0], t, I) else "pm" if re.search(_HI_TIME[3][0] + "|" + _HI_TIME[4][0], t, I) else ""
    for rx, rep in _HI_TIME:
        t = re.sub(rx, "" if rep in ("am", "pm") else rep, t, flags=I)
    t = " ".join(t.split())
    return re.sub(r"(\d{1,2}(?::\d{2})?)", lambda m: f"{m.group(1)} {ampm}".strip(), t, count=1) if ampm else t


def _everyday_intent(t: str) -> Intent | None:
    if _WALL_CHANGE.match(t):
        return Intent("control", "set_wallpaper", "desktop", {"mode": "next"})
    if m := _CHART.match(t):
        return Intent("control", "make_chart", "image", {"request": m.group("x"), **({"kind": m.group("k").lower()} if m.group("k") else {})})
    if _TRAINING_Q.search(t) and len(t.split()) <= 12:
        return Intent("control", "training", "watch", {"action": "status"})
    if (m := _HABIT_DONE.match(t.strip(" .!"))) and len(t.split()) <= 10:
        try:
            from jarvis.core import habits
            if habits.find(m.group("x")):
                return Intent("control", "habits", "tracker", {"action": "done", "text": m.group("x")})
        except Exception:
            pass
    if m := _HI_WAKE.match(t.strip(" .!?")):
        when = _hinglish_when(m.group("w") or m.group("w2"))
        if re.search(r"\d", when):
            return Intent("control", "set_alarm", "clock", {"when": when})
    return None


def _control_intent(t: str) -> Intent | None:
    if ei := _everyday_intent(t):
        return ei
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
