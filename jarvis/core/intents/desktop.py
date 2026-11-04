"""Fast-path intents for the desktop: volume, brightness, media keys, DND, night light, power modes, alert mute, usage.

Moved out of fastpath.py unchanged; fastpath re-imports every name, so `fastpath.X` still works."""
from __future__ import annotations

import re
import time
from jarvis.core.intents.base import I, Intent, _full, _rx


# --- desktop controls (P5b) ---
_N = r"(?P<n>\d{1,3})"


_PCT = r"(?: ?%| percent| pratishat| प्रतिशत)?"


_BY = r"(?: by (?P<n>\d{1,2})(?: ?%| percent)?)?"


_UP_HI = r"(?:badhao|badha do|badhau|badhaunu|barhao|बढ़ाओ|बढाओ|बढ़ा दो|बढाउ|बढाऊ|बढाइदेउ)"


_DOWN_HI = r"(?:kam karo|kam kar do|ghatao|ghatau|ghataunu|कम करो|कम कर दो|घटाओ|घटाउ|घटाऊ|घटाइदेउ)"


_DO_HI = r"(?:karo|kar do|gara|garnu|garideu|करो|कर दो|गर|गर्नु|गरिदेउ)"


_DEV = r"(?:(?:laptop|system|computer|device|pc|speaker)(?:'s)? )?"  # 'increase the laptop volume': with KURAMA's music


# playing, plain 'volume' is the music's, so the laptop's needed these words (11-03: none of them had a shortcut)
_VOL = r"(?:the )?" + _DEV + r"(?:volume|sound)"


_VOL_HI = r"(?:awaz|awaaz|awaj|awaaj|volume|आवाज़|आवाज|भोल्युम)"


_BRI = r"(?:the )?(?:screen )?brightness"


_BRI_HI = r"(?:brightness|ब्राइटनेस|चमक)"


LEVELS = {  # name -> (tool, group, {action: patterns})
    "volume": ("volume", "audio", {
        "set": _rx(r"(?:set|change|put|turn|make|keep) " + _VOL + r"(?: level)? (?:to |at )?" + _N + _PCT,
                   r"" + _DEV + r"(?:volume|sound)(?: level)? (?:to |at )?" + _N + _PCT,
                   _VOL_HI + " " + _N + _PCT + " " + _DO_HI),
        "up": _rx(r"(?:turn|bump|crank) up " + _VOL + _BY, r"(?:turn|bump|crank) " + _VOL + " up" + _BY,
                  r"(?:increase|raise) (?:the )?(?:more )?" + _DEV + r"(?:volume|sound)(?: more| a bit| a little)?" + _BY,
                  r"" + _DEV + r"(?:volume|sound) up" + _BY, r"(?:make it )?louder",
                  _VOL_HI + " " + _UP_HI),
        "down": _rx(r"turn down " + _VOL + _BY, r"turn " + _VOL + " down" + _BY,
                    r"(?:decrease|lower|reduce) (?:the )?(?:more )?" + _DEV + r"(?:volume|sound)(?: more| a bit| a little)?" + _BY,
                    r"" + _DEV + r"(?:volume|sound) down" + _BY,
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
