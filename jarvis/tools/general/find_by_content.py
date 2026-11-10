"""find_by_content: find a document by what is INSIDE it ("the PDF about attention I downloaded last week"), offline
and 0 tokens: an index of PDFs, Word, PowerPoint, notebooks and notes (core/contentindex.py) (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="filesearch", safety="safe",
      description="Find a document by what it is ABOUT / what is written inside (PDF, Word, slides, notebook, notes), "
                  "with time words ('last week') and type ('pdf'): 'the pdf about attention I downloaded last week'.")
def find_by_content(query: str) -> str:
    """Find documents by their content.

    Args:
        query: The user's words: the topic, plus type / time words if said.
    """
    from jarvis.core import contentindex
    return contentindex.answer(query)
