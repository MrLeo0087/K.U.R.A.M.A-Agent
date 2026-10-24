"""repo_hygiene: suggestions to tidy a git repo (safe, read-only): missing README/LICENSE/.gitignore
entries, tracked junk (__pycache__, venv, .env, .pyc), big or binary files, merged/stale branches,
TODO/FIXME count and empty folders. Nothing is changed.

No longer a tool of its own: the merged tool calls repo_hygiene() (old name kept as an alias)."""
from __future__ import annotations

import os
import time
from pathlib import Path

from jarvis.tools.interactive import _proc

BIG_BYTES = 1024 * 1024
STALE_DAYS = 90
BINARY_EXT = (".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".whl", ".exe", ".dll", ".so", ".dylib", ".bin",
              ".pt", ".pth", ".ckpt", ".safetensors", ".onnx", ".h5", ".pkl", ".pickle", ".npy", ".npz",
              ".db", ".sqlite", ".sqlite3", ".mp4", ".mov", ".avi", ".wav", ".mp3", ".flac", ".iso", ".parquet")
JUNK_PARTS = ("__pycache__", "venv", ".venv", "node_modules", ".pytest_cache", ".mypy_cache", ".ruff_cache",
              ".ipynb_checkpoints", ".idea")
JUNK_NAMES = (".DS_Store", "Thumbs.db", ".env")
# path that should be ignored -> .gitignore entry to suggest (Python projects)
IGNORE_PROBES = {"__pycache__/x.pyc": "__pycache__/", ".env": ".env", "venv/bin/python": "venv/",
                 ".venv/bin/python": ".venv/", ".pytest_cache/x": ".pytest_cache/", "pkg.egg-info/PKG-INFO": "*.egg-info/"}
PROTECTED = ("main", "master", "develop", "dev", "trunk")


def _short(items: list[str], n: int = 4) -> str:
    return ", ".join(items[:n]) + (f" +{len(items) - n}" if len(items) > n else "")


def missing_docs(root: Path, tracked: list[str]) -> list[str]:
    top = {Path(f).parts[0].lower() for f in tracked}
    out = []
    if not any(t.startswith("readme") for t in top):
        out.append("README")
    if not any(t.startswith(("license", "licence", "copying")) for t in top):
        out.append("LICENSE")
    return out


def gitignore_gaps(root: Path, tracked: list[str]) -> list[str]:
    if not (root / ".gitignore").exists():
        return [".gitignore (missing)"]
    if not any(f.endswith(".py") for f in tracked):
        return []
    cp = _proc.run(["git", "-C", str(root), "check-ignore", "--no-index", *IGNORE_PROBES], timeout=10)
    ignored = set(cp.stdout.split())
    gaps = [entry for probe, entry in IGNORE_PROBES.items() if probe not in ignored]
    if "venv/" in gaps and ".venv/" not in gaps or ".venv/" in gaps and "venv/" not in gaps:
        gaps = [g for g in gaps if g not in ("venv/", ".venv/")]  # one of the two is enough
    return gaps


def tracked_junk(tracked: list[str]) -> list[str]:
    junk = []
    for f in tracked:
        parts = Path(f).parts
        if any(p in JUNK_PARTS for p in parts[:-1]) or parts[-1] in JUNK_NAMES or f.endswith((".pyc", ".pyo")):
            junk.append(f)
    return junk


def big_files(root: Path, tracked: list[str]) -> list[str]:
    hits: list[tuple[int, str]] = []
    for f in tracked:
        try:
            size = (root / f).stat().st_size
        except OSError:
            continue
        if size > BIG_BYTES or f.lower().endswith(BINARY_EXT):
            hits.append((size, f))
    return [f"{f} ({s / 1048576:.1f} MB)" for s, f in sorted(hits, reverse=True)]


def branches(root: Path) -> tuple[list[str], list[str]]:
    current = _proc.git(["rev-parse", "--abbrev-ref", "HEAD"], root, ok_codes=(0, 128)).strip()
    merged = [b.strip(" *+") for b in _proc.git(["branch", "--merged", "HEAD"], root, ok_codes=(0, 129)).splitlines()]
    merged = [b for b in merged if b and b != current and b not in PROTECTED and not b.startswith("(")]
    stale, now = [], time.time()
    for ln in _proc.git(["for-each-ref", "--format=%(refname:short) %(committerdate:unix)", "refs/heads"], root).splitlines():
        name, _, ts = ln.rpartition(" ")
        if name and name != current and ts.isdigit() and now - int(ts) > STALE_DAYS * 86400 and name not in merged:
            stale.append(name)
    return merged, stale


def todo_count(root: Path) -> int:
    out = _proc.git(["grep", "-I", "-c", "-w", "-e", "TODO", "-e", "FIXME", "-e", "HACK", "-e", "XXX"],
                    root, ok_codes=(0, 1), timeout=20)
    return sum(int(ln.rsplit(":", 1)[1]) for ln in out.splitlines() if ln.rsplit(":", 1)[-1].isdigit())


def empty_dirs(root: Path, limit: int = 20000) -> list[str]:
    out, n = [], 0
    for d, dirs, names in os.walk(root):
        dirs[:] = [x for x in dirs if x not in _proc.EXCLUDES and x not in JUNK_PARTS and x != "data"]
        n += 1
        if not dirs and not names and Path(d) != root:
            out.append(os.path.relpath(d, root))
        if n > limit:
            break
    return out


def repo_hygiene(repo: str = ".") -> str:
    """Suggest hygiene fixes for a git repository (changes nothing).

    Args:
        repo: Repository folder (default: current folder).
    """
    root = _proc.repo_root(repo)
    tracked = [f for f in _proc.git(["ls-files", "-z"], root, timeout=20).split("\0") if f]
    tips: list[str] = []
    if docs := missing_docs(root, tracked):
        tips.append(f"add {' and '.join(docs)}")
    if gaps := gitignore_gaps(root, tracked):
        tips.append(f".gitignore: add {_short(gaps, 5)}")
    if junk := tracked_junk(tracked):
        tips.append(f"untrack junk (git rm --cached): {_short(junk, 3)}")
    if big := big_files(root, tracked):
        tips.append(f"big/binary files tracked (use LFS or ignore): {_short(big, 3)}")
    merged, stale = branches(root)
    if merged:
        tips.append(f"merged branches to delete: {_short(merged)}")
    if stale:
        tips.append(f"stale branches (>{STALE_DAYS} days): {_short(stale)}")
    todos = todo_count(root)
    if empties := empty_dirs(root):
        tips.append(f"empty folders: {_short(empties, 3)}")
    head = f"repo_hygiene {root.name}: {len(tracked)} tracked files, {todos} TODO/FIXME"
    if not tips:
        return head + "\nlooks tidy, no suggestions"
    return _proc.clip("\n".join([head] + [f"- {t}" for t in tips]))
