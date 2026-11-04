"""Notes: what the owner asked KURAMA to remember ('remember that my locker code is...')."""
from __future__ import annotations

from jarvis.core.memories import Hit, MemorySource, words


def _search(query: str, k: int) -> list[Hit]:
    from jarvis.core import store
    rows = store.notes_recent(k, query)  # the exact phrase first
    if not rows:  # then any note sharing a word
        q = words(query)
        rows = [r for r in store.notes_recent(200) if q & words(r["text"])][:k]
    return [Hit(r["text"], ref=f"note:{r.get('id', '')}") for r in rows]


SOURCE = MemorySource("notes", "Things you asked me to remember", _search)
