"""use_skill (P7c): run a saved toolsmith skill (zero generation tokens).

No longer a tool of its own: the merged tool calls use_skill() (old name kept as an alias)."""
from __future__ import annotations

from jarvis.core import toolsmith


def use_skill(name: str, arg: str = "") -> str:
    """Run a saved skill by name.

    Args:
        name: Skill name (see list_skills).
        arg: Input for the skill, in the format its description asks for.
    """
    return toolsmith.use_skill(name, arg)
