"""git_commit: commit staged changes with a given or auto-generated message (confirm). Never pushes."""
from __future__ import annotations

import logging
import re

from jarvis.core.registry import tool
from jarvis.tools.interactive import _proc

log = logging.getLogger("jarvis.tools.git_commit")

DIFF_CHARS = 1500  # token guard: only --stat plus this much diff goes to the fast model
NOISY = (":(exclude)*.lock", ":(exclude)*.min.js", ":(exclude)*.ipynb", ":(exclude)package-lock.json")
PROMPT = ("Write one git commit message line for this change: imperative mood, at most 60 "
          "characters, no quotes, no trailing period. Reply with the line only.")


def _fallback_message(stat: str) -> str:
    files = [ln.split("|")[0].strip() for ln in stat.splitlines() if "|" in ln]
    names = ", ".join(f.rsplit("/", 1)[-1] for f in files[:3])
    return f"Update {names}" + (f" and {len(files) - 3} more" if len(files) > 3 else "") if files else "Update files"


def auto_message(stat: str, diff: str) -> str:
    """Short message from the staged stat + a clipped diff on the fast tier; falls back to file names."""
    from jarvis.core import llm

    user = f"diff --stat:\n{stat[:600]}\n\ndiff (clipped):\n{diff[:DIFF_CHARS]}"
    try:
        reply = llm.chat([{"role": "system", "content": PROMPT}, {"role": "user", "content": user}],
                         tier="fast", purpose="git_commit_msg", max_tokens=200, temperature=0.2)
        line = next((ln for ln in str(reply).splitlines() if ln.strip()), "")
        line = re.sub(r"^(?:commit message:\s*)", "", line.strip().strip("`\"'"), flags=re.I).rstrip(".")
        if line:
            return line[:72]
    except Exception as e:  # no LLM: still commit with a plain message
        log.warning("commit message generation failed: %s", e)
    return _fallback_message(stat)


@tool(group="git", safety="confirm",
      description="Commit staged git changes; auto-writes a short message if none is given. Never pushes.")
def git_commit(message: str = "", repo: str = ".", add_all: bool = False) -> str:
    """Commit staged changes.

    Args:
        message: Commit message (empty = generate one from the staged diff).
        repo: Repository folder (default: current folder).
        add_all: Stage all changes (git add -A) first.
    """
    root = _proc.repo_root(repo)
    if add_all:
        _proc.git(["add", "-A"], root)
    stat = _proc.git(["diff", "--cached", "--stat=80"], root).strip()
    if not stat:
        return f"nothing staged to commit in {root.name} (stage files first or use add_all)"
    msg = message.strip()
    if not msg:
        diff = _proc.git(["diff", "--cached", "--unified=1", "--no-color", "--", ".", *NOISY], root)
        msg = auto_message(stat, diff)
    _proc.git(["commit", "-q", "-m", msg], root, timeout=30)
    sha = _proc.git(["rev-parse", "--short", "HEAD"], root).strip()
    summary = stat.splitlines()[-1].strip()
    return f"committed {sha} in {root.name}: {msg} ({summary}). Not pushed."
