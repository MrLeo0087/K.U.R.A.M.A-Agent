"""delete_skill (P7c): remove a saved skill (asks first).

No longer a tool of its own: the merged tool calls delete_skill() (old name kept as an alias)."""
from __future__ import annotations

from jarvis.core import toolsmith


def delete_skill(name: str) -> str:
    """Delete a saved skill by name.

    Args:
        name: Skill name (see list_skills).
    """
    return f"Deleted skill {name}." if toolsmith.delete(name) else f"error: no saved skill called {name!r}"
