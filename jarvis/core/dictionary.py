"""Offline English dictionary (0 tokens): Open English WordNet 2024 in data/wordnet/wn.db (the `wn` package).

'what does serendipity mean', a highlighted word -> part of speech, the main meanings, one example, a few synonyms.
Words it doesn't know (names, slang, phrases) fall back to the AI in assist.meaning(). Setup once:
venv/bin/python -c "import wn; wn.config.data_directory='data/wordnet'; wn.download('oewn:2024')"
"""
from __future__ import annotations

import logging
import re

from jarvis.core import config

log = logging.getLogger(__name__)
POS = {"n": "noun", "v": "verb", "a": "adjective", "s": "adjective", "r": "adverb"}
_en = None


def _wordnet():
    global _en
    if _en is None:
        db = config.WORDNET_DB
        if not db.exists():
            return None
        import wn
        wn.config.data_directory = str(db.parent)
        wn.config.allow_multithreading = True  # the API serves requests from a thread pool
        _en = wn.Wordnet("oewn:2024")
    return _en


def available() -> bool:
    return config.WORDNET_DB.exists()


def lookup(word: str, senses: int = 2) -> str | None:
    """'serendipity (noun): good luck in making unexpected and fortunate discoveries.' + example + synonyms."""
    w = re.sub(r"[^\w\s'-]", "", (word or "").strip().lower())
    if not w or len(w.split()) > 3:
        return None
    try:
        en = _wordnet()
        if en is None:
            return None
        synsets = en.synsets(w) or en.synsets(w.replace(" ", "_")) or en.synsets(w.replace(" ", "-"))
    except Exception as e:  # a broken db must never break the meaning answer
        log.warning("wordnet lookup failed: %s", e)
        return None
    if not synsets:
        return None
    by_pos: dict[str, list] = {}
    for s in synsets:
        by_pos.setdefault(POS.get(s.pos, s.pos), []).append(s)
    lines, example, syns = [], "", []
    for pos, ss in sorted(by_pos.items(), key=lambda kv: -len(kv[1]))[:2]:  # the commoner use first ('run' = verb)
        defs = [s.definition() for s in ss[:senses] if s.definition()]
        if not defs:
            continue
        lines.append(f"{w} ({pos}): " + "; ".join(f"{i}. {d}" if len(defs) > 1 else d
                                                  for i, d in enumerate(defs, 1)) + ".")
        if not example:
            example = next((e for s in ss[:senses] for e in s.examples()), "")
        for s in ss[:2]:
            syns += [x for x in s.lemmas() if x.lower() != w and x not in syns]
    if not lines:
        return None
    out = "\n".join(lines)
    if example:
        out += f"\nExample: {example}."
    if syns:
        out += f"\nSimilar: {', '.join(x.replace('_', ' ') for x in syns[:4])}."
    return out
