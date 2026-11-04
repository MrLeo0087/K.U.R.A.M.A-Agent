"""Memory sources: every kind of thing KURAMA remembers, behind one small contract, so a new kind of memory is
one new file and never touches the others.

    jarvis/memories/<name>.py defines  SOURCE = MemorySource(name, description, search, heavy=False)
    search(query, k) -> list[Hit]      each Hit: text, where it came from (ref), a score (higher = better)

`search(query)` asks every light source (a heavy one, e.g. the embedding index of your documents, only when asked
for by name or with heavy=True), isolates failures (a broken source is logged and skipped), and merges the lists
with reciprocal rank fusion, the same method the document search uses. 0 tokens: nothing here calls an AI.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger("jarvis.memories")

PACKAGE = "jarvis.memories"
RRF_K = 60


@dataclass
class Hit:
    text: str
    source: str = ""
    ref: str = ""  # where it is: a note id, a file path, a link
    score: float = 0.0


@dataclass
class MemorySource:
    name: str
    description: str  # one line: what this memory holds
    search: Callable[[str, int], list[Hit]]
    heavy: bool = False  # loads a model or scans a lot: only when asked for
    extra: dict = field(default_factory=dict)


_cache: dict[str, MemorySource] | None = None


def sources() -> dict[str, MemorySource]:
    """Every memory source in jarvis/memories/ (found once, then cached)."""
    global _cache
    if _cache is None:
        from jarvis.core import plugins
        _cache = {s.name: s for s in plugins.load(PACKAGE, "SOURCE").values() if isinstance(s, MemorySource)}
    return _cache


def search(query: str, k: int = 5, only: list[str] | tuple[str, ...] | None = None, heavy: bool = False) -> list[Hit]:
    """The best k hits across the sources (all light ones by default), fused by rank."""
    query = (query or "").strip()
    if not query:
        return []
    fused: dict[tuple[str, str], tuple[float, Hit]] = {}
    for name, src in sources().items():
        if only is not None and name not in only:
            continue
        if only is None and src.heavy and not heavy:
            continue
        try:
            hits = src.search(query, k) or []
        except Exception as e:  # noqa: BLE001 - one broken memory must not hide the others
            log.warning("memory source %s failed: %s", name, e)
            continue
        for rank, h in enumerate(hits[:k]):
            h.source = h.source or name
            key = (h.source, h.ref or h.text)
            prev = fused.get(key, (0.0, h))[0]
            fused[key] = (prev + 1.0 / (RRF_K + rank + 1), h)
    ranked = sorted(fused.values(), key=lambda x: -x[0])
    return [h for _, h in ranked[:k]]


def words(text: str) -> set[str]:
    """Lower-case words of 3+ letters (a tiny helper for simple word-overlap sources)."""
    import re
    return {w for w in re.findall(r"[\w']{3,}", (text or "").lower())}
