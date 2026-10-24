"""find_capability: which of the assistant's tools fit a task or problem (0 tokens, word match) (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="self", safety="safe", max_chars=1200,
      description="Find which of your tools can do a task or help with a problem; use it to guide a stuck user.")
def find_capability(need: str) -> str:
    """Search your own tools for a need.

    Args:
        need: What the user wants to do, in a few words (e.g. "create a python project").
    """
    from jarvis.core import selfknow
    hits = selfknow.find_tools(need)
    if not hits:
        return ("no built-in tool matches; options: search the web for how-to steps, or offer to build a small new "
                "tool with toolsmith (ask the user first)")
    return "\n".join(f"- {name} ({group}): {desc}" for group, name, desc in hits)
