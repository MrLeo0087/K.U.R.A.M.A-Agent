"""Shared helpers for open/close/focus app tools (not a tool): a cached index of .desktop files,
fuzzy matching of spoken app names, a detached launcher (gtk-launch, then gio) and wmctrl windows."""
from __future__ import annotations

import difflib
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from jarvis.tools.interactive import _proc

DESKTOP_DIRS = [Path("/usr/share/applications"), Path.home() / ".local/share/applications",
                Path("/var/lib/snapd/desktop/applications"),
                Path("/var/lib/flatpak/exports/share/applications"),
                Path.home() / ".local/share/flatpak/exports/share/applications"]
INDEX_TTL_S = 300
FASTPATH_MIN_SCORE = 75  # the zero-token path only launches confident matches
TOOL_MIN_SCORE = 50

# Spoken name -> names to look for, in order.
ALIASES: dict[str, list[str]] = {}
for _spoken, _targets in {
    ("vs code", "vscode", "visual studio", "visual studio code", "code editor", "vs", "bs code", "code"): ["visual studio code", "vscode", "code"],
    ("settings", "system settings", "control center", "control panel", "setting"): ["settings"],
    ("files", "file manager", "file explorer", "explorer", "nautilus", "my files"): ["files", "nautilus"],
    ("terminal", "console", "command line", "shell", "command prompt"): ["terminal", "console", "ptyxis"],
    ("chrome", "google chrome"): ["google chrome", "chromium", "chrome"],
    ("calculator", "calc"): ["calculator"],
    ("text editor", "editor", "notepad", "gedit"): ["text editor", "gedit", "gnome text editor"],
    ("browser", "web browser"): ["firefox", "web browser"],
}.items():
    for _s in _spoken:
        ALIASES[_s] = _targets

_index: list[dict] = []
_index_ts = 0.0
_lock = threading.Lock()


def compact(s: str) -> str:
    return re.sub(r"[\W_]+", "", (s or "").lower())


def clean_query(name: str) -> str:
    q = re.sub(r"[?!.]+$", "", (name or "").strip().strip("\"'")).lower()
    q = re.sub(r"^(?:the|my)\s+", "", q)
    return re.sub(r"\s+(?:app|application|window|program)$", "", q).strip()


def _exe(exec_line: str) -> str:
    toks = [t for t in exec_line.split() if not t.startswith("%")]
    if toks and toks[0].endswith("env"):
        toks = [t for t in toks[1:] if "=" not in t]
    if len(toks) > 2 and toks[0].endswith("flatpak") and toks[1] == "run":
        toks = [t for t in toks[2:] if not t.startswith("-")]
    return os.path.basename(toks[0]).lower() if toks else ""


def parse_desktop(path: Path) -> dict | None:
    """Fields of the [Desktop Entry] section, or None for hidden/non-application entries."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    fields: dict[str, str] = {}
    in_entry = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            in_entry = line == "[Desktop Entry]"
            continue
        if in_entry and "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            fields.setdefault(k.strip(), v.strip())
    if fields.get("Type", "Application") != "Application" or not fields.get("Name"):
        return None
    if fields.get("NoDisplay", "").lower() == "true" or fields.get("Hidden", "").lower() == "true":
        return None
    app_id = path.name[:-8] if path.name.endswith(".desktop") else path.name
    return {"id": app_id, "path": str(path), "name": fields["Name"],
            "generic": fields.get("GenericName", ""),
            "keywords": [k.strip() for k in fields.get("Keywords", "").split(";") if k.strip()],
            "wmclass": fields.get("StartupWMClass", ""), "exe": _exe(fields.get("Exec", ""))}


def index(refresh: bool = False) -> list[dict]:
    """All visible apps (first .desktop id wins, like XDG); cached for INDEX_TTL_S."""
    global _index, _index_ts
    with _lock:
        if _index and not refresh and time.monotonic() - _index_ts < INDEX_TTL_S:
            return _index
        seen: dict[str, dict] = {}
        for d in DESKTOP_DIRS:
            try:
                files = sorted(Path(d).glob("*.desktop"))
            except OSError:
                continue
            for f in files:
                if f.name[:-8] not in seen and (e := parse_desktop(f)):
                    seen[e["id"]] = e
        _index, _index_ts = list(seen.values()), time.monotonic()
        return _index


def _score(target: str, e: dict) -> int:
    t = compact(target)
    if len(t) < 2:
        return 0
    name, stem = compact(e["name"]), compact(e["id"].rsplit(".", 1)[-1])
    if t in (name, stem, compact(e["id"]), compact(e["exe"])):
        return 100
    if e["generic"] and t == compact(e["generic"]):
        return 90
    if t in {compact(k) for k in e["keywords"]}:
        return 85
    if len(t) >= 3 and (name.startswith(t) or target.lower() in e["name"].lower().split()):
        return 75
    if len(t) >= 4 and t in name:
        return 60
    ratio = difflib.SequenceMatcher(None, t, name).ratio()
    return int(60 * ratio) if ratio >= 0.85 else 0


def find_app(name: str, apps: list[dict] | None = None) -> tuple[dict | None, int]:
    """Best (entry, score 0..100) for a spoken app name; (None, 0) if nothing plausible."""
    q = clean_query(name)
    if not q:
        return None, 0
    apps = index() if apps is None else apps
    best, best_score = None, 0
    for rank, target in enumerate(ALIASES.get(q, []) + [q]):
        for e in apps:
            s = _score(target, e) - rank  # earlier alias targets win ties
            if s > best_score or (s == best_score and best and len(e["name"]) < len(best["name"])):
                best, best_score = e, s
    return (best, max(best_score, 0)) if best_score > 0 else (None, 0)


def launch(entry: dict) -> str:
    """Start an app detached from KURAMA: gtk-launch <id>, falling back to gio launch <file>."""
    gtk, gio = shutil.which("gtk-launch"), shutil.which("gio")
    if gtk:
        p = subprocess.Popen([gtk, entry["id"]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            if p.wait(timeout=3) == 0:
                return "gtk-launch"
        except subprocess.TimeoutExpired:
            return "gtk-launch"  # still starting; leave it running
    if gio:
        subprocess.Popen([gio, "launch", entry["path"]], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return "gio"
    raise RuntimeError("could not launch: neither gtk-launch nor gio works (install libgtk-3-bin)")


def list_windows() -> list[dict]:
    """Normal windows from `wmctrl -l -x`: {id, wmclass, title} (sticky -1 desktop windows skipped)."""
    if not shutil.which("wmctrl"):
        raise _proc.ProcError("wmctrl not found: sudo apt install wmctrl")
    out = _proc.run(["wmctrl", "-l", "-x"], timeout=5).stdout
    wins = []
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 3 and parts[1] != "-1":
            wins.append({"id": parts[0], "wmclass": parts[2], "title": parts[4] if len(parts) > 4 else ""})
    return wins


def match_windows(name: str, windows: list[dict] | None = None) -> tuple[list[dict], str]:
    """Windows belonging to the named app (by WM class, else by title) and a display name."""
    entry, score = find_app(name)
    q = clean_query(name)
    label = entry["name"] if entry and score >= TOOL_MIN_SCORE else q
    terms = {compact(q)}
    if entry and score >= TOOL_MIN_SCORE:
        terms |= {compact(entry["name"]), compact(entry["id"].rsplit(".", 1)[-1]),
                  compact(entry["wmclass"]), compact(entry["exe"])}
    terms = {t for t in terms if len(t) >= 3}
    windows = list_windows() if windows is None else windows
    by_class = [w for w in windows if any(t in compact(w["wmclass"]) for t in terms)]
    if by_class:
        return by_class, label
    return [w for w in windows if len(q) >= 3 and q in w["title"].lower()], label


def wmctrl(args: list[str]) -> None:
    cp = _proc.run(["wmctrl", *args], timeout=5)
    if cp.returncode != 0:
        raise _proc.ProcError((cp.stderr or "wmctrl failed").strip()[:200])
