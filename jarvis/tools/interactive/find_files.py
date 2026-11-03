"""find_files: find files by name (fdfind) or by content (rg) under a folder, compactly (safe)."""
from __future__ import annotations

import time

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


def name_argv(query: str, limit: int, ftype: str = "f", paths: tuple[str, ...] = (".",), regex: bool = False) -> list[str]:
    # --no-ignore-vcs: also files in git-ignored folders (data/, outputs); junk folders are excluded below
    argv = [_fd_binary(), "--color=never", "--type", ftype, "--max-results", str(limit), "--absolute-path",
            "--no-ignore-vcs", "--ignore-case"]
    for ex in _proc.EXCLUDES:
        argv += ["--exclude", ex]
    if regex:
        pass  # fd's default is regex
    elif any(c in query for c in "*?["):
        argv += ["--glob"]
    else:
        argv += ["--fixed-strings"]
    return argv + ["--", query, *paths]


def fuzzy_search(query: str, bases: list, limit: int, ftype: str) -> list[str]:
    """Find names that are CLOSE to the query (tolerates spacing/underscores and small spelling slips):
    'final rag' / 'final-rag' / 'final drag' all find 'Final_RAG'. Returns paths, best match first."""
    import difflib
    import os
    import re
    toks = re.findall(r"[a-z0-9]+", (query or "").lower())
    if not toks:
        return []
    # 1) tokens with any separators between them ("final rag" -> final[ _.-]*rag), case-insensitive
    pat = r"[\s._/-]*".join(map(re.escape, toks))
    found, _ = search_names(pat, bases, limit, ftype, regex=True)
    if found:
        return found
    # 2) small typos / run-together ("finalrag"): search a prefix of the most distinctive token broadly,
    #    then rank candidates by similarity to the whole query
    key = max(toks, key=len)
    if len(key) < 3:
        return []
    cand, _ = search_names(key, bases, 200, ftype)
    if not cand and len(key) >= 5:  # "finalrag" matches no "finalrag"; search the prefix "fina" and rank
        cand, _ = search_names(key[:4], bases, 400, ftype)
    want = re.sub(r"[^a-z0-9]", "", (query or "").lower())

    def score(p: str) -> float:
        name = re.sub(r"[^a-z0-9]", "", os.path.basename(p.rstrip("/")).lower())
        return difflib.SequenceMatcher(None, want, name).ratio()

    ranked = sorted(((score(p), p) for p in cand), reverse=True)
    return [p for s, p in ranked if s >= 0.6][:limit]


def search_names(query: str, bases: list, limit: int = 20, ftype: str = "f", regex: bool = False) -> tuple[list[str], bool]:
    """Matching paths under all bases in ONE fd run (fd searches them in parallel); (paths, timed_out)."""
    argv = name_argv(query, limit, ftype, tuple(str(b) for b in bases), regex=regex)
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


def _size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _ranked(query: str, path: str, limit: int, order: str) -> str:
    """The biggest / newest files under a folder ('find the biggest files in my downloads' searched for a file
    NAMED 'biggest files', 11-03)."""
    import fnmatch
    import os
    base = _proc.resolve_dir(path) if (path or "").strip() else os.path.expanduser("~")
    pat = query if any(c in query for c in "*?[") else f"*{query}*"
    rows, seen, t0 = [], 0, time.monotonic()
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", "venv", ".venv")]
        for f in files:
            if f.startswith(".") or not fnmatch.fnmatch(f.lower(), pat.lower()):
                continue
            fp = os.path.join(root, f)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            rows.append((st.st_size if order == "biggest" else st.st_mtime, st.st_size, fp))
            seen += 1
        if time.monotonic() - t0 > TIMEOUT:
            break
    if not rows:
        return f"No files like {query!r} under {base}."
    rows.sort(reverse=True)
    what = "biggest" if order == "biggest" else "newest"
    lines = [f"{i}. {_clean(fp)} ({_size(sz)})" for i, (_, sz, fp) in enumerate(rows[:limit], 1)]
    return "\n".join([f"The {what} {min(limit, len(rows))} of {seen} files under {base}:", *lines])


@tool(group="filesearch", safety="safe", description="Find files or folders by name, or text inside files, anywhere on this laptop (home + all disks); or the biggest / newest files in a folder.")
def find_files(query: str, path: str = "", kind: Literal["any", "name", "folder", "content"] = "any",
               limit: int = 20, order: Literal["name", "biggest", "newest"] = "name") -> str:
    """Search files or folders. Without a path it searches the whole laptop: home and every mounted disk.

    Args:
        query: File/folder name, part of it or a glob (*.py) for name/folder; text to look for when kind=content.
            '*' = every file (with order: 'the biggest files in downloads').
        path: Folder to search; loose names work ("project1 then tara"). Empty = whole laptop.
        kind: any (files AND folders, the default), name (files), folder, or content (text inside files).
        limit: Max results (max 50).
        order: name (default); biggest = largest files first, with sizes; newest = most recently changed first.
    """
    if order in ("biggest", "newest") and kind != "content":
        return _ranked(query or "*", path, max(1, min(int(limit or 10), 50)), order)
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
        fuzzy = ""
        if kind == "any":  # search folders first (what people usually mean by "find X"), then files
            folders, late1 = search_names(query, bases, limit, "d")
            files, late2 = search_names(query, bases, limit, "f")
            found = list(dict.fromkeys(folders + [f for f in files if f not in folders]))[:limit]
            late = late1 or late2
        else:
            found, late = search_names(query, bases, limit, "d" if kind == "folder" else "f")
        if not found:  # nothing exact: try a close/fuzzy match (spacing, underscores, small typos)
            for ft in (("d", "f") if kind in ("any", "folder") else ("f",)):
                if hit := fuzzy_search(query, bases, limit, ft):
                    found, fuzzy = hit, f" (closest matches to {query!r})"
                    break
        partial = f" (timed out after {TIMEOUT}s; partial, narrow the path)" if late else ""
        if not found:
            where = "anywhere on your laptop" if len(bases) > 1 else f"under {base}"
            return f"No {what} named like {query!r} {where}. Try a different spelling or part of the name."
        if kind in ("folder", "any"):  # remember the top folder, so "send this folder" works next
            from jarvis.core import focus
            focus.set_path(found[0])
        head = f"{len(found)}{'+' if len(found) == limit else ''} {what} named like {query!r}{fuzzy}{partial}:"
        return "\n".join([head, *(f"{i}. {_clean(f)}" for i, f in enumerate(found, 1))])  # numbered: 'open 4'
        # ('open that 4 number folder' after a search re-searched and opened another one, 11-04)
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
