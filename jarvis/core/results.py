"""Typed tool results: a tool can return `Reply(text, paths=[...], ...)` instead of a plain string.

A Reply IS a str (LangChain, the LLM, logs and every old caller see the same text), and it also carries the exact
data behind the words, so code that acts on a result ('open the second one', 'send it') reads the data instead of
parsing the sentence back with regexes (a path cut to 140 characters for display could never be opened again).
"""
from __future__ import annotations

from typing import Any


class Reply(str):
    """Tool text plus structured data. `Reply("3 folders...", paths=[...]).data == {"paths": [...]}`."""

    data: dict[str, Any]

    def __new__(cls, text: str, **data: Any) -> "Reply":
        obj = super().__new__(cls, text)
        obj.data = {k: v for k, v in data.items() if v is not None}
        return obj


def data_of(result: Any) -> dict[str, Any]:
    """The structured data a tool returned ({} for a plain string or anything else)."""
    d = getattr(result, "data", None)
    return dict(d) if isinstance(d, dict) else {}
