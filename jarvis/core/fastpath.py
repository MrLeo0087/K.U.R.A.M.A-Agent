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
from pathlib import Path

from jarvis.core import config, safety, store
from jarvis.core import notes as notes_mod
from jarvis.core import study as study_mod
from jarvis.core.assist import LANG_ALT as _LANG_ALT  # any language: nepali, hindi, english, japanese, french...
from jarvis.core.assist import WHOLE_CODE
from jarvis.core.intents.base import (  # noqa: F401  (moved; names kept here for callers and tests)
    FastResult, I, Intent, URL_RE, _NO_LEADS, _NO_WORDS,
    _ORD, _PERIOD, _RL_LIST, _YES_LEADS, _YES_WORDS, _full,
    _nth, _period, _rx, yes_no,
)

log = logging.getLogger("jarvis.fastpath")


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

from jarvis.core.intents.files import (  # noqa: F401  (moved; names kept here for callers and tests)
    CLOSE, OPEN, SEARCH, SEARCH_NAMES, SEARCH_URLS, SENDFILE,
    _ANAPHORA_SEND, _BAD_TARGET, _DEST, _ENG, _FILEISH, _FINDFILE,
    _FIND_SEND, _HERE_LIST, _HI_DO, _HI_ON, _IS_THERE, _LISTDIR,
    _LOCP, _NOT_FINDFILE, _OPEN_REF, _RANKED, _SEARCH_ANSWER, _SEARCH_LOCAL,
    _SENDLEAD, _TGDEST, _focus_intent, findfile_intent, focus_is_anaphora, here_intent,
    listdir_intent, ranked_files_intent, search_intent, sendfile_intent,
)


from jarvis.core.intents.desktop import (  # noqa: F401  (moved; names kept here for callers and tests)
    ABOUT_ME, BATTERY, DIGEST, DND_PATS, FOCUS_START, FOCUS_STOP,
    LEVELS, NAME, NL_PATS, POWER_MODE, POWER_STATUS, SESSION,
    SWITCHES, TOKENS, WALL_NEXT, WALL_RANDOM, YOUTUBE, _BRI,
    _BRI_HI, _BY, _DEPS, _DEV, _DND, _DOWN_HI,
    _DO_HI, _MAXW, _MEDIA_OBJ, _MIN, _MINW, _MUTE_FOR,
    _MUTE_KIND, _MUTE_NOUN, _MUTE_VERB, _N, _NAME_BAD, _NB2PY,
    _NL, _NUMW, _OFFW, _ONW, _PCT, _PM_ANY,
    _PM_WORDS, _REQS, _SONG, _SONG_HI, _STOP_TRACK, _UP_HI,
    _VID, _VID_NE, _VOL, _VOL_HI, _WHERE_LAPTOP, _YT,
    _YT_DO, _levels_words, _mute_minutes, _onoff, _p9a_intent, _system_intent,
    mute_intent, power_mode_intent,
)


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


from jarvis.core.intents.media import (  # noqa: F401  (moved; names kept here for callers and tests)
    TG_TAIL, WALL_TAIL, _ARCH, _CANDO, _CHANGED, _CMD_ALERTS,
    _COLAB, _COLAB_SETUP, _DATA_WHERE, _DAYS, _DETAIL, _DOCTOR,
    _DRAW, _FREE_RAM, _GESTURE, _GEST_OFF, _GEST_ON, _HAVE_TOOL,
    _IMAGE, _INSTALL, _LECTURE_START, _LECTURE_STOP, _LECTURE_SUM, _LIMITS,
    _MATH, _NET, _NET_BACK, _NET_SPEED, _NEWS, _NEXT_CLASS,
    _NOTES_SHOW, _NOT_A_SONG, _NWORD, _OUT_WHERE, _PORT, _QUIZ,
    _QUIZ_MOVES, _RENAME, _RESET, _STATUS, _TRAIN_Q, _TRAIN_STATUS,
    _TRAIN_STOP, _TT, _WEBWATCH, _WHERE, _WHOAMI, audio_intent,
    chart_intent, diagram_intent, image_intent, music_intent, video_make_intent,
)


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
_C_LIST = re.compile(r"^(?:please\s+)?(?:show|list|open|give|send|tell)(?:\s+me)?\s+(?:all\s+)?(?:of\s+)?(?:my\s+|the\s+)?(?:contacts|"
                     r"contact\s+list|contacts\s+list|phone\s+book|phonebook)[\s.?!]*$", I)  # 'show me my contact list' (11-04)
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


_MONEY_AMT = r"(?:rs\.?\s*|npr\s*|रु\.?\s*)?\d[\d,]*(?:\.\d+)?\s*(?:k\b|thousand|hajar)?\s*(?:rs|rupees?|npr)?"


def _money_period(t: str, default: str = "month") -> str:
    """A date range said in words ('from Oct 1 to Oct 15', 'on the 20th', 'last 10 days') wins over 'this month'."""
    from jarvis.core import expenses as ex
    if r := ex.dates_in(re.sub(r"\b(?:today|yesterday)\b", "", t, flags=I)):
        return ex.range_period(*r)
    return _period(t, default)


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
    if re.fullmatch(r"(?:please\s+)?send\s+(?:me\s+)?(?:my\s+|the\s+|today'?s\s+)?(?:morning\s+|daily\s+)?brief(?:ing)?\s+"
                    r"(?:to|on|in)\s+(?:my\s+)?telegram", low, I):  # the REAL brief, not the words / a made-up one (11-04)
        from jarvis.core import brief
        return Intent("tgmsg", "send_message_telegram", "telegram", {"text": brief.build()})
    if m := re.fullmatch(r"(?:please\s+)?(?:turn|switch|set)\s+(?P<s>on|off)\s+(?:the\s+|my\s+)?(?:laptop\s+)?guard|(?:the\s+|my\s+)?"
                         r"(?:laptop\s+)?guard\s+(?P<s2>on|off)|(?P<a>arm|disarm)\s+(?:the\s+|my\s+)?(?:laptop\s+)?guard", low, I):
        st = m.group("s") or m.group("s2") or ("on" if m.group("a") == "arm" else "off")
        return Intent("control", "laptop_guard", "power", {"action": st})  # 'turn off laptop guard': "no tool" (11-04)
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
    if cmd.name in ("list", "offline"):
        return Intent("say", "_say", "self", {"en": slash.help_text("md", only_offline=cmd.name == "offline")})
    if cmd.phrase and (p := slash.phrase_for(cmd, arg)):
        return match(p)
    if tc := slash.tool_call(cmd, arg):
        return Intent("slash", tc[0], tc[1], tc[2], cmd.name)
    if (cmd.tool or cmd.hint.startswith("<")) and not arg:  # '/search' alone
        return Intent("say", "_say", "self", {"en": f"Usage: /{cmd.name} {cmd.hint} — {cmd.desc}.".replace("  ", " ")})
    if cmd.cat.startswith("tool:"):
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
    where = r"(?:\s+(?:in|inside|from)\s+(?:here|this\s+(?:project|file|folder|repo|code(?:\s*base)?)|my\s+(?:code|project|repo)|"\
            r"the\s+(?:project|code(?:\s*base)?|repo)))?"  # 'find a function rate_limit in here' went to the FILE search
    if m := re.fullmatch(lead + r"(?:" + verb + r"\s+(?:me\s+)?(?:the\s+|a\s+|an\s+)?(?:real\s+|actual\s+)?(?:code\s+of\s+|definition\s+of\s+)?"
                         r"(?:the\s+|a\s+|an\s+)?(?:function|method|class|def)\s+(?:called\s+|named\s+)?|where\s+is\s+(?:the\s+)?"
                         r"(?:function|method|class)\s+)(?P<n>[A-Za-z_][\w.]*)(?:\(\))?(?:\s+(?:defined|function|method|class))?"
                         + where + r"[\s.!?]*", t, I) \
            or (m := re.fullmatch(lead + verb + r"\s+(?:the\s+)?(?P<n>[A-Za-z_][\w.]*(?:_[\w.]*|[a-z][A-Z][\w.]*))(?:\(\))?\s+"
                                  r"(?:function|method|class)" + where + r"[\s.!?]*", t)):  # 'find rate_limit function'
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
        if re.match(r"(?:the\s+)?(?:(?:laptop|computer)(?:'s)?\s+)?(?:screen|laptop|computer|pc|system)\b", p, I) \
                and m.group("a").lower() == "lock":
            return Intent("lock", "lock_screen", "power", {})  # 'lock laptop fast' locked a FOLDER 'laptop fast'
        if not re.fullmatch(r"(?:the\s+)?(?:(?:laptop|computer)(?:'s)?\s+)?(?:screen|laptop|computer|pc|kurama|phone|door|it\s+now)", p, I):
            from jarvis.core.focus import is_anaphora
            from jarvis.core.paths import smart_path
            if is_anaphora(p) or smart_path(p) is not None:  # a folder / file that exists (or 'this'), else the AI
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
    if re.fullmatch(r"(?:please\s+)?(?:install\s+(?:the\s+)?kaggle(?:\s+(?:cli|tool|api))?|(?:set\s*up|configure)\s+(?:the\s+)?"
                    r"kaggle\s+(?:cli|tool|api|command\s+line)(?:\s+on\s+(?:my\s+)?laptop)?)[\s.!]*", t, I):
        # the laptop's Kaggle CLI ("train this on Kaggle's GPU" from here); plain "set up kaggle" = the notebook
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
    if assist.pending_code_active() or assist.improving():  # an improved code is waiting (or still being written)
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
    if p := ui.parse_type(t):  # known = the words to type: the meaning gate judges 'type X', not what X says
        return Intent("ui", "app_control", "windows", {"action": "type", "text": p["text"], "app": p["app"]},
                      known=p["text"])  # (11-04: typing a sentence about Telegram was sent TO Telegram)
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


from jarvis.core.intents.todo import (  # noqa: F401  (moved; names kept here for callers and tests)
    _G_DEFAULT_Q, _G_NOUN, _G_PROGRESS, _G_STOP, _LIST_ANY, _LONG_WORDS,
    _L_SAVE, _L_STORE, _L_WORD, _MONEYISH, _MONS, _RL_CUE,
    _TAG, _TD_CMD, _TODO, _WHEN_BIT, _extras, _goal,
    _goal_intent, _goal_name, _last_span, _take_tag, _take_when, _todo_extra,
    goal_intent, links_intent, read_later_intent, todo_intent, todo_now_intent,
)


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


_NO_GATE = {"unlock", "error", "study", "say", "slash", "assist", "agent", "coding", "appname", "mywords", "stylerule",
            "newproject"}  # exact answers / commands, not guesses


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
    from jarvis.core.planner import split_clauses
    parts = split_clauses(t)
    if len(parts) <= 2 and any(re.search(r"^\W*(?:please\s+|can\s+you\s+|now\s+)?(?:complete|finish)\b", c, I)
                               and re.search(r"\b[\w-]+\.(?:py|js|ts)\b|\b(?:code|function|file|class|method)\b", c, I)
                               for c in parts) and len(t) < 300:  # 'complete this function' - never 'send a message
        # that the task is complete ... search for command.md file' inside a 7-part request (11-03: it took all 7)
        from jarvis.core import context
        if not context.snapshot()["selection"] and context.editor_open():  # selected code: assist completes that
            return Intent("tofile", "code_to_file", "clipboard", {"request": t})
    bare = _VSCODE_NAME.sub(" ", t)  # the 'code' in 'VS Code' is the app's name, not a request for code
    # the ask and 'into the file' must be in ONE part: 'create a folder
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
    if re.fullmatch(r"(?:as\s+well|too|also|again|both|it\s+too|number|the\s+number|this\s+number|that\s+number|the\s+list|"
                    r"(?:my\s+|the\s+|today'?s\s+)?(?:morning\s+|daily\s+|evening\s+)?(?:brief|briefing|summary|digest|report|"
                    r"status|weather|news|schedule|plan))", msg, I):
        return None  # 'send this number in telegram as well' sent "as well"; 'send morning brief' sent the words (11-04)
    if not msg or len(msg) > 500 or focus.is_anaphora(msg) or workmem.kind_named(msg) \
            or re.search(r"(?:^|\s)(?:/|~/)|\b[\w-]+\.[a-z0-9]{2,5}\b|https?://", msg, I):
        return None  # a file, a path, a link or 'it': the send-file / send-last tools
    return msg


_IN_PLACE = re.compile(r"\b(?:in|inside|into|under|at|on)\s+(?:the\s+|my\s+)?(?P<loc>[\w.-]+(?:\s+[\w.-]+){0,3}?)"
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
    from jarvis.core import querykind
    if (qk := querykind.route(text)) is not None:  # help / explain / 'run it again with ...': decided FIRST, by the
        return qk  # request's kind, so 'how can I send a file to my phone' is never done, only answered
    if (win := _window_first(text)) is not None:  # 'restore vs code' was read as a question about the open file
        return win
    it = app_name_intent(text) or style_intent(text) or new_project_intent(text) or ranked_files_intent(text) \
        or agent_intent(text) or agent_coding_intent(text) or link_play_intent(text) or clean_intent(text) \
        or shutdown_later_intent(text) or to_file_intent(text) or selection_intent(text) \
        or _code_not_file(_match(text)) or daily_intent(text)
    if it is not None and it.tool == "read_later" and semantic_ensure():  # "add a job for later: write a poem" is
        from jarvis.core import semantic  # KURAMA's job list, not the reading list: by meaning, job wins -> the AI
        best = semantic.best_of(text, "job_vs_readlater", {"job": config.QUEUE_EXAMPLES["later"],
                                                           "readlater": config.READLATER_EXAMPLES})
        if best and best[0] == "job":
            return None
    it = _to_last_list(text, it)
    if it is not None and meaning_ok(text, it):
        return it
    semantic_ensure()  # a freed model loads in ~0.6 s: cheaper than an AI request that guesses (it wrote kt1.txt)
    if _bare_yes_no(text):
        return None  # a bare yes/no names no action: it answers a question (the AI reads it with that question)
    if (mi := meaning_intent(text)) is not None:  # no pattern, or its meaning disagreed ('Open VS Code from this
        return mi  # folder' is not a folder named 'VS Code from this'): an action picked by meaning
    from jarvis.core import recipes  # what the owner's 👍 / clean repeats taught (data/recipes.json), else the AI
    return recipes.match(text)


_LIST_WORD = re.compile(r"\b(?:to-?do|todo|task|list|links?|link\s+store|read(?:ing)?\s+(?:later|list)|bookmarks?|notes?)\b", I)


def _to_last_list(text: str, it: Intent | None) -> Intent | None:
    """'remove second' / 'open 2' that names no list: the item of the numbered list KURAMA showed last (links, read
    later, to-do), not always the to-do list (d31dfcbc: right after the link list it deleted to-do item 2)."""
    if it is None or it.tool not in ("todo", "read_later", "saved_links") or _LIST_WORD.search(text):
        return it
    from jarvis.core import workmem
    last = workmem.last_list()
    n = it.args.get("item") or it.args.get("n") or it.args.get("name")
    act = str(it.args.get("action", ""))
    if not last or last == it.tool or not str(n).strip().isdigit() or act not in ("delete", "remove", "open", "done"):
        return it
    n = int(n)
    if last == "saved_links":
        return Intent("links", "saved_links", "links", {"action": "delete" if act in ("delete", "remove") else "open",
                                                        "name": str(n)}) if act != "done" else it
    if last == "read_later":
        return Intent("readlater", "read_later", "links", {"action": "remove" if act == "delete" else act, "n": n})
    if last == "todo":
        return Intent("todo", "todo", "todo", {"action": "delete" if act == "remove" else act, "item": str(n)})
    return it


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


_CODE_CHANGE = re.compile(r"^\W*(?:please\s+|can you\s+|could you\s+|now\s+|also\s+|and\s+)*(?:make|change|add|remove|"
                          r"delete|fix|move|put|use|set|improve|update|create|build|write|rename|replace|turn|increase|"
                          r"decrease|align|center|centre|show|hide|style|refactor|implement)\b", re.I)


def _coder_asked() -> bool:
    """The coding agent stopped on a question to the owner (its loop's waiting file, < 30 min old)."""
    try:
        from coder.agent import loop
        return loop.waiting() is not None
    except Exception:  # noqa: BLE001
        return False


def agent_coding_intent(text: str) -> Intent | None:
    """While the coding agent is on, its requests by MEANING (agents.coding.EXAMPLES, 0 tokens); its waiting change
    takes yes / no. Off: nothing here runs. (It was named coding_intent too, which silently replaced the older
    coding_intent above: 'generate requirements.txt', 'notebook to script', 'check dependencies' stopped working.)
    It only takes a request that is clearly its own: an assist question waiting ('replace it?') keeps its answer;
    a request whose meaning is closer to the selection/editing actions goes to them; undo needs a near-exact match
    (it once undid fixes for 'update code', 'add comments', 'clean and complete this code')."""
    from jarvis import agents
    t = " ".join((text or "").split())
    if not t or t.startswith("/"):
        return None
    if (yn0 := yes_no(t)) and _coder_asked():  # its question ('Should I remove TODO.md?') takes the yes / no in any
        return Intent("coding", "coding", "coding_agent", {"action": yn0})  # mode (11-07: "nothing waiting for a yes")
    if agents.current() != "coding":
        return None
    from jarvis.agents.coding import EXAMPLES, changes, terminal

    def act(a: str, **kw) -> Intent:
        return Intent("coding", "coding", "coding_agent", {"action": a, **kw})
    yn = yes_no(t)
    import coder  # the coding agent's own project: a plan / a commit waiting for its yes
    if (changes.waiting() or changes.cost_waiting() or coder.pending() is not None or coder.commit_waiting()) and yn:
        return act("yes" if yn == "yes" else "no")
    from coder.interfaces import api as _capi
    if _capi._question_key().exists() and len(t.split()) <= 6:  # the answer to its question ('2', 'web', 'here')
        return act("project", request=t)
    if coder.pending() is not None and re.fullmatch(  # 'fine, start build' / 'go ahead and build it' (0 tokens)
            r"(?:\w+\W+){0,3}(?:start|go|build|make|do|begin|proceed)(?:\W+(?:it|the|build|building|now|ahead|please|bro))*\W*", t, I):
        return act("yes")
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
                                                    *agents.groups())), 0.0)
    need = {"undo": config.AGENT_UNDO_MIN, "project": config.AGENT_PROJECT_MIN}.get(label, config.AGENT_MIN)
    if score < need or score < other - config.SELECTION_MARGIN:
        # coding mode + a clear instruction to change the project ('make the Reserve button text white'): the agent
        # takes it directly, 0 tokens (it went through the AI first: ~6k tokens just to pick the tool, 11-07).
        # Not a vague 'update code', and not about the selected code (that is the editing assistant's).
        about_selection = re.search(r"\b(?:this|selected|selection|highlighted)\s+(?:code|line|function|part)\b", t, I)
        if _CODE_CHANGE.match(t) and len(t.split()) >= 4 and not about_selection:
            sel = semantic.best_of(t, "selection", config.SELECTION_EXAMPLES)
            if not sel or sel[1] < 0.8:
                return act("project", request=t)
        return None
    if label != "project" and (sel := semantic.best_of(t, "selection", config.SELECTION_EXAMPLES)) \
            and sel[1] >= score - config.AGENT_OVER_SELECTION:
        return None  # 'add comments to this code', 'clean and complete it': editing, not the agent's actions
    if label in ("look", "preview", "check_page") and re.search(
            r"\b(?:make|improve|change|better|redesign|update|fix|add|modern|beautiful|nicer|colou?r)\b", t, I):
        label = "project"  # 'make the UI better': a CHANGE to the project, not a look at a web page (11-06)
    if label == "run" and not crash:  # 'run this project and tell me what it says': the agent runs it
        return act("run_task", request=f"Run the project and tell me in plain words what it does / prints: {t}")
    if label == "fix" and not crash:
        return None  # nothing crashed: 'fix this' is about the selection / the AI
    site = (re.search(r"\b(chatgpt|gemini|claude)\b", t, I) or [None, ""])[1].lower()
    return act(label, request=t, **({"site": site} if label == "bridge" and site else {}))


def _assist_waiting(t: str) -> bool:
    """One of the assist questions waits for this reply (a code change / run block / question / 'which file'); an
    offer ('want the long version?', 'try again?') only takes a yes or no, anything else is a new request."""
    from jarvis.core import assist
    text_offer = assist.pending_code_active() and assist._pending.get("text")  # 'replace it?' after a text rewrite
    return bool((assist.pending_code_active() and (not text_offer or yes_no(t) or _APPLY_CODE.search(t)))
                or (assist.improving() and (yes_no(t) == "yes" or _APPLY_CODE.search(t)))
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


_ONE_TOOL = {"time_now": ("time", "get_time", "general", {}), "date_today": ("date", "get_date", "general", {}),
             "battery": ("battery", "battery_status", "power", {}),
             "git_status": ("git", "git_info", "git", {"action": "status"}),
             "daily_summary": ("digest", "daily_digest", "usage", {"date": "today"})}
_APP_NAME = re.compile(r"\b(?:when(?:ever)?|if)\s+i\s+say\s+(?:open\s+)?(?P<w>[\w .'-]{2,40}?)\s*,?\s+(?:then\s+)?"
                       r"(?:you\s+(?:should|must|have\s+to)\s+|please\s+|just\s+)?(?:open|launch|start|use|run)\s+"
                       r"(?:the\s+)?(?P<a>[\w .'-]{2,40}?)(?:\s*,?\s+(?:not|instead\s+of|rather\s+than)\b.*)?[\s.!]*$", I)


def app_name_args(raw: str) -> dict | None:
    """The two names of 'when I say <word>, open <app> (not <other>)'; None when either is missing (0c4641e3: the AI
    promised to remember Brave and saved nothing; match() gates it by meaning like every pattern)."""
    m = _APP_NAME.search(" ".join((raw or "").split()))
    if not m:
        return None
    app = re.sub(r"\s+(?:app|application)$", "", m.group("a").strip(), flags=I)
    return {"name": m.group("w").strip(), "app": app}


_SAY_MEANS = re.compile(r"\b(?:when(?:ever)?|if)\s+i\s+say\s+[\"']?(?P<w>[\w .'-]{2,40}?)[\"']?\s*,?\s+(?:then\s+)?"
                        r"(?:you\s+(?:should|must|have\s+to|need\s+to)\s+|please\s+|just\s+|it\s+means\s+)?"
                        r"(?P<cmd>(?:open|launch|start|run|play|lock|turn|show|set|close|search|switch|put|mute)\b"
                        r"[^,]{1,120}?)(?:\s*,?\s+(?:not|instead\s+of|rather\s+than)\b.*)?[\s.!]*$", I)


_STYLE_LEAD = re.compile(r"^\W*(?:(?:ok(?:ay)?|hey|so|and|also|listen|remember)[\s,]+)*(?:\w+[\s,]+)?"
                         r"(?:from\s+now\s+on|starting\s+now|going\s+forward|always|never|don'?t\s+ever|every\s+time\s+you)\b", I)


_FORGET_RULE = re.compile(r"^\W*(?:(?:ok(?:ay)?|please|kurama)[\s,]+)*(?:forget|remove|delete|drop|cancel|clear)\s+"
                          r"(?:the\s+|my\s+|that\s+|your\s+)?(?:(?P<all>all\s+(?:the\s+|my\s+)?rules)|(?:style\s+)?rule"
                          r"(?:\s+(?:about|for|of|that\s+says|to))?\s*(?P<w>.*?))[\s.!]*$", I)


def style_intent(text: str) -> Intent | None:
    """'From now on keep your answers short' / 'always call me boss' / 'never use emojis': a standing rule for how
    KURAMA replies (style.py, in every AI reply), by meaning - 'always open youtube at 9' is a schedule, not one."""
    if m := _FORGET_RULE.match(text or ""):  # 'forget the rule about calling me boss' (it went to memory's fact
        what = "all" if m.group("all") else (m.group("w") or "").strip()  # forget, which asks yes/no: live 11-03)
        return Intent("stylerule", "app_name", "apps", {"action": "forget_rule", "command": what}) if what else None
    if not _STYLE_LEAD.search(text or "") or len(text) > 200 or not semantic_ensure():
        return None
    from jarvis.core import semantic
    best = semantic.best_of(text, "style_rule", {"style": config.STYLE_EXAMPLES, "other": config.NOT_STYLE_EXAMPLES})
    if not best or best[0] != "style" or best[1] < config.STYLE_MIN:
        return None
    return Intent("stylerule", "app_name", "apps", {"action": "rule", "command": text})


_NEW_PROJECT = re.compile(r"^\W*(?:(?:ok(?:ay)?|please|now|i\s+want\s+(?:you\s+)?to|can\s+you|could\s+you)[\s,]+)*"
                          r"(?:create|build|make|develop|code|write|generate|set\s*up|start)\s+(?:me\s+)?(?:a\s+|an\s+|the\s+)?"
                          r"(?:new\s+|simple\s+|small\s+|basic\s+|full\s+|complete\s+)*[\w+#.\s-]{0,40}?"
                          r"\b(?:app|application|project|program|website|web\s*app|game|bot|api|cli|tool)\b", I)


def new_project_intent(text: str) -> Intent | None:
    """'create simple calculator app in this folder' / 'build a flask todo app' / 'make a snake game in python': the
    project builder (plan + code files + .venv, opened in VS Code), with or without coding mode on. It went to the
    writer as an essay-like job (an .md, no files) when coding mode was off (11-04)."""
    t = " ".join((text or "").split())
    if len(t) > 220 or not _NEW_PROJECT.match(t) or re.search(r"\b(?:folder|directory)\s+(?:called|named)\b", t, I):
        return None
    if re.search(r"\b(?:diagram|chart|graph|image|picture|video|report|summary|readme|plan|presentation|ppt|slides?|doc|"
                 r"docs|documentation|essay|notes?|environment|venv|virtualenv|backup|list|review)\b", t, I):
        return None  # 'make a diagram of this project', 'set up the environment for a python project': not a new app
    if re.search(r"\b(?:open|close|launch|install|uninstall|update)\s+(?:the\s+)?app\b", t, I):
        return None  # an app on the laptop, not a new program
    return Intent("newproject", "coding", "coding_agent", {"action": "project", "request": t})


def app_name_intent(text: str) -> Intent | None:
    """'when I say <word>, open <app>' -> the app's name (works inside any sentence: _apps.teach); 'when I say
    <words>, <any command>' -> the owner's words for that whole command (mywords), both kept until changed."""
    if not re.search(r"\bi\s+say\b", text or "", I):
        return None
    if (args := app_name_args(text)) is not None:
        from jarvis.tools.general import _apps
        entry, score = _apps.find_app(args["app"])
        if entry is not None and score >= _apps.FASTPATH_MIN_SCORE and len(args["name"].split()) <= 3:
            return Intent("appname", "app_name", "apps", args, known=args["app"])
    if m := _SAY_MEANS.search(" ".join((text or "").split())):
        return Intent("mywords", "app_name", "apps", {"name": m.group("w").strip(), "command": m.group("cmd").strip()},
                      known=m.group("cmd"))
    return None


def meaning_label(t: str) -> tuple[str, float] | None:
    """The closest config.MEANING_SHORTCUTS action and how close. Words no action knows (a name: 'whatsapp',
    'night melody song') become X, like in the examples, so a name never pulls the meaning away
    ('save this website names whatsapp' -> 'save this website names X')."""
    from jarvis.core import semantic
    if "" not in _vocab:
        _vocab[""] = set().union(*(_words(e) for exs in config.MEANING_SHORTCUTS.values() for e in exs)) - {"x"}
    masked = re.sub(r"\bX(?:\s+X\b)+", "X", " ".join(w if _known(w, _vocab[""]) else "X"
                                                     for w in re.findall(r"[\w'.+#-]+", t)))
    best = semantic.best_of(masked, "meaning_shortcuts", config.MEANING_SHORTCUTS)
    if (apps := _mask_open_apps(t)) is not None:  # an open app's name is a slot too ('minimize vs code': "code" and
        win = {k: config.MEANING_SHORTCUTS[k] for k in _WINDOW_LABELS}  # "telegram" are words other actions know)
        wb = semantic.best_of(apps, "window_shortcuts", win)
        if wb and (best is None or wb[1] > best[1]):
            best = wb
    if (mine := _mask_my_commands(t)) is not None:  # one of the owner's saved commands named: it is the X
        fb = semantic.best_of(mine, "my_command_forget", {"my_command_forget": config.MEANING_SHORTCUTS["my_command_forget"]})
        if fb and (best is None or fb[1] > best[1]):
            best = fb
    return best


def _mask_my_commands(t: str) -> str | None:
    """The request with one of the owner's saved command phrases replaced by X, or None (none named)."""
    from jarvis.core import mywords
    low = " ".join(re.sub(r"[^\w\s']", " ", (t or "").lower()).split())
    for k in sorted(mywords.all_words(), key=len, reverse=True):
        if len(k) >= 3 and re.search(rf"\b{re.escape(k)}\b", low):
            return re.sub(rf"\b{re.escape(k)}\b", "X", low, count=1)
    return None


_WINDOW_LABELS = ("window_minimize", "window_maximize", "window_restore")


def _window_first(text: str) -> Intent | None:
    """A short request that clearly MEANS one window action (>= 0.95 to its examples, an open app named or none)
    wins before the word patterns: they read 'make vs code full screen' as a writing request about VS Code."""
    from jarvis.core import semantic
    if len(text.split()) > 16 or not semantic.ready():  # never loads the model just for this (later steps may)
        return None
    t = " ".join((text or "").split()).strip(" .!?")
    best = meaning_label(t)
    first = {**{w: 0.95 for w in _WINDOW_LABELS}, "my_command_forget": 0.95, "setting_change": 0.88,
             "help_me": 0.93,
             "setting_keep": 0.92}
    if not best or best[0] not in first or best[1] < first[best[0]]:
        return None  # (actions whose X is checked against what really exists: an open window, a saved command, a
        #              setting and its range; or a question about KURAMA itself: 'how do you measure my speed'
        #              must explain, not run a speed test)
    it = meaning_intent(text)
    return it if it is not None and it.tool in ("window", "app_name", "kurama_settings", "explain_self", "help_me",
                                                "find_capability") else None


def _about_last(text: str) -> bool:
    """A question that points at what KURAMA just did ('how did you measure THAT', 'how can I use IT'), asked while
    there is a request from the last 15 minutes to explain."""
    if not re.search(r"\b(?:you|your|it|that|this|those|these)\b", text or "", I):
        return False
    try:
        from jarvis.core import trace
        cur = (trace.current() or {}).get("id")
        return any(r["id"] != cur and time.time() - float(r["ts"]) < 900 for r in trace.recent(1, 3))
    except Exception:  # noqa: BLE001
        return False


def _mask_open_apps(t: str) -> str | None:
    """The request with the name of an app that has a window open replaced by X ('minimize vs code' -> 'minimize X'),
    or None (no open app named, or not a short request). The window list is read once (wmctrl, ~10 ms)."""
    toks = re.findall(r"[\w'.+#-]+", t)
    if not 2 <= len(toks) <= 7:
        return None
    try:
        from jarvis.tools.general import _apps
        wins = _apps.list_windows()
    except Exception:  # noqa: BLE001 - no wmctrl / X
        return None
    for n in (3, 2, 1):  # the longest name first ('visual studio code' before 'code')
        for i in range(1, len(toks) - n + 1):  # never the first word: that is what to do
            span = " ".join(toks[i:i + n])
            if span.lower() in ("the", "this", "window", "the window", "my", "all"):
                continue
            try:
                if _apps.match_windows(span, wins)[0]:
                    return " ".join([*toks[:i], "X", *toks[i + n:]])
            except Exception:  # noqa: BLE001
                return None
    return None


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
    if best is None:
        return None
    if best[1] < config.MEANING_SHORTCUT_MIN_BY.get(best[0], config.MEANING_SHORTCUT_MIN) and not (
            best[0] == "open_vscode" and best[1] >= config.MEANING_FOLDER_MIN and folder_in_words(raw) is not None) \
            and not (best[0] == "setting_change" and best[1] >= config.MEANING_SETTING_MIN):
        return None  # (a real folder / a real setting with a valid value may be a little less close in meaning:
        #              the slot is checked below, and nothing runs unless it is real)
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
        places = (m for st in re.finditer(r"\b(?:in|inside|into|under|at|on)\s", raw, I)  # every 'in / on ...' on its
                  if (m := _IN_PLACE.match(raw, st.start())))  # own: 'called on hold in downloads' (overlapping)
        for m in places:  # "in download folder", "inside my documents": a REAL folder named
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
    if label in ("settings_list", "setting_undo", "settings_reset", "setting_change", "explain_last", "help_me",
                 "setting_keep", "capability_ask"):
        return _about_me_intent(label, raw, t, extra)
    if label in ("claude_on", "claude_off", "claude_go", "claude_status", "claude_report", "claude_stop", "claude_usage"):
        return None if extra else _ok(t, Intent("claude", "claude_code", "dev", {"action": label.split("_")[1]}))
    if label == "my_commands":
        return None if extra else _ok(t, Intent("mywords", "app_name", "apps", {"action": "list"}))
    if label == "my_command_forget":  # only one of the owner's commands that exists ('forget my command X')
        from jarvis.core import mywords
        from jarvis.tools.general import _apps
        name = mywords.key(" ".join(extra))
        if not name or (name not in mywords.all_words() and _apps.clean_query(name) not in _apps.taught()):
            return None
        return _ok(t, Intent("mywords", "app_name", "apps", {"action": "forget", "name": name}, known=name))
    if label in ("window_minimize", "window_maximize", "window_restore"):  # one window, never all of them
        if pos and (pos[-1] - pos[0] + 1 != len(pos) or len(pos) > 4):
            return None  # two separate unknown parts or a long one: more than an app name -> the AI
        name = " ".join(extra)
        if name:  # only an app that has a window open (else the AI explains / opens it)
            from jarvis.tools.general import _apps
            try:
                if not _apps.match_windows(name)[0]:
                    return None
            except Exception:  # noqa: BLE001 - no wmctrl: the AI path
                return None
        it = Intent("window", "window", "windows", {"action": label.split("_")[1], "name": name}, known=name)
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
            try:  # only a tab that IS open ('show me my contact list' looked for a tab 'contact list', 11-04)
                from jarvis.core import browsertab
                tabs = [str(x.get("title") or "").lower() for x in browsertab.tabs()] or None  # None = can't tell
            except Exception:  # noqa: BLE001 - the extension isn't there: the old behaviour
                tabs = None
            want = " ".join(extra).lower()
            if tabs is not None and not any(want in tt or all(w in tt for w in want.split()) for tt in tabs):
                return None
            verb = "tab:" if label == "switch_tab" else "close_tab:"
            it = Intent("tab", "app_control", "windows", {"action": "shortcut", "text": verb + " ".join(extra)})
        else:
            it = Intent("links", "saved_links", "links", {"action": "save", **({"name": " ".join(extra)} if extra else {})})
        return it if meaning_ok(t, it) else None
    if label == "open_vscode":  # a folder NAMED in the request wins over 'this folder' (11-06: 'open that new_folder
        #   folder in vs code' opened Downloads: 'new_folder' is made of known words, so it wasn't seen as a name)
        if (picked := listed_pick(raw)) is not None:  # 'open the 4th folder in vs code' after a listing
            it = Intent("openpath", "open_path", "files", {"path": str(picked), "app": "vscode"}, "VS Code")
            return it
        folder = folder_in_words(raw)
        said = re.sub(r"[\W_]+", "", raw.lower())
        if folder is not None and (extra or re.sub(r"[\W_]+", "", folder.name.lower()) in said):
            it = Intent("openpath", "open_path", "files", {"path": str(folder), "app": "vscode"}, "VS Code",
                        known=" ".join(extra) or folder.name)
            return it if meaning_ok(t, it) or not extra else None
        if extra:
            return None
    if extra:  # something the examples don't cover: a number, a name, a place -> the AI
        return None
    if label == "list_links":
        it = Intent("links", "saved_links", "links", {"action": "list"})
        return it if meaning_ok(t, it) else None
    if label == "read_later_add":
        it = Intent("readlater", "read_later", "links", {"action": "add", "url": ""})
        return it if meaning_ok(t, it) else None
    if label in ("colab_setup", "kaggle_setup"):  # the ready notebook (.ipynb) linked to KURAMA: 0 tokens
        it = Intent("colab", "training", "watch", {"action": "kaggle" if label == "kaggle_setup" else "colab"})
        return it if meaning_ok(t, it) else None
    if label == "close_all_tabs":  # every tab = the browser window (11-01 'Close all tab.' cost an AI call); 'all
        it = Intent("tabs", "app_control", "windows", {"action": "shortcut", "text": "close_tabs:all"})  # but X'
        #  is refused by close_tabs (11-06 'close all the tabs and only keep YouTube' closed the whole Brave)
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
    if label in _ONE_TOOL:  # a one-tool question with nothing to fill in: the tool answers it
        name, tool, group, args = _ONE_TOOL[label]
        it = Intent(name, tool, group, dict(args))
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


_FOLDER_GLUE = re.compile(r"\b(?:please|can\s+you|could\s+you|open(?:\s+up)?|launch|show|start|with|using|this|that|it|"
                          r"the|a|an|my|there\s+is|there's|is|named?|called|folders?|director(?:y|ies)|dir|then|and|"
                          r"inside|under|from|in|into|at|on|of|to|go|editor|code\s+editor)\b", I)


def _about_me_intent(label: str, raw: str, t: str, extra: list[str]) -> Intent | None:
    """KURAMA about itself: settings (0 tokens, only a real setting with a valid value), explain (a short AI call
    grounded in the last request + tool notes), help (0 tokens)."""
    from jarvis.core import usersettings
    if label == "explain_last":
        return _ok(t, Intent("explain", "explain_self", "self", {"question": raw}))
    if label == "help_me":  # the need in the owner's own words ('sending a file to my phone'), not the leftover words
        topic = re.sub(r"^.*?\bhelp\s+(?:me\s+)?(?:with\s+|to\s+|for\s+)?", "", raw, count=1, flags=I).strip(" ?.!") \
            if re.search(r"\bhelp\b", raw, I) else " ".join(extra)
        if re.fullmatch(r"(?:me\s+)?(?:use|using)\s+(?:you|kurama)|", topic, I):
            topic = ""
        return _ok(t, Intent("help", "help_me", "self", {"topic": topic}))
    if label == "capability_ask":  # 'do you have the ability to convert a pdf?': answer it, never do it
        need = re.sub(r"^.*?\b(?:ability|able|possible|support|know how|way|feature|abality)\b\s*(?:for you\s+)?(?:to\s+)?",
                      "", raw, flags=I).strip(" ?.!") or raw
        need = re.sub(r"^(?:can|could|will)\s+you\s+", "", need, flags=I)
        if re.fullmatch(r"(?:(?:do|make|run|open|send)\s+)?(?:it|that|this|those|them)(?:\s+or\s+not)?", need.lower()):
            return _ok(t, Intent("explain", "explain_self", "self", {"question": raw}))  # 'can you do it or not?'
        return _ok(t, Intent("can", "find_capability", "self", {"need": need}))
    if label == "setting_keep":
        return None if extra else _ok(t, Intent("settings", "kurama_settings", "self", {"action": "keep"}))
    if label == "settings_list":
        return None if extra else _ok(t, Intent("settings", "kurama_settings", "self", {"action": "list"}))
    if label == "setting_undo":
        return None if extra else _ok(t, Intent("settings", "kurama_settings", "self", {"action": "undo"}))
    if label == "settings_reset":
        return None if extra else _ok(t, Intent("settings", "kurama_settings", "self", {"action": "reset", "name": "all"}))
    if re.search(r"\b(?:with|for|using|in)\s+\d", raw, I) and not re.search(r"\b(?:to|=)\s*[+-]?\d", raw, I):
        return None  # 'run the speed test WITH 30 seconds': that one run only (the tool's own intent), not a change
    m = re.search(r"\b(?:to|at|=)\s+(?P<v>[+-]?\d.*)$", raw, I) or re.search(r"(?P<v>[+-]?\d+(?:\.\d+)?\s*(?:%|[a-z]+)?)", raw, I)
    if not m:
        return None  # "make the speed test longer": how much? -> the AI asks / picks
    s = usersettings.find(raw[:m.start()] + " " + raw[m.end():])
    if s is None:
        return None
    try:
        usersettings.parse(s, m.group("v"))
    except ValueError:
        return None  # out of range / not a value: the AI explains the allowed range
    return _ok(t, Intent("settings", "kurama_settings", "self", {"action": "set", "name": s.name, "value": m.group("v")},
                         known=s.name))


def _ok(t: str, it: Intent) -> Intent | None:
    return it if meaning_ok(t, it) else None


_ORDINAL = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
            "ninth": 9, "tenth": 10, "1st": 1, "2nd": 2, "3rd": 3}


def listed_pick(text: str) -> Path | None:
    """'open the 4th folder' / 'open 4 in vs code' / 'open number 4': item N of the last numbered listing (folders are
    numbered too), when that listing is recent (10 min). None otherwise."""
    import json
    t = (text or "").lower()
    m = re.search(r"\b(?:number\s+|no\.?\s*|#)?(\d{1,2})(?:st|nd|rd|th)?\b(?!\s*(?:seconds?|minutes?|%|gb|mb))", t)
    n = int(m.group(1)) if m else next((v for k, v in _ORDINAL.items() if re.search(rf"\b{k}\b", t)), 0)
    if not n:
        return None
    try:
        from jarvis.core import store
        d = json.loads(store.kv_get("found_files") or "{}")
    except (ValueError, TypeError):
        return None
    paths = d.get("paths") or []
    if not paths or time.time() - float(d.get("t") or 0) > 600 or not 1 <= n <= len(paths):
        return None
    p = Path(paths[n - 1])
    return p if p.exists() else None


def folder_in_words(text: str) -> Path | None:
    """The real folder a request names, also as a path in words: 'from project1, then new project, there is the
    folder Kurama' / 'the kurama folder in new project in project1' -> /media/leo/Project1/New_project/KURAMA.
    The names left after the glue words are tried in both orders as 'X in Y in Z'; only a folder that exists and
    is called like one of the names counts. None when nothing (or more than 4 names) is left."""
    from jarvis.core.paths import smart_path
    if not _VSCODE_NAME.search(text or "") and not re.search(r"\bcode\s+editor\b", text or "", I):
        return None  # only for "... in VS Code": a disk-wide search for every request was 12 s ('open youtube and ...')
    for m in re.finditer(r"(?:~|/)[^\s,;]+", text or ""):  # a real path written out wins
        if (p := Path(m.group(0).rstrip(".")).expanduser()).is_dir():
            return p
    s = _FOLDER_GLUE.sub("|", _VSCODE_NAME.sub("|", text or ""))
    names = [n.strip(" ,.!?'\"") for n in re.split(r"[|,.;!?]+", s)]
    names = [n for n in names if n and not n.isspace()]
    if not 1 <= len(names) <= 4:
        return None

    def key(x: str) -> str:
        return re.sub(r"[\W_]+", "", x.lower())
    for order in (names[::-1], names):
        p = smart_path(" in ".join(order), want="dir")
        if p is not None and p.is_dir() and _alike_name(key(p.name), [key(n) for n in names]):
            return _latest_alike(p, order, key)
    return None


def _alike_name(found: str, said: list[str]) -> bool:
    """The folder found is called like one of the names said ('kurma' / 'kuramaa' for KURAMA: a voice or typing slip)."""
    import difflib
    return any(found == s or (len(s) >= 4 and difflib.SequenceMatcher(None, found, s).ratio() >= 0.8) for s in said)


def _latest_alike(p: Path, order: list[str], key) -> Path:
    """Several folders fit ('kurama in project1': Project1/New_project/KURAMA and Project1/Test_project/KURAMA): the
    one worked in most recently (its git index, else the folder itself, changed last), not the first one found."""
    from jarvis.core import paths
    top = paths.smart_path(order[-1], want="dir") if len(order) > 1 else None
    bases = [top] if top is not None and top != p else paths.roots()
    want = [key(n) for n in order]
    alike = {p}
    for b in bases:
        for c in paths.find_children(b, p.name, depth=4, dirs_only=True, k=8):
            if key(c.name) == key(p.name) and len(c.parts) == len(p.parts) and \
                    all(w in key(str(c)) or _alike_name(key(c.name), [w]) for w in want):
                alike.add(c)

    def used(c: Path) -> float:
        for f in (c / ".git" / "index", c):
            try:
                return f.stat().st_mtime
            except OSError:
                continue
        return 0.0
    return max(alike, key=used)


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
    if not target or len(target.split()) > 6 or re.search(r"\b(?:it|this|that|here|there)\b", target, I):
        return None  # 'open code from this folder': 'this' is the folder in use, never part of a name (it opened
        #              a folder called Code on another disk, 5712fe4c)
    from jarvis.core.paths import smart_path  # a folder that really exists: the gate judges "open X folder", not the
    real = smart_path(target, want="dir") is not None  # name ("open kurama folder" is not about KURAMA itself)
    return Intent("openfolder", "open_folder", "filesearch", {"name": target}, target, known=target if real else "")


_GENERIC_APP = re.compile(r"(?:an?\s+|the\s+|some\s+|any\s+|my\s+)?(?:app|apps|application|program|software|something)",
                          I)


def _open_intent(target: str, verb: str) -> Intent | None:
    if not target or len(target.split()) > 4 or _BAD_TARGET.search(target):
        return None
    if _GENERIC_APP.fullmatch(target.strip(" ?.!")):  # 'can you open app?' opened KDE Connect (11-05)
        return Intent("say", "_say", "apps", {"en": "Which app should I open? Say e.g. 'open VS Code' or 'open Brave'."})
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


_ACTION_LOG = re.compile(r"^(?P<v>minimized|maximized|restored|closed|focused|snapped|opened|moved|copied|renamed|"
                         r"locked|muted|unmuted|paused|resumed|stopped)\s+(?P<x>.{1,80}?)(?P<rest>\s+to\s+the\s+(?:left|right)\s+half)?[.!]?$",
                         re.I)
_NATURAL = {"minimized": "{x} is minimized", "maximized": "{x} is maximized", "restored": "{x} is back on screen",
            "focused": "{x} is in front now", "opened": "{x} is open", "paused": "{x} is paused",
            "muted": "{x} is muted", "unmuted": "{x} is unmuted", "locked": "{x} is locked"}


def natural(text: str, lang: str = "en") -> str:
    """A tool's short action log ('minimized KURAMA', 'snapped VS Code to the left half') as a sentence a person
    would say ('Done — KURAMA is minimized.'). Anything else is returned as it is (owner 11-03: "the reply are weird
    ... it have to give a real kind of reply")."""
    t = (text or "").strip()
    m = _ACTION_LOG.match(t) if lang == "en" and "\n" not in t else None
    if not m:
        return t
    v, x, rest = m.group("v").lower(), m.group("x").strip(), (m.group("rest") or "").strip()
    if v == "snapped" and rest:
        return f"Done — {x} is on the {rest.split()[-2]} half."
    said = _NATURAL.get(v, f"I {v} {{x}}").format(x=x)
    return f"Done — {said}."


def render(intent: Intent, ok: bool, output: str, lang: str) -> str:
    if intent.name in ("say", "cached"):
        return intent.args.get(lang) or intent.args["en"]
    if intent.name == "learned":  # a learned shortcut: the tool's own sentence
        return (output[:1].upper() + output[1:]) if output else output
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
        if out.startswith(("Yes, I can", "I can't do that yet")):  # find_capability's own plain answer
            return out
        lines = [ln[2:].split(" (", 1)[0].replace("_", " ") for ln in out.splitlines() if ln.startswith("- ")]
        if not lines:
            return ("I don't have a tool for that yet. I can search the web for the steps, or build a small new "
                    "tool for it if you like.")
        return f"Yes, I can help with {intent.label}. These of my tools fit: {', '.join(lines[:4])}. Shall I start?"
    if intent.name == "listdir":
        return _render_listdir(intent, out)
    return natural(out, lang) if ok else out  # weather / recall / digest...: the tool output is already text


def _render_listdir(intent: Intent, out: str) -> str:
    """The numbered list itself, in the chat (11-06: "it's in your workspace" and the owner couldn't see it);
    only a very long one (over 60 lines) shows its start here and the whole of it in the Workspace."""
    lines = out.splitlines()
    if len(lines) <= 60:
        body = "\n".join(re.sub(r"^(/\S.*?) : (\d.*)$", lambda m: f"{Path(m.group(1)).name} has {m.group(2)}:", ln)
                         for ln in lines)
        return body + ("\n\nSay 'open 3 in VS Code' or 'send 3'." if re.search(r"^\d+\. ", out, re.M) else "")
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
        ok, output = res.ok, (getattr(res, "full", "") or res.output)  # the user gets the whole text (the AI's copy is cut)
        if shelf:
            from jarvis.core import workspace
            output = workspace.strip_note(output)  # "[The full result ... is shown in the workspace]" is for the AI
            intent.args.setdefault("_published", shelf[-1])
    if rid := intent.args.get("_recipe"):  # a learned shortcut: it worked, or the AI does it this time (and after
        from jarvis.core import recipes  # RECIPE_MAX_FAILS failures in a row it is switched off)
        if not recipes.ran(rid, ok and not (output or "").lstrip().lower().startswith("error")):
            return None
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
    if mode == "voice" and intent.name == "cached":  # a kept text answer, spoken: its first two sentences
        answer = " ".join(re.split(r"(?<=[.!?])\s+", answer.strip())[:2])
    ms = int((time.monotonic() - t0) * 1000)
    try:
        store.log_routing(text, [intent.group], "fastpath", ms)
    except Exception as e:
        log.warning("could not log routing: %s", e)
    return FastResult(answer, intent, ok, ms, published, started)


from jarvis.core.intents.control import (  # noqa: F401  (moved; names kept here for callers and tests)
    REMIND, REMIND_CANCEL, REMIND_LIST, SWITCH_TTL_S, _ALARM, _AMOUNT,
    _AOD, _AWAKE_ASK, _AWAKE_OFF, _AWAKE_ON, _CHART, _DEV,  # noqa: F811 (this second _DEV is the one the code below uses)
    _DEVICES, _HABIT_DONE, _HI_TIME, _HI_WAKE, _LOGOUT, _NUM,
    _PHONE_TAIL, _POWERMODE, _RESTART, _SHUTDOWN, _STOPWATCH, _SUSPEND,
    _SW_FILL, _SW_FOLLOW, _SW_VERB, _TIMER, _TRAINING_Q, _UNIT,
    _WALL_CHANGE, _WHEN_FIRST, _WHEN_NOW, _amount, _control_intent, _everyday_intent,
    _hinglish_when, _p9b_intent, switch_intent,
)


