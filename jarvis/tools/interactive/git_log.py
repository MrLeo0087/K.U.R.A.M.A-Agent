"""git_log: the last N commits of a repo, one line each (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool
from jarvis.tools.interactive import _proc


@tool(group="git", safety="safe", description="Show the last N git commits, one line each.")
def git_log(repo: str = ".", n: int = 10) -> str:
    """Recent commits.

    Args:
        repo: Repository folder (default: current folder).
        n: How many commits (max 30).
    """
    root = _proc.repo_root(repo)
    n = max(1, min(int(n or 10), 30))
    try:
        out = _proc.git(["log", f"-n{n}", "--date=short", "--pretty=format:%h %ad %s"], root)
    except _proc.ProcError as e:
        if "does not have any commits" in str(e):
            return f"{root.name}: no commits yet"
        raise
    return _proc.clip(out.strip() or f"{root.name}: no commits yet")
