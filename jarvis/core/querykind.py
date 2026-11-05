"""What KIND of request this is, decided first, before any tool is picked (0 tokens, by meaning):

    help     "how can I send a file to my phone?", "do you have the ability to convert pdf?", "help me with X",
             "is it possible to ...": a question about USING KURAMA -> the command to say (find_capability),
             never the action itself (it shared a folder over Wi-Fi and converted a random file).
    explain  "how did you do that?", "how do you measure my speed?", "why did you ...": about what KURAMA does or
             just did -> explain_self (facts from the real record + the code).
    again    "run it for 30 seconds", "do it again", "make it 50": the last request again, with the new value.
    None     a command or a normal question: the usual path.

The kind comes from how the request STARTS (its first 2-5 words compared by meaning with config.QUERY_OPENINGS), so
a long or misspelled rest can't change it. A help question no tool fits ("how do I cook rice?") is a normal question.
"""
from __future__ import annotations

import re
import threading
import time

from jarvis.core import config

I = re.I
_inside = threading.local()  # 'again' rebuilds a request and matches it: never twice in a row


def opening_kind(text: str) -> tuple[str, float, int] | None:
    """(kind, closeness, how many words the opening is) for the request's first 2-5 words, or None."""
    from jarvis.core import semantic
    if not semantic.ensure_ready():  # the kind must never depend on whether the model happened to be loaded
        return None
    toks = re.findall(r"[\w'.+#-]+", text or "")
    best = None
    for k in (2, 3, 4, 5):
        if k > len(toks) - 1:  # an opening needs something after it
            break
        b = semantic.best_of(" ".join(toks[:k]).lower(), "query_openings", config.QUERY_OPENINGS)
        if b and (best is None or b[1] > best[1] + 0.005):
            best = (b[0], b[1], k)
    return best if best and best[1] >= config.QUERY_OPENING_MIN else None


def rest_after(text: str, k: int) -> str:
    """The words after the opening: the need ('how can i | send a file to my phone' -> 'send a file to my phone')."""
    toks = re.findall(r"\S+", text or "")
    rest = " ".join(toks[k:]).strip(" ?.!,")
    return re.sub(r"^(?:to|for|with|about)\s+", "", rest, flags=I)


def last_request(max_age_s: float = 600) -> dict | None:
    """The previous request (not this one) if it was recent."""
    try:
        from jarvis.core import trace
        cur = (trace.current() or {}).get("id")
        for r in trace.recent(1, 4):
            if r["id"] != cur and time.time() - float(r["ts"]) <= max_age_s:
                return trace.get(r["id"]) or r
    except Exception:  # noqa: BLE001
        pass
    return None


_VALUE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(%|percent|seconds?|secs?|minutes?|mins?|hours?|hrs?|ms|times?)?\b", I)
_POINTS_BACK = re.compile(r"\b(?:it|that|this|again|same|once more)\b", I)


def again(text: str):
    """'run it for 30 seconds' / 'do that again' / 'make it 50' right after a request: that request once more,
    with the new value. Only when the rebuilt request is the SAME action (else None)."""
    t = " ".join((text or "").split())
    if len(t.split()) > 8 or not _POINTS_BACK.search(t):
        return None
    last = last_request()
    if not last or not last.get("text") or last.get("path") not in ("fastpath", None):
        return None
    prev = str(last["text"]).strip(" .!?")
    new = _VALUE.search(t)
    if new:
        old = _VALUE.search(prev)
        rebuilt = (prev[:old.start()] + new.group(0) + prev[old.end():]) if old else f"{prev} for {new.group(0)}"
    elif re.search(r"\b(?:again|once more|same)\b", t, I):
        rebuilt = prev
    else:
        return None
    from jarvis.core import fastpath
    if getattr(_inside, "on", False):
        return None
    _inside.on = True
    try:
        it = fastpath.match(rebuilt)
    finally:
        _inside.on = False
    try:
        import json
        was = {c.get("name") for c in json.loads(last.get("tools") or "[]")}
    except ValueError:
        was = set()
    return it if it is not None and it.tool in was else None


def _about_last_thing(need: str) -> bool:
    """The need names the thing the last request made ('use colab notebook' after 'set up colab notebook')."""
    last = last_request()
    if not last:
        return False
    if re.search(r"\b(?:it|this|that|these|those)\b", need, I):
        return True
    common = {"with", "from", "into", "file", "files", "this", "that", "make", "open", "send", "take", "give", "show",
              "tell", "find", "write", "have", "what", "your", "about", "want"}
    words = {w for w in re.findall(r"[a-z]{4,}", need.lower())} - common
    return bool(words) and len(words & set(re.findall(r"[a-z]{4,}", str(last.get("text") or "").lower()))) >= min(2, len(words))


def nepal(text: str) -> bool:
    """A question for the Nepal documents (laws, legal processes, services and fees, Nepal general knowledge), not
    live data: its meaning is closest to config.LANE_EXAMPLES['nepal'] by NEPAL_LANE_MARGIN over every other lane.
    Devanagari (the meaning model reads English only): config.NEPAL_DEVANAGARI_WORDS stand in."""
    t = text or ""
    if re.search(r"[\u0900-\u097F]", t):
        return any(w in t for w in config.NEPAL_DEVANAGARI_WORDS) and not re.search(
            r"आज|अहिले|अहिलेको|भोलि|मौसम|समाचार|मूल्य|भाउ", t)  # today / now / weather / news / price: live data
    from jarvis.core import lanes
    s = lanes.scores(t)
    if not s or "nepal" not in s:
        return False
    rest = max((v for k, v in s.items() if k != "nepal"), default=0.0)
    v = s["nepal"]  # close and ahead, or a little less close but far ahead ('what is divorce process': .75 vs .57)
    return (v >= config.NEPAL_LANE_MIN and v - rest >= config.NEPAL_LANE_MARGIN) or (v >= 0.70 and v - rest >= 0.12)


def route(text: str):
    """The Intent for the request's KIND, or None (the usual path decides). The kinds, in order:
    again ('run it for 30 seconds') > explain ('how did you…') > nepal documents (laws, processes, Nepal facts) >
    help ('how can I…' with a tool that fits) > everything else (general chat, live search, actions: the
    usual path: small talk, the router, the tools)."""
    from jarvis.core import safety
    from jarvis.core.fastpath import Intent
    if safety.parse_yes_no(text) is not None and len((text or "").split()) <= 4:
        return None  # 'ok go ahead' / 'yeah do it' answer a question: never a help request
    if (it := again(text)) is not None:
        return it
    raw = " ".join((text or "").split()).strip(" ?.!")
    k = opening_kind(text)
    kind, n = (k[0], k[2]) if k else ("", 0)
    pronoun = r"(?:(?:do|make|run|open|send)\s+)?(?:it|that|this|them)(?:\s+or\s+not)?"
    if kind == "command" and re.fullmatch(pronoun, rest_after(raw, n), I):
        return Intent("explain", "explain_self", "self", {"question": raw})  # 'can you do it or not?'
    if kind == "explain" or (kind == "help" and _about_last_thing(rest_after(raw, n))):
        return Intent("explain", "explain_self", "self", {"question": raw})  # 'how can I use it' right after
    if nepal(raw):  # 'what is the citizenship fee', 'how do I get a passport in Nepal', 'नेपालको सबैभन्दा ठूलो जिल्ला'
        return Intent("nepal", "nepal_docs", "nepal", {"question": raw})
    if kind in ("help", "ability"):
        need = rest_after(raw, n)
        if not need or re.fullmatch(pronoun, need, I):
            return Intent("explain", "explain_self", "self", {"question": raw})
        from jarvis.core import selfindex
        card, sure = selfindex.best_for(need)
        if card is not None and sure >= config.HELP_TOOL_MIN:
            return Intent("can", "find_capability", "self", {"need": need})
    if kind == "ability":  # 'are you able to fly?': a clear no, with what to do instead
        return Intent("can", "find_capability", "self", {"need": rest_after(raw, n)})
    return None  # general chat, a live search, an action: the usual path
