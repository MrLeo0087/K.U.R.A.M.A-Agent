"""Looking at changes, three ways (0 tokens unless said):
  diffs     the last build's changed files side by side in VS Code (`code --diff old new`), so each can be kept
            or put back ("reject app.js" = that one file back as it was, a new one to the trash)
  review    your uncommitted changes (git diff) read by the fast model: bugs, risks, missing pieces (1 small call)
  commit    a commit message written from the staged / changed diff (1 small call); committed only after a yes
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from coder.core import run as runmod
from coder.llm import models


def _undo_record() -> tuple[Path, dict] | None:
    d = runmod.last_run()
    if d is None:
        return None
    try:
        return d, json.loads((d / "undo.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def diffs(limit: int = 6) -> str:
    got = _undo_record()
    if got is None:
        return "I haven't changed any files to show."
    _, rec = got
    shown = 0
    for path, backup in list(rec.get("changed", {}).items())[:limit]:
        subprocess.Popen(["code", "--diff", backup, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        shown += 1
    new = [Path(p).name for p in rec.get("created", [])]
    if not shown and not new:
        return "The last build changed nothing."
    return (f"Opened {shown} changed file(s) side by side in VS Code" if shown else "No existing file was changed") + (
        f"; new files: {', '.join(new[:8])}" if new else "") + ". Say 'reject <file>' to put one back."


def reject(name: str) -> str:
    """One file of the last build back as it was (a new one goes to the trash)."""
    got = _undo_record()
    if got is None:
        return "I haven't changed any files."
    d, rec = got
    import re
    m = re.search(r"[\w./-]+\.\w{1,6}\b", name or "")  # 'reject app.js' / 'I don't want the change in main.py'
    name = (m.group(0) if m else name or "").strip().lower().rsplit("/", 1)[-1]
    for path, backup in rec.get("changed", {}).items():
        if Path(path).name.lower() == name or path.lower().endswith("/" + name):
            Path(path).write_bytes(Path(backup).read_bytes())
            del rec["changed"][path]
            (d / "undo.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
            return f"{Path(path).name} is back as it was."
    for path in rec.get("created", []):
        if Path(path).name.lower() == name and Path(path).exists():
            subprocess.run(["gio", "trash", path], capture_output=True, timeout=20)
            rec["created"].remove(path)
            (d / "undo.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
            return f"{Path(path).name} (new) went to the trash."
    return f"The last build didn't touch a file named {name}."


def _git(root: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def review(root: Path) -> str:
    diff = _git(root, "diff", "HEAD") or _git(root, "diff")
    if not diff.strip():
        return "There are no uncommitted changes to review."
    out = models.ask(None, "review", "You review a code change. List real problems only (bugs, crashes, security, "
                     "missing error handling, wrong logic), each as '- file: problem -> fix', most serious first, max "
                     "8; then one line 'Overall: ...'. If it looks good, say so in one line.",
                     diff[:12000], 700)
    return out.strip() or "I couldn't review it right now."


def commit_message(root: Path) -> str:
    diff = _git(root, "diff", "--cached") or _git(root, "diff", "HEAD")
    if not diff.strip():
        return ""
    return models.ask(None, "review", "Write a git commit message for this change: a subject line under 70 "
                      "characters in the imperative, a blank line, then 1-4 short bullet lines of what and why. "
                      "Only the message.", diff[:10000], 250).strip().strip("`")


def commit(root: Path, message: str) -> str:
    if not _git(root, "rev-parse", "--is-inside-work-tree").strip():
        return f"{root.name} isn't a git repository."
    _git(root, "add", "-A")
    r = subprocess.run(["git", "commit", "-m", message], cwd=root, capture_output=True, text=True, timeout=60)
    return ("Committed: " + message.splitlines()[0]) if r.returncode == 0 else ("Commit failed: " + (r.stderr or r.stdout)[-200:])
