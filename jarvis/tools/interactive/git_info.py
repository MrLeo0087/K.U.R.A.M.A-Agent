"""git_info: read-only git status, recent commits or a change summary (safe).

Merged from git_status, git_log and git_diff_summary (their old names still work as aliases).
"""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import alias, tool
from jarvis.tools.interactive.git_diff_summary import git_diff_summary
from jarvis.tools.interactive.git_log import git_log
from jarvis.tools.interactive.git_status import git_status


@tool(group="git", safety="safe",
      description="Git (read-only): status (branch, changed files), log (last N commits) or diff (what changed).")
def git_info(action: Literal["status", "log", "diff"] = "status", repo: str = ".", n: int = 10) -> str:
    """Look at a git repo.

    Args:
        action: status, log or diff.
        repo: The repo folder (loose names work, e.g. "kurama").
        n: How many commits for action=log.
    """
    if action == "log":
        return git_log(repo, n)
    if action == "diff":
        return git_diff_summary(repo)
    return git_status(repo)


alias("git_status", "git_info", action="status")
alias("git_log", "git_info", action="log")
alias("git_diff_summary", "git_info", action="diff")
