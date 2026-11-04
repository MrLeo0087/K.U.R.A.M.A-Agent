"""Profile: facts about the owner (name, city, likes...), learned from what they said."""
from __future__ import annotations

from jarvis.core.memories import Hit, MemorySource, words


def _search(query: str, k: int) -> list[Hit]:
    from jarvis.core import profile, store
    q = words(query)
    scored = []
    for f in store.profile_all():
        n = len(q & (words(f["key"].replace("_", " ")) | words(f["value"])))
        if n:
            scored.append((n, f))
    scored.sort(key=lambda x: -x[0])
    return [Hit(profile.render_fact(f), ref=f"profile:{f['key']}") for _, f in scored[:k]]


SOURCE = MemorySource("profile", "Facts about you", _search)
