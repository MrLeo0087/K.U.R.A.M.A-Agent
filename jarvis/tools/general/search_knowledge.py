"""search_knowledge: hybrid (BM25 + vector) search over the user's indexed code and notes (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


def empty_index_reply() -> str:
    from jarvis.core import memory

    job = memory.start_index_job(None)
    return (f"Your knowledge index is empty, so I started indexing your project and notes (job #{job.id}). "
            "Ask again in a minute.")


@tool(group="knowledge", safety="safe", description="Search the user's own code, docs and notes; returns file:lines with short snippets.")
def search_knowledge(query: str, k: int = 5) -> str:
    """Search code and notes.

    Args:
        query: What to look for, in plain words.
        k: Number of hits (1-8).
    """
    from jarvis.core import config, memory

    query = (query or "").strip()
    if not query:
        return "error: give something to search for"
    idx = memory.get_index()
    if idx.count_chunks() == 0:
        return empty_index_reply()
    hits = idx.search(query, k=max(1, min(int(k or config.KNOWLEDGE_K), 8)))
    if not hits:
        return f"Nothing in your indexed files matches {query!r}."
    return memory.format_hits(hits)
