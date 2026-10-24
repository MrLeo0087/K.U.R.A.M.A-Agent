"""secrets_audit: scan tracked files and recent git history for API keys, tokens, private keys and
passwords, and check that .env is gitignored and untracked (safe). Secret values are never printed:
each hit shows file:line, the kind and a masked preview (first 4 chars + ****).

No longer a tool of its own: the merged tool calls secrets_audit() (old name kept as an alias)."""
from __future__ import annotations

import os
from pathlib import Path

from jarvis.tools.interactive import _proc, _secrets

MAX_FILE_BYTES = 1_000_000
MAX_HISTORY_CHARS = 30_000_000
MAX_SHOWN = 10
SKIP_SUFFIXES = (".lock", ".min.js", ".map", ".svg", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff",
                 ".woff2", ".ttf", ".zip", ".gz", ".whl", ".pyc", ".so", ".onnx", ".db", ".sqlite", ".wav", ".mp3")
HISTORY_EXCLUDES = (":(exclude)*.lock", ":(exclude)package-lock.json", ":(exclude)*.min.js", ":(exclude)*.svg")


def _read_text(p: Path) -> str | None:
    try:
        if p.stat().st_size > MAX_FILE_BYTES or p.suffix.lower() in SKIP_SUFFIXES:
            return None
        data = p.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", "replace")


def _files(root: Path, is_git: bool) -> list[str]:
    if is_git:
        return [f for f in _proc.git(["ls-files", "-z"], root, timeout=20).split("\0") if f]
    out = []
    for d, dirs, names in os.walk(root):
        dirs[:] = [x for x in dirs if x not in _proc.EXCLUDES]
        out += [os.path.relpath(os.path.join(d, n), root) for n in names]
        if len(out) > 20000:
            break
    return out


def scan_tree(root: Path, is_git: bool) -> tuple[list[_secrets.Finding], int]:
    found: list[_secrets.Finding] = []
    files = _files(root, is_git)
    for rel in files:
        text = _read_text(root / rel)
        if text:
            found.extend(_secrets.scan_text(text, rel))
    return found, len(files)


def scan_history(root: Path, commits: int) -> tuple[list[_secrets.Finding], int]:
    """Added lines of the last N commits (all branches)."""
    try:
        diff = _proc.git(["log", "--all", "-p", f"-n{int(commits)}", "--no-color", "--unified=0",
                          "--no-ext-diff", "--format=commit %H", "--", ".", *HISTORY_EXCLUDES], root, timeout=60)
    except _proc.ProcError as e:
        if "does not have any commits" in str(e) or "bad default revision" in str(e):
            return [], 0
        raise
    n = diff.count("\ncommit ") + diff.startswith("commit ")
    return _secrets.scan_diff(diff[:MAX_HISTORY_CHARS], limit=500), n


def env_checks(root: Path, is_git: bool) -> list[str]:
    """Problems with .env handling ([] = fine)."""
    notes: list[str] = []
    if not is_git:
        return notes
    tracked = [f for f in _proc.git(["ls-files"], root).splitlines()
               if Path(f).name.startswith(".env") and not f.endswith((".example", ".sample", ".template", ".dist"))]
    if tracked:
        notes.append(f"TRACKED env file(s): {', '.join(tracked[:3])} (git rm --cached, then rotate keys)")
    cp = _proc.run(["git", "-C", str(root), "check-ignore", "--no-index", "-q", ".env"], timeout=10)
    if cp.returncode != 0:
        notes.append(".env is NOT in .gitignore")
    if _proc.git(["log", "--all", "--format=%h", "-n1", "--", ".env"], root).strip():
        notes.append(".env appears in git history (rotate those keys)")
    return notes


def report(root: Path, tree: list, history: list, nfiles: int, ncommits: int, env: list[str]) -> str:
    seen = {f.fingerprint for f in tree}
    hist_only = []
    for f in history:
        if f.fingerprint not in seen:
            seen.add(f.fingerprint)
            hist_only.append(f)
    total = len(tree) + len(hist_only)
    head = (f"secrets_audit {root.name}: {total} possible secret(s) "
            f"({len(tree)} in {nfiles} files, {len(hist_only)} only in history of {ncommits} commits)")
    lines = [head]
    for f in (tree + hist_only)[:MAX_SHOWN]:
        lines.append("- " + f.render())
    if total > MAX_SHOWN:
        lines.append(f"- ...and {total - MAX_SHOWN} more")
    env_ok = ".env ignored and untracked" if (root / ".env").exists() else "no .env file"
    lines.append("env: " + ("; ".join(env) if env else env_ok))
    if total:
        lines.append("fix: move values to .env, rotate any real key; add '# secrets: ignore' to false positives")
    return _proc.clip("\n".join(lines))


def secrets_audit(repo: str = ".", commits: int = 200, history: bool = True) -> str:
    """Audit a repository for committed secrets (values are always masked).

    Args:
        repo: Repository or folder (default: current folder).
        commits: How many recent commits of history to scan.
        history: Also scan git history (not just current files).
    """
    base = _proc.resolve_dir(repo)
    try:
        root, is_git = _proc.repo_root(str(base)), True
    except _proc.ProcError:
        root, is_git = base, False
    tree, nfiles = scan_tree(root, is_git)
    hist, ncommits = scan_history(root, max(1, min(int(commits or 200), 5000))) if (is_git and history) else ([], 0)
    return report(root, tree, hist, nfiles, ncommits, env_checks(root, is_git))
