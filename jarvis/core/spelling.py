"""Common slips fixed before a request is understood (0 tokens): real words used by mistake, which the typo fixer
leaves alone because they ARE words ('remain me' -> remind me, 'remainder' -> reminder, 'expensive' -> expenses), and
frequent typos from the owner's traces ('opne', 'budjet', 'funtion', 'fodler'). Whole words only; names are never
touched (only the words listed here change). Agent.run / Agent.stream apply it; the trace keeps what was said."""
from __future__ import annotations

import re

_FIX: list[tuple[str, str]] = [
    (r"\bremain(?=\s+me\b)", "remind"), (r"\bremainders?\b", "reminder"), (r"\b(?:raminders?|reminers?|remiders?)\b", "reminder"),
    (r"\b(?:alaram|alram|allarm|alaram)\b", "alarm"), (r"\bbudjets?\b", "budget"),
    (r"(?:(?<=\bmy )|(?<=\bin )|(?<=\bof )|(?<=\bthe ))expensive\b", "expenses"), (r"\b(?:ruppes|ruppess|ruppees|rupess)\b", "rupees"),
    (r"\b(?:funtion|fuction|funcion)\b", "function"), (r"\b(?:pyhton|pyton)\b", "python"), (r"\bcalculater\b", "calculator"),
    (r"\b(?:opne|oprn)\b", "open"), (r"\b(?:goolge|googel|gogle)\b", "google"), (r"\b(?:laptlp|labtop|leptop)\b", "laptop"),
    (r"\bdisply\b", "display"), (r"\b(?:moeny|mony)\b", "money"), (r"\bwffi\b", "wifi"), (r"\bscreen\s+shot\b", "screenshot"),
    (r"\bthne\b", "then"), (r"\b(?:fodler|foldr|floder)\b", "folder"), (r"\bsettign\b", "setting"),
]
_RX = [(re.compile(a, re.I), b) for a, b in _FIX]


def fix(text: str) -> str:
    t = text or ""
    for rx, to in _RX:
        t = rx.sub(lambda m: _case(m.group(0), to), t)
    return t


def _case(said: str, to: str) -> str:
    return to.capitalize() if said[:1].isupper() else to
