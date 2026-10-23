"""list_skills (P7c): the small tools Jarvis built and saved."""
from __future__ import annotations

from jarvis.core import toolsmith
from jarvis.core.registry import tool


@tool(group="toolsmith", safety="safe", description="List the saved skills (small tools Jarvis built earlier).")
def list_skills() -> str:
    """List saved skills with what they do and how often they were used."""
    metas = toolsmith.list_saved()
    if not metas:
        return "No saved skills yet."
    metas.sort(key=lambda m: m.get("last_used", 0), reverse=True)
    return "\n".join(f"{m['name']}: {m.get('summary', '')} (arg: {m.get('arg_hint') or 'none'}; "
                     f"used {m.get('uses', 0)}x{'; asks first' if m.get('sensitive') else ''})" for m in metas)
