"""Fast-path intents for files and folders: open, search, list a folder, find, send to Telegram.

Moved out of fastpath.py unchanged; fastpath re-imports every name, so `fastpath.X` still works."""
from __future__ import annotations

import re
from jarvis.core.intents.base import I, Intent, _full, _rx


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
                           r"|\b(?:news|weather|time|price|who|what\s+is|meaning|define|online|internet|web|song|video\s+of)\b"
                           # a size / age, not a name ('the biggest files in downloads': the AI sorts, find_files order)
                           r"|\b(?:biggest|largest|smallest|heaviest|huge|newest|oldest|latest|most\s+recent|recently)\b", re.I)


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
        if re.search(r"\s+(?:folder|directory)\s+(?:in|inside|under|within)\s", q, I):
            kind = "folder"  # 'find kurama folder in project1' listed 20 files too (11-04)
        elif re.search(r"\s+file\s+(?:in|inside|under|within)\s", q, I):
            kind = "name"
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
                r"(?:photo|picture|image|pic|wallpaper|(?:pie\s+|bar\s+|line\s+)?(?:chart|graph|plot)|diagram)"  # a chart is a picture
                r"(?:\s+(?:you\s+)?(?:made|generated|created|drew|drawn))?" + _TGDEST +
                r"?(?:\s+(?:as\s+well|too|also|again|now|please))?\s*[.!?]*$", t, I):  # '... as well' drew a NEW one
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


_RANKED = re.compile(r"^(?:please\s+)?(?:find|show|list|give\s+me|what\s+are)\s+(?:me\s+)?(?:the\s+|my\s+)?(?:(?P<n>\d+)\s+)?"
                     r"(?P<o>biggest|largest|heaviest|newest|latest|most\s+recent|recent)\s+(?:(?P<n2>\d+)\s+)?"
                     r"(?P<q>[\w.*]+\s+)?files?\s+(?:in|on|inside|from)\s+(?:my\s+|the\s+)?(?P<p>.+?)[\s.?!]*$", I)


def ranked_files_intent(t: str) -> Intent | None:
    """'find the biggest files in my downloads' / 'show the 5 newest pdf files in documents': sorted, 0 tokens (the AI
    listed the folder and wrote its own script: 5,054 tokens, 11-04)."""
    m = _RANKED.match(t or "")
    if not m:
        return None
    order = "biggest" if m.group("o").lower() in ("biggest", "largest", "heaviest") else "newest"
    q = (m.group("q") or "").strip().lower()
    q = f"*.{q.lstrip('*.')}" if q and q not in ("all", "the", "my") else "*"
    return Intent("findfile", "find_files", "filesearch", {"query": q, "path": m.group("p").strip(), "kind": "name",
                                                           "order": order, "limit": int(m.group("n") or m.group("n2") or 10)})


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

    # 'carry minati on youtube and google': the same words searched on EACH site (it searched Google for the whole
    # 'carry minati on youtube and google', 11-03)
    sites = r"(?:google|youtube|you\s*tube|wikipedia|wiki)"
    if mm := re.fullmatch(rf"(?P<q>.+?)\s+(?:on|in|at)\s+(?:both\s+)?(?P<e>{sites}(?:\s*(?:,|and|&|or)\s*{sites})+)", q, I):
        engs = []
        for e in re.findall(sites, mm.group("e"), I):
            e = "wikipedia" if e.lower() == "wiki" else re.sub(r"\s+", "", e.lower())
            if e not in engs:
                engs.append(e)
        q2 = mm.group("q").strip(" ,")
        urls = ", ".join(SEARCH_URLS[e].format(q=quote_plus(q2)) for e in engs)
        names = ", ".join(SEARCH_NAMES[e] for e in engs[:-1]) + " and " + SEARCH_NAMES[engs[-1]]
        return Intent("search", "apps", "browser", {"action": "open", "target": urls}, f"{names}|{q2}")
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
