"""Documents: the owner's own notes and code, indexed for hybrid search (FTS5 + vectors). Heavy: it may load
the embedding model, so it is searched only when asked for by name (memories.search(q, only=["documents"]))."""
from __future__ import annotations

from jarvis.core.memories import Hit, MemorySource


def _search(query: str, k: int) -> list[Hit]:
    from jarvis.core import memory
    return [Hit(h.text[:300], ref=f"{h.path}:{h.start}-{h.end}", score=h.score) for h in memory.search(query, k)]


SOURCE = MemorySource("documents", "Your own documents and code", _search, heavy=True)
