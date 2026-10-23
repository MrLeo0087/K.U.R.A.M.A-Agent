"""ask_knowledge: answer a question about the user's code/notes from the top indexed chunks (safe).
Token-cheap: <= config.ASK_K chunks, <= config.ASK_CONTEXT_CHARS of context, fast tier, and a
normalized-question answer cache (cleared on reindex) so repeated questions cost 0 tokens."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="knowledge", safety="safe", description="Answer a question about the user's own code, docs or notes (also 'what is this project about'), citing file paths.")
def ask_knowledge(question: str) -> str:
    """Ask the codebase / notes.

    Args:
        question: The question, e.g. "how does the fast path work?".
    """
    from jarvis.core import llm, memory
    from jarvis.tools.general.search_knowledge import empty_index_reply

    question = (question or "").strip()
    if not question:
        return "error: ask a question"
    if memory.get_index().count_chunks() == 0 and not memory.is_overview_question(question):
        return empty_index_reply()
    try:
        res = memory.ask(question)
    except llm.LLMError as e:
        return f"error: the model is unavailable ({e})"
    if not res["answer"]:
        return "I found nothing about that in your indexed files."
    return res["answer"]
