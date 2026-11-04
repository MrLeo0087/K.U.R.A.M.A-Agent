"""Links: named links the owner saved ('the link for Claude Code')."""
from __future__ import annotations

from jarvis.core.memories import Hit, MemorySource, words


def _search(query: str, k: int) -> list[Hit]:
    from jarvis.core import links
    q = words(query)
    rows = [r for r in links._rows() if q & words(" ".join(str(r.get(c) or "") for c in ("Name", "Title", "Site")))]
    return [Hit(f"{r.get('Name')}: {r.get('Link')}", ref=str(r.get("Link") or "")) for r in rows[:k]]


SOURCE = MemorySource("links", "Links you saved by name", _search)
