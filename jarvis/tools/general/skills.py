"""skills: list, run or delete the tools KURAMA built and saved (safe; deleting asks first).

Merged from list_skills, use_skill and delete_skill (their old names still work as aliases).
"""
from __future__ import annotations

from typing import Literal

from jarvis.core import safety
from jarvis.core.registry import alias, tool
from jarvis.tools.general.delete_skill import delete_skill
from jarvis.tools.general.list_skills import list_skills
from jarvis.tools.general.use_skill import use_skill


@tool(group="toolsmith", safety="safe",
      description="Saved tools KURAMA built earlier: list them, run one by name, or delete one.")
def skills(action: Literal["list", "use", "delete"] = "list", name: str = "", arg: str = "") -> str:
    """Saved skills.

    Args:
        action: list = all saved tools, use = run `name` with `arg`, delete = remove `name` (asks first).
        name: The saved tool's name.
        arg: The input for the saved tool (action=use).
    """
    if action == "use":
        return use_skill(name, arg)
    if action == "delete":
        if not safety.ask(f"Delete the saved tool {name!r}?"):
            return "The user said no, so nothing was deleted."
        return delete_skill(name)
    return list_skills()


alias("list_skills", "skills", action="list")
alias("use_skill", "skills", action="use")
alias("delete_skill", "skills", action="delete")
