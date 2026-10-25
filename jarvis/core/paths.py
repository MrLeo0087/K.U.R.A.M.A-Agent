"""Smart path resolution for spoken/loose paths ("project1 then tara folder", "tara source code in project1",
"/media/leo/project1/tara"). Used by the file, search and Telegram tools when a path doesn't exist as written.

No LLM: aliases (config.PATH_ALIASES) + case-insensitive/fuzzy folder matching with a small bounded walk.
"""
from __future__ import annotations

import difflib
import os
import re
from collections import deque
from pathlib import Path

from jarvis.core import config

_FILLER = re.compile(r"\b(?:the|my|a|folder|folders|directory|dir|file|called|named|from|go to|open|inside|"
                     r"located|path|of|please)\b", re.I)
_SPLIT = re.compile(r"\s*(?:/|\\|>|,|\bthen\b|\band then\b|\binside\b|\bunder\b|\bwithin\b)\s*", re.I)
_SKIP = {"node_modules", "venv", ".venv", "__pycache__", ".git", "site-packages", ".cache"}
MAX_SCAN = 6000  # directory entries looked at per search (keeps it fast)


def norm(s: str) -> str:
    return re.sub(r"[\s_\-.]+", "", s.lower())


def roots() -> list[Path]:
    return [Path(p).expanduser() for p in config.SEARCH_ROOTS if Path(p).expanduser().is_dir()]


_DATA_FS = {"ext4", "ext3", "ext2", "btrfs", "xfs", "f2fs", "fuseblk", "ntfs", "ntfs3", "exfat", "vfat"}


def all_disks() -> list[Path]:
    """Home + every data disk that is mounted now (/media/<user>/*, /mnt/*, ...): "my whole laptop" for file
    search and for sending files. System mounts (/, /boot, snaps) are left out; / itself is covered by home."""
    out = [Path.home()]
    try:
        import psutil

        for part in psutil.disk_partitions(all=False):
            mp = Path(part.mountpoint)
            if part.fstype.lower() in _DATA_FS and str(mp).startswith(("/media/", "/mnt/", "/run/media/")):
                out.append(mp)
    except Exception:
        pass
    out += [r for r in roots() if r not in out]
    return [p for p in dict.fromkeys(out) if p.is_dir()]


def _score(name: str, want: str) -> float:
    a, b = norm(name), norm(want)
    if not b:
        return 0.0
    if a == b:
        return 1.0
    if a.startswith(b) or b.startswith(a):
        return 0.9 if min(len(a), len(b)) >= 3 else 0.0
    if b in a:
        return 0.8
    return difflib.SequenceMatcher(None, a, b).ratio()


def find_child(base: Path, want: str, depth: int = 2, dirs_only: bool = True) -> Path | None:
    """Best match for `want` under base, breadth-first up to `depth` levels (exact names win)."""
    best: tuple[float, int, Path] | None = None
    q: deque[tuple[Path, int]] = deque([(base, 1)])
    seen = 0
    while q and seen < MAX_SCAN:
        d, lvl = q.popleft()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            seen += 1
            if e.name.startswith(".") or e.name in _SKIP:
                continue
            is_dir = e.is_dir(follow_symlinks=False)
            if dirs_only and not is_dir:
                continue
            s = _score(e.name, want)
            if s >= config.PATH_MATCH_MIN and (best is None or (s, -lvl) > (best[0], best[1])):
                best = (s, -lvl, Path(e.path))
            if is_dir and lvl < depth:
                q.append((Path(e.path), lvl + 1))
        if best and best[0] == 1.0 and -best[1] == lvl:
            break
    return best[2] if best else None


def find_children(base: Path, want: str, depth: int = 2, dirs_only: bool = True, k: int = 4,
                  min_score: float | None = None) -> list[Path]:
    """Up to k good matches under base (best first), for backtracking over ambiguous names."""
    found: list[tuple[float, int, Path]] = []
    q: deque[tuple[Path, int]] = deque([(base, 1)])
    seen = 0
    while q and seen < MAX_SCAN:
        d, lvl = q.popleft()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            seen += 1
            if e.name.startswith(".") or e.name in _SKIP:
                continue
            is_dir = e.is_dir(follow_symlinks=False)
            if (not dirs_only or is_dir) and (sc := _score(e.name, want)) >= (min_score or config.PATH_MATCH_MIN):
                found.append((sc, -lvl, Path(e.path)))
            if is_dir and lvl < depth:
                q.append((Path(e.path), lvl + 1))
    found.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [p for _, _, p in found[:k]]


def similar_dirs(want: str, k: int = 4) -> list[Path]:
    """Folders whose names look like `want` (looser than smart_path), best first: "did you mean ...?"."""
    segs = segments(want)
    if not segs:
        return []
    found: list[Path] = []
    for r in roots():
        found += find_children(r, segs[-1], depth=3, dirs_only=True, k=k, min_score=0.5)
    found.sort(key=lambda p: _score(p.name, segs[-1]), reverse=True)
    return list(dict.fromkeys(found))[:k]


def _walk(cur: Path, segs: list[str], want: str) -> Path | None:
    """Resolve the remaining segments under cur, trying alternatives when a name is ambiguous."""
    if not segs:
        ok = (want != "dir" or cur.is_dir()) and (want != "file" or cur.is_file())
        return cur if ok else None
    last = len(segs) == 1
    dirs_only = not last or want == "dir"
    cands = find_children(cur, segs[0], depth=2, dirs_only=dirs_only)
    if last and want != "dir" and not cands:
        cands = find_children(cur, segs[0], depth=3, dirs_only=False)
    for c in cands:
        if (hit := _walk(c, segs[1:], want)) is not None:
            return hit
    return None


def segments(text: str) -> list[str]:
    t = text.strip().strip("\"'")
    rev = bool(re.search(r"\bin\b", t, re.I)) and not re.search(r"/", t)
    parts = re.split(r"\s+\bin\b\s+", t, flags=re.I) if rev else [t]
    if rev:
        parts = list(reversed(parts))  # "tara in project1" -> project1, tara
    segs: list[str] = []
    for p in parts:
        for s in _SPLIT.split(p):
            s = " ".join(_FILLER.sub(" ", s).split())
            m = re.match(r"^(.*?)\s+(\S+\.[A-Za-z0-9]{1,6})$", s)  # "kurama readme.md" -> kurama, readme.md
            if m and m.group(1):
                segs += [m.group(1), m.group(2)]
            elif s:
                segs.append(s)
    return segs


def smart_path(text: str, want: str = "any") -> Path | None:
    """Resolve a loose path description to an existing path, or None. want: any | dir | file."""
    raw = (text or "").strip().strip("\"'")
    if not raw:
        return None
    p = Path(raw).expanduser()
    if p.is_absolute() and p.exists():
        return p
    home = str(Path.home())
    if raw.startswith("~/") or raw.startswith(home + "/"):  # "~/project1/kurama/x": the model guessed home
        raw = raw.split("/", 1)[1] if raw.startswith("~/") else raw[len(home) + 1:]
    segs = segments(raw.lstrip("/") if raw.startswith("/") else raw)
    if not segs:
        return None
    cur: Path | None = None
    alias = config.PATH_ALIASES.get(norm(segs[0]))
    if raw.startswith("/"):  # absolute but wrong case/typo: walk from / component by component
        cur = Path("/")
        for i, s in enumerate(segs):
            nxt = find_child(cur, s, depth=1, dirs_only=i < len(segs) - 1 or want == "dir")
            if nxt is None:
                return None
            cur = nxt
        return cur
    if alias:
        return _walk(Path(alias).expanduser(), segs[1:], want)
    for r in roots():  # first segment anywhere under the search roots (depth 3), then walk the rest
        for c in find_children(r, segs[0], depth=3, dirs_only=len(segs) > 1 or want == "dir"):
            if (hit := _walk(c, segs[1:], want)) is not None:
                return hit
    return None


def resolve_target(name: str, src_ext: str = "") -> Path | str:
    """For tools acting on ONE file/folder the user names loosely: a path, 'this'/'it' (the file we were just talking about, else the newest matching file in Downloads),
    or a file/folder NAME found anywhere. Returns the Path or an error string."""
    from jarvis.core import convert, focus
    raw = (name or "").strip().strip("'\"")
    want = convert.ext_of(src_ext) if src_ext else ""
    if not raw or focus.is_anaphora(raw) or raw.lower() in ("this " + want, "that " + want, want):
        if (fp := focus.get_path()) and Path(fp).exists() and (not want or Path(fp).is_dir()
                                                               or convert.ext_of(Path(fp).suffix) == want):
            return Path(fp)
        dl = Path.home() / "Downloads"
        files = sorted((p for p in dl.glob("*") if p.is_file() and (not want or convert.ext_of(p.suffix) == want)),
                       key=lambda p: p.stat().st_mtime, reverse=True) if dl.is_dir() else []
        return files[0] if files else f"error: which {want or ''} file? Give its name or path."
    p = Path(raw).expanduser()
    if p.exists():
        return p
    if hit := smart_path(raw):
        return hit
    from jarvis.tools.general.find_and_send import search
    stem_hits = search(raw) or (search(f"{raw}.{want}") if want else [])
    if want:
        stem_hits = [h for h in stem_hits if convert.ext_of(h.suffix) == want] or stem_hits
    return stem_hits[0] if stem_hits else f"error: I couldn't find '{raw}'."
