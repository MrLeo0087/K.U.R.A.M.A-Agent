"""git_diff_summary: `git diff --stat` for staged and unstaged changes (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool
from jarvis.tools.interactive import _proc


def _stat(root, staged: bool) -> str:
    args = ["diff", "--stat=100", "--stat-count=12"] + (["--cached"] if staged else [])
    return _proc.git(args, root).rstrip()


@tool(group="git", safety="safe", description="Summarize git changes (diff --stat) for staged and unstaged files.")
def git_diff_summary(repo: str = ".") -> str:
    """Diff summary.

    Args:
        repo: Repository folder (default: current folder).
    """
    root = _proc.repo_root(repo)
    staged, unstaged = _stat(root, True), _stat(root, False)
    if not staged and not unstaged:
        return f"{root.name}: no changes to tracked files"
    out = []
    if staged:
        out.append("staged:\n" + staged)
    if unstaged:
        out.append("unstaged:\n" + unstaged)
    return _proc.clip("\n".join(out))
