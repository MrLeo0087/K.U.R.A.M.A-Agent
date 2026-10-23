"""delete_skill (P7c): remove a saved skill (asks first)."""
from __future__ import annotations

from jarvis.core import toolsmith
from jarvis.core.registry import tool


@tool(group="toolsmith", safety="confirm", description="Delete a saved skill.")
def delete_skill(name: str) -> str:
    """Delete a saved skill by name.

    Args:
        name: Skill name (see list_skills).
    """
    return f"Deleted skill {name}." if toolsmith.delete(name) else f"error: no saved skill called {name!r}"
