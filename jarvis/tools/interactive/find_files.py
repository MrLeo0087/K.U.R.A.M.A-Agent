"""find_files: find files by name (fdfind) or by content (rg) under a folder, compactly (safe)."""
from __future__ import annotations

import shutil
from typing import Literal

from jarvis.core.registry import tool
from jarvis.tools.interactive import _proc

TIMEOUT = 15
LINE_CHARS = 140


def _fd_binary() -> str:
    exe = shutil.which("fdfind") or shutil.which("fd")
    if not exe:
        raise _proc.ProcError("fdfind not found: sudo apt install fd-find")
    return "fdfind" if exe.endswith("fdfind") else exe


def name_argv(query: str, limit: int) -> list[str]:
    argv = [_fd_binary(), "--color=never", "--type", "f", "--max-results", str(limit)]
    for ex in _proc.EXCLUDES:
        argv += ["--exclude", ex]
    argv += ["--glob"] if any(c in query for c in "*?[") else ["--fixed-strings"]
    return argv + ["--", query, "."]


def content_argv(query: str, limit: int) -> list[str]:
    if not shutil.which("rg"):
        raise _proc.ProcError("rg not found: sudo apt install ripgrep")
    argv = ["rg", "--line-number", "--no-heading", "--color=never", "--smart-case", "--fixed-strings",
            "--max-count", "3", "--max-columns", str(LINE_CHARS), "--max-filesize", "2M"]
    for ex in _proc.EXCLUDES:
        argv += ["--glob", f"!{ex}/"]
    return argv + ["--", query, "."]


def _clean(line: str) -> str:
    line = line[2:] if line.startswith("./") else line
    return line if len(line) <= LINE_CHARS else line[: LINE_CHARS - 3] + "..."


@tool(group="files", safety="safe", description="Find files by name (glob or part of name) or by text content under a folder.")
def find_files(query: str, path: str = "~", kind: Literal["name", "content"] = "name", limit: int = 20) -> str:
    """Search files.

    Args:
        query: File name, part of it or a glob (*.py) for kind=name; text to look for when kind=content.
        path: Folder to search (default: home).
        kind: name or content.
        limit: Max results (max 50).
    """
    query = (query or "").strip()
    if not query:
        return "error: give something to search for"
    base = _proc.resolve_dir(path, "~")
    limit = max(1, min(int(limit or 20), 50))
    argv = name_argv(query, limit) if kind == "name" else content_argv(query, limit)
    partial = ""
    try:
        cp = _proc.run(argv, cwd=base, timeout=TIMEOUT)
        if cp.returncode not in (0, 1):
            return f"error: {(cp.stderr or 'search failed').strip()[:200]}"
        out = cp.stdout
    except _proc.ProcError as e:
        if "timed out" not in str(e):
            raise
        out, partial = e.output, f" (timed out after {TIMEOUT}s; partial, narrow the path)"
    hits = [_clean(ln) for ln in out.splitlines() if ln.strip()][:limit]
    if not hits:
        return f"no {'files named' if kind == 'name' else 'matches for'} {query!r} under {base}{partial}"
    head = f"{len(hits)}{'+' if len(hits) == limit else ''} {'files' if kind == 'name' else 'hits'} under {base}{partial}:"
    return _proc.clip("\n".join([head, *hits]))
