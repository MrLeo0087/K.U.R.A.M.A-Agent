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
    if cards:  # one short answer in the owner's words: what it is and the words to say (no internal names)
        top = cards[0]
        if top.direct:  # saying the need runs it: tell exactly that
            out = f"Yes, I can {top.short()}: just say \"{need.strip(' ?.!')}\"" + (f" (or {top.ask()})." if top.ask() else ".")
        else:
            out = f"Yes, I can {top.short()}" + (f": {top.ask()}." if top.ask() else ".")
        return out  # one clear answer (a second "Or ..." was usually off-topic: 'rename a folder' for sending files)
    hits = selfknow.find_tools(need)
    if not hits:
        return ("I can't do that yet. You can teach me your own command (\"when I say X, do Y\"), or I can build a small "
                "new tool for it: say \"make a tool that ...\" (I ask before I make it).")
    return "\n".join(f"- {name} ({group}): {desc}" for group, name, desc in hits)
