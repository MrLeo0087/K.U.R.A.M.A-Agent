"""Is it a real English word? (the system dictionary, loaded once on first need, ~6 MB; never at startup)."""
from __future__ import annotations

_words: frozenset[str] | None = None


def is_word(w: str) -> bool:
    global _words
    if _words is None:
        try:
            with open("/usr/share/dict/words", encoding="utf-8", errors="ignore") as fh:
                _words = frozenset(x.strip().lower() for x in fh if x.strip().isalpha())
        except OSError:
            _words = frozenset()
    return (w or "").lower() in _words
