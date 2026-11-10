"""github_quick: GitHub in one line: push my work (commit message + one yes + push), a new project (uv + git +
GitHub repo with GITHUB_TOKEN, opened in VS Code), did my build pass (safe; pushing asks first)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="git", safety="safe",
      description="GitHub in one line: push = commit all changes of the open project with a good message and push "
                  "(asks once); new_project = ~/projects/<name> with uv + git (+ a GitHub repo when GITHUB_TOKEN is "
                  "set), opened in VS Code; ci = did the last GitHub Actions build pass.")
def github_quick(action: Literal["push", "new_project", "ci"] = "push", name: str = "", folder: str = "") -> str:
    """GitHub helper.

    Args:
        action: push, new_project or ci.
        name: The new project's name (new_project).
        folder: The project folder (push / ci); empty = the project open in VS Code.
    """
    from jarvis.core import gitquick, safety
    if action == "new_project":
        return gitquick.new_project(name) if name.strip() else "What should the new project be called?"
    if action == "ci":
        return gitquick.ci(folder)
    return gitquick.push(folder, ask=safety.ask)
