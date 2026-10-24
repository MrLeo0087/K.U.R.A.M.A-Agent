"""git_status: branch, ahead/behind and a compact changed-files summary of a git repo (safe).

No longer a tool of its own: the merged tool calls git_status() (old name kept as an alias)."""
from __future__ import annotations

import re

from jarvis.tools.interactive import _proc

MAX_FILES = 10


def summarize(porcelain: str) -> tuple[str, dict[str, int], list[str]]:
    """Parse `git status --porcelain=v1 -b` -> (branch line, counts, file lines)."""
    lines = porcelain.splitlines()
    head = lines[0][3:] if lines and lines[0].startswith("## ") else "?"
    counts = {"staged": 0, "modified": 0, "untracked": 0, "conflicts": 0}
    files: list[str] = []
    for ln in lines[1:]:
        if len(ln) < 4:
            continue
        x, y, path = ln[0], ln[1], ln[3:]
        if x == "?":
            counts["untracked"] += 1
        elif "U" in (x, y) or (x, y) in (("A", "A"), ("D", "D")):
            counts["conflicts"] += 1
        else:
            counts["staged"] += x not in " "
            counts["modified"] += y not in " "
        files.append(f"{(x + y).strip() or '?'} {path}")
    return head, counts, files


def _branch_text(head: str) -> str:
    if head.startswith("No commits yet on "):
        return f"{head[len('No commits yet on '):]} (no commits yet)"
    m = re.match(r"(\S+?)(?:\.\.\.(\S+))?(?: \[(.*)\])?$", head)
    if not m:
        return head
    branch, upstream, track = m.groups()
    if not upstream:
        return f"{branch} (no upstream)"
    ahead = re.search(r"ahead (\d+)", track or "")
    behind = re.search(r"behind (\d+)", track or "")
    return (f"{branch} vs {upstream}: ahead {ahead.group(1) if ahead else 0}, "
            f"behind {behind.group(1) if behind else 0}")


def git_status(repo: str = ".") -> str:
    """Show git status.

    Args:
        repo: Repository folder (default: current folder).
    """
    root = _proc.repo_root(repo)
    head, counts, files = summarize(_proc.git(["status", "--porcelain=v1", "-b"], root))
    branches = _proc.git(["branch", "--format=%(refname:short)"], root).split()
    parts = [f"{n} {k}" for k, n in counts.items() if n]
    out = [f"{root.name} on {_branch_text(head)}", ", ".join(parts) if parts else "working tree clean"]
    if len(branches) > 1:
        out.append("branches: " + ", ".join(branches[:6]) + (" ..." if len(branches) > 6 else ""))
    out += files[:MAX_FILES]
    if len(files) > MAX_FILES:
        out.append(f"... +{len(files) - MAX_FILES} more")
    return _proc.clip("\n".join(out))
