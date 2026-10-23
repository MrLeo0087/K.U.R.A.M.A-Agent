"""make_tool (P7c): offer to build a small tool when no other tool fits. Asks the user first."""
from __future__ import annotations

from jarvis.core import safety, toolsmith
from jarvis.core.registry import tool


@tool(group="toolsmith", safety="safe",
      description="When no other tool can do a real task (calculation, conversion, data, a desktop setting), "
                  "offer to build a small tool for it. It asks the user before making anything.")
def make_tool(task: str) -> str:
    """Build (after the user's yes) and run a small sandboxed tool.

    Args:
        task: What the user wants done, in their words.
    """
    ctx = safety.context()
    return toolsmith.handle(task, user_text=ctx.get("user_text"), lang=ctx.get("lang"))
