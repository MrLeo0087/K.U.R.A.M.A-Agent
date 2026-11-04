"""Fast-path intents that make things: music, video, audio, diagrams, charts, images.

Moved out of fastpath.py unchanged; fastpath re-imports every name, so `fastpath.X` still works."""
from __future__ import annotations

import re
from jarvis.core.intents.base import I, Intent, _period


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
    tm = r"(?P<n>\d+(?::\d{2})?\s*(?:seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?)?(?:\s+(?:and\s+)?\d+\s*(?:seconds?|secs?|s))?)"
    if music.running():  # 'skip 30 seconds', 'go back 10 seconds', 'jump to 2 minutes', 'start from 1:30' (11-04: none)
        if m := re.fullmatch(lead + r"(?:skip|forward|fast\s*forward|go\s+forward|move\s+forward|jump\s+(?:ahead|forward)|ahead)"
                             r"\s+(?:by\s+)?" + tm + r"(?:\s+(?:ahead|forward))?[\s.!]*", low, I):
            return mu("seek", "+" + m.group("n"))
        if m := re.fullmatch(lead + r"(?:go\s+back|back|rewind|move\s+back|jump\s+back|skip\s+back)\s+(?:by\s+)?" + tm
                             + r"(?:\s+back)?[\s.!]*", low, I):
            return mu("seek", "-" + m.group("n"))
        if m := re.fullmatch(lead + r"(?:(?:jump|go|skip|seek|move)\s+(?:direct(?:ly)?\s+)?to|(?:start|play|resume)\s+(?:it\s+|the\s+"
                             r"(?:song|music)\s+)?(?:again\s+)?from)\s+(?:the\s+)?" + tm + r"(?:\s+mark)?[\s.!]*", low, I):
            return mu("seek", m.group("n"))
    if re.fullmatch(lead + r"(?:next|skip|skip\s+(?:it|this|the\s+song|this\s+song)|next\s+(?:one|song|track|music)|play\s+(?:the\s+)?next"
                    r"(?:\s+(?:song|track|one))?|another\s+one|change\s+(?:it|the\s+song))[\s.!]*", low, I) and music.running():
        return Intent("media", "media_control", "media", {"action": "next"}, "media")
    if re.fullmatch(lead + r"(?:previous|back|go\s+back|last\s+one|previous\s+(?:song|track|one)|play\s+(?:the\s+)?previous"
                    r"(?:\s+(?:song|track|one))?)[\s.!]*", low, I) and music.running():
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
    # 'play us mod se shuru kare' / 'play tu hai kaha': a song's title alone (11-03: the AI took 5-7 s and 5k tokens,
    # once searched the web instead); the meaning gate still decides it is music, the browser / games keep theirs
    if (m := re.fullmatch(lead + r"(?:play|bajau|bajaau)\s+(?P<q>[^\W\d][\w' -]{2,60}?)[\s.!]*", t, I)) \
            and len(m.group("q").split()) <= 8 and not _NOT_A_SONG.search(m.group("q")):
        return mu("play", m.group("q").strip())
    return None


_NOT_A_SONG = re.compile(r"\b(?:it|this|that|these|those|video|videos|youtube|movie|film|tab|game|games|chess|cards|"
                         r"next|previous|again|back|pause|music\s+folder|my|from|in\s+(?:the\s+)?browser)\b", I)


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
