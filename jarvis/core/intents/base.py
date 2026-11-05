"""Shared pieces of the zero-token fast path: the Intent/FastResult types and small text helpers.

Moved out of fastpath.py unchanged; fastpath re-imports every name, so `fastpath.X` still works."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


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


def _rx(*alts: str) -> list[re.Pattern]:
    return [re.compile(a, I) for a in alts]


def _full(patterns: list[re.Pattern], text: str) -> re.Match | None:
    for p in patterns:
        if m := p.fullmatch(text):
            return m
    return None


_PERIOD = (("today", r"\btoday|aaja|आज\b"), ("yesterday", r"\byesterday|hijo|हिजो\b"),
           ("last_month", r"\blast\s+month|previous\s+month|gayeko\s+mahina\b"),
           ("week", r"\b(?:this\s+|the\s+|per\s+|a\s+)?week(?:ly)?\b|\bhapta\b"),
           ("year", r"\b(?:this\s+|the\s+|per\s+)?year(?:ly)?\b|\bbarsa\b"),
           ("month", r"\b(?:this\s+|the\s+|per\s+)?month(?:ly)?\b|\bmahina\b|महिना"))


def _period(t: str, default: str = "month") -> str:
    return next((p for p, rx in _PERIOD if re.search(rx, t, I)), default)


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
    if s[0] in ("ok", "okay", "alright", "sure", "fine") and len(s) > 1 and s[1] not in _YES_WORDS | _NO_WORDS | {
            "go", "do", "add", "please", "now", "then", "thanks", "thank", "bro", "kurama"}:
        return ""  # 'Ok, replace it.' is a new request, not a yes to the offer before it (ca0ed9c4 explained more)
    if s[0] in ("stop", "cancel") and len(s) > 1 and s[1] not in ("it", "that", "this", "please", "now", "kurama"):
        return ""  # 'stop watching claude code', 'cancel the timer': a command, not a "no" to a question
    if s[0] in _NO_WORDS or _NO_LEADS.match(joined):
        return "no"
    if s[0] in _YES_WORDS or _YES_LEADS.match(joined):
        return "" if re.search(r"\b(?:but|instead|change|make\s+it|shorter|longer|different)\b", joined) and s[0] != "yes" else "yes"
    return ""


URL_RE = re.compile(r"https?://\S+", I)


_RL_LIST = r"(?:reading\s+list|read[\s-]+later(?:\s+list)?|saved\s+(?:links|articles|pages))"


_ORD = {"first": 1, "1st": 1, "one": 1, "second": 2, "2nd": 2, "two": 2, "third": 3, "3rd": 3, "three": 3, "fourth": 4,
        "4th": 4, "four": 4, "fifth": 5, "5th": 5, "five": 5, "last": -1, "next": 1, "top": 1, "newest": 1, "latest": 1}


def _nth(t: str) -> int:
    if m := re.search(r"\b(?:number|no\.?|item|#)?\s*(\d{1,3})\b", t):
        return int(m.group(1))
    m = re.search(r"\b(" + "|".join(_ORD) + r")\b", t, I)  # (_NUM further down is the cardinal-number table)
    return _ORD[m.group(1).lower()] if m else 1
