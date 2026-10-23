"""git_branch: create (and switch to) or switch to a git branch (confirm). Never deletes or forces."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool
from jarvis.tools.interactive import _proc


@tool(group="git", safety="confirm", description="Create a new git branch (and switch to it) or switch to an existing one.")
def git_branch(name: str, action: Literal["create", "switch"] = "switch", repo: str = ".") -> str:
    """Create or switch a branch.

    Args:
        name: Branch name.
        action: create (new branch, then switch) or switch (existing branch).
        repo: Repository folder (default: current folder).
    """
    root = _proc.repo_root(repo)
    name = (name or "").strip()
    if not name or name.startswith("-"):
        return "error: give a valid branch name"
    _proc.git(["check-ref-format", "--branch", name], root)
    if action == "create":
        _proc.git(["switch", "-c", name], root)
        return f"created and switched to branch {name} in {root.name}"
    _proc.git(["switch", name], root)
    return f"switched to branch {name} in {root.name}"
