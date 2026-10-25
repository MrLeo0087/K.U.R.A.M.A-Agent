"""find_files: find files by name (fdfind) or by content (rg) under a folder, compactly (safe)."""
from __future__ import annotations

import shutil
from typing import Literal

from jarvis.core.registry import tool
from jarvis.tools.interactive import _proc

TIMEOUT = 25
LINE_CHARS = 140


def _fd_binary() -> str:
    exe = shutil.which("fdfind") or shutil.which("fd")
    if not exe:
        raise _proc.ProcError("fdfind not found: sudo apt install fd-find")
    return "fdfind" if exe.endswith("fdfind") else exe


def name_argv(query: str, limit: int, ftype: str = "f", paths: tuple[str, ...] = (".",)) -> list[str]:
    # --no-ignore-vcs: also files in git-ignored folders (data/, outputs); junk folders are excluded below
    argv = [_fd_binary(), "--color=never", "--type", ftype, "--max-results", str(limit), "--absolute-path",
            "--no-ignore-vcs"]
    for ex in _proc.EXCLUDES:
        argv += ["--exclude", ex]
    argv += ["--glob"] if any(c in query for c in "*?[") else ["--fixed-strings"]
    return argv + ["--", query, *paths]


def search_names(query: str, bases: list, limit: int = 20, ftype: str = "f") -> tuple[list[str], bool]:
    """Matching paths under all bases in ONE fd run (fd searches them in parallel); (paths, timed_out)."""
    argv = name_argv(query, limit, ftype, tuple(str(b) for b in bases))
    try:
        cp = _proc.run(argv, cwd=str(bases[0]), timeout=TIMEOUT)
        if cp.returncode not in (0, 1):
            raise _proc.ProcError((cp.stderr or "search failed").strip()[:200])
        out, partial = cp.stdout, False
    except _proc.ProcError as e:
        if "timed out" not in str(e):
            raise
        out, partial = e.output or "", True
    return list(dict.fromkeys(ln.strip() for ln in out.splitlines() if ln.strip()))[:limit], partial


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


@tool(group="filesearch", safety="safe", description="Find files or folders by name, or text inside files, anywhere on this laptop (home + all disks).")
def find_files(query: str, path: str = "", kind: Literal["any", "name", "folder", "content"] = "any",
               limit: int = 20) -> str:
    """Search files or folders. Without a path it searches the whole laptop: home and every mounted disk.

    Args:
        query: File/folder name, part of it or a glob (*.py) for name/folder; text to look for when kind=content.
        path: Folder to search; loose names work ("project1 then tara"). Empty = whole laptop.
        kind: any (files AND folders, the default), name (files), folder, or content (text inside files).
        limit: Max results (max 50).
    """
    query = (query or "").strip()
    if not query:
        return "error: give something to search for"
    from jarvis.core.paths import all_disks
    bases = [_proc.resolve_dir(path)] if (path or "").strip() else all_disks()
    base = bases[0] if len(bases) == 1 else " and ".join(str(b) for b in bases)
    limit = max(1, min(int(limit or 20), 50))
    if not (path or "").strip():
        limit = 200  # whole-laptop search: the full list goes to the Workspace card, the LLM sees the top
    what = {"any": "files/folders", "name": "files", "folder": "folders", "content": "hits"}[kind]
    if kind != "content":
        if kind == "any":  # search folders first (what people usually mean by "find X"), then files
            folders, late1 = search_names(query, bases, limit, "d")
            files, late2 = search_names(query, bases, limit, "f")
            found = list(dict.fromkeys(folders + [f for f in files if f not in folders]))[:limit]
            late = late1 or late2
        else:
            found, late = search_names(query, bases, limit, "d" if kind == "folder" else "f")
        partial = f" (timed out after {TIMEOUT}s; partial, narrow the path)" if late else ""
        if not found:
            return f"no {what} matching {query!r} under {base}{partial}"
        if kind in ("folder", "any"):  # remember the top folder, so "send this folder" works next
            from jarvis.core import focus
            focus.set_path(found[0])
        head = f"{len(found)}{'+' if len(found) == limit else ''} {what} named like {query!r}{partial}:"
        return "\n".join([head, *(_clean(f) for f in found)])
    argv = content_argv(query, limit)
    out, partial = "", ""
    for b in bases:
        try:
            cp = _proc.run(argv, cwd=b, timeout=TIMEOUT)
            if cp.returncode not in (0, 1):
                return f"error: {(cp.stderr or 'search failed').strip()[:200]}"
            out += cp.stdout
        except _proc.ProcError as e:
            if "timed out" not in str(e):
                raise
            out, partial = out + (e.output or ""), f" (timed out after {TIMEOUT}s; partial, narrow the path)"
        out = "\n".join(f"{b}/{ln}" if ln and not ln.startswith("/") else ln for ln in out.splitlines())
    hits = list(dict.fromkeys(_clean(ln) for ln in out.splitlines() if ln.strip()))[:limit]
    if not hits:
        return f"no {what} matching {query!r} under {base}{partial}"
    head = f"{len(hits)}{'+' if len(hits) == limit else ''} {what} under {base}{partial}:"
    return _proc.clip("\n".join([head, *hits]))
