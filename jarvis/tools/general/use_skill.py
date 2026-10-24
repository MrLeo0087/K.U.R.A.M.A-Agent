"""use_skill (P7c): run a saved toolsmith skill (zero generation tokens)."""
from __future__ import annotations

from jarvis.core import toolsmith
from jarvis.core.registry import tool


@tool(group="toolsmith", safety="safe", description="Run a saved skill (a small tool KURAMA built earlier).")
def use_skill(name: str, arg: str = "") -> str:
    """Run a saved skill by name.

    Args:
        name: Skill name (see list_skills).
        arg: Input for the skill, in the format its description asks for.
    """
    return toolsmith.use_skill(name, arg)
