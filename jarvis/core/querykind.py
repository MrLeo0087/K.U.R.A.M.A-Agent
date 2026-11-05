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
    words = {w for w in re.findall(r"[a-z]{4,}", need.lower())} - {"with", "from", "into", "file", "files", "this", "that"}
    return len(words & set(re.findall(r"[a-z]{4,}", str(last.get("text") or "").lower()))) >= 1


def route(text: str):
    """The Intent for a help / explain / again request, or None (the usual path decides)."""
    from jarvis.core import safety
    from jarvis.core.fastpath import Intent
    if safety.parse_yes_no(text) is not None and len((text or "").split()) <= 4:
        return None  # 'ok go ahead' / 'yeah do it' answer a question: never a help request
    if (it := again(text)) is not None:
        return it
    k = opening_kind(text)
    if k is None:
        return None
    kind, _score, n = k
    raw = " ".join((text or "").split()).strip(" ?.!")
    if kind == "command":  # 'can you open youtube': a command (only 'can you do it or not?' asks about the last one)
        if re.fullmatch(r"(?:(?:do|make|run|open|send)\s+)?(?:it|that|this|them)(?:\s+or\s+not)?", rest_after(raw, n), I):
            return Intent("explain", "explain_self", "self", {"question": raw})
        return None
    if kind == "help" and _about_last_thing(rest_after(raw, n)):  # 'how can I use colab notebook' right after
        return Intent("explain", "explain_self", "self", {"question": raw})  # 'set up colab notebook'
    if kind == "explain":
        return Intent("explain", "explain_self", "self", {"question": raw})
    need = rest_after(raw, n)
    if not need or re.fullmatch(r"(?:(?:do|make|run|open|send)\s+)?(?:it|that|this|them)(?:\s+or\s+not)?", need, I):
        return Intent("explain", "explain_self", "self", {"question": raw})  # 'can you do it or not?'
    from jarvis.core import selfindex
    card, sure = selfindex.best_for(need)
    if card is None or sure < config.HELP_TOOL_MIN:
        if kind == "ability":  # 'are you able to fly?': a clear no, with what to do instead
            return Intent("can", "find_capability", "self", {"need": need})
        return None  # 'how do I cook rice?': a normal question for the AI
    return Intent("can", "find_capability", "self", {"need": need})
