"""git_change: commit, or create/switch a branch (confirm: changes the repo; never pushes).

Merged from git_commit and git_branch (their old names still work as aliases).
"""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import alias, tool
from jarvis.tools.interactive.git_branch import git_branch
from jarvis.tools.interactive.git_commit import git_commit


@tool(group="git", safety="confirm",
      description="Git changes: commit staged work (auto message if none), or create / switch a branch. Never pushes.")
def git_change(action: Literal["commit", "new_branch", "switch_branch"] = "commit", repo: str = ".",
               message: str = "", add_all: bool = False, branch: str = "") -> str:
    """Change a git repo.

    Args:
        action: commit, new_branch (create + switch) or switch_branch.
        repo: The repo folder.
        message: Commit message (empty = written automatically).
        add_all: Stage every change before committing.
        branch: Branch name for new_branch / switch_branch.
    """
    if action == "commit":
        return git_commit(message, repo, add_all)
    if not branch:
        return "error: which branch?"
    return git_branch(branch, "create" if action == "new_branch" else "switch", repo)


alias("git_commit", "git_change", action="commit")
alias("git_branch", "git_change", lambda a: {"branch": a.get("name", ""), "repo": a.get("repo", "."),
                                             "action": "new_branch" if a.get("action") == "create" else "switch_branch"})
