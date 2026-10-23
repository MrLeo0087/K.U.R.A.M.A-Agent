"""token_usage: LLM tokens, calls, budget %, fast-path savings, STT seconds and cost for a period (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="usage", safety="safe", description="Report LLM token usage, budget, fast-path savings, speech seconds and API cost.")
def token_usage(period: Literal["today", "week", "month"] = "today") -> str:
    """Token usage report.

    Args:
        period: "today", "week" (last 7 days) or "month".
    """
    from jarvis.core import usage

    return usage.report(period or "today")
