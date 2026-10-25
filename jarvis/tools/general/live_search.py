"""live_search: real-time answers — live/last/next game scores (ESPN), minutes-fresh news (Google News), or a short
answer to a current-events question built only from fresh sources (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="web", safety="safe",
      description="REAL-TIME info: live/latest match scores, results with scorers and next fixtures for any team; "
                  "latest news on a topic; or an up-to-date answer to a current-events question (who won, what "
                  "happened today). Prefer this over web_search for anything recent.")
def live_search(query: str, kind: Literal["auto", "sports", "news", "answer"] = "auto") -> str:
    """Real-time search.

    Args:
        query: The question or topic, e.g. "Inter Miami result today", "news about Nepal".
        kind: auto (decide), sports (a team's live/last/next game), news (headlines), answer (fresh short answer).
    """
    from jarvis.core import live
    q = " ".join((query or "").split())
    if not q:
        return "error: what should I look up?"
    if kind == "answer":
        return live.answer(q)
    return live.search(q, kind)
