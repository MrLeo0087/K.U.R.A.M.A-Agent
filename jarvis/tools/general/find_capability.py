"""find_capability: which of the assistant's tools fit a task or problem: by meaning (local model, core/selfindex.py),
else by word match; with a way to ask for each (0 tokens) (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="self", safety="safe", max_chars=1200,
      description="Find which of your tools can do a task or help with a problem; use it to guide a stuck user.")
def find_capability(need: str) -> str:
    """Search your own tools for a need.

    Args:
        need: What the user wants to do, in a few words (e.g. "create a python project").
    """
    from jarvis.core import selfindex, selfknow
    cards = selfindex.by_meaning(need, 4)
    if cards:  # in the owner's words: what it is and how to ask (no internal names)
        top, rest = cards[0], cards[1:]
        out = [f"Yes, I can help with that: {top.what}" + (f' Say: "{top.say[0]}".' if top.say else "")]
        out += [f"Also: {c.what}" + (f' ("{c.say[0]}")' if c.say else "") for c in rest[:2]]
        return "\n".join(out)
    hits = selfknow.find_tools(need)
    if not hits:
        return ("no built-in tool matches; options: search the web for how-to steps, the owner's own command ('when I "
                "say X, do Y'), or build a small new tool with make_tool (it asks the user itself with a Yes/No box: "
                "don't ask in chat first)")
    return "\n".join(f"- {name} ({group}): {desc}" for group, name, desc in hits)
