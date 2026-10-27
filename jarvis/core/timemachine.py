"""Code time machine: silent snapshots of the projects you work on, so "what changed since it worked?" and
"give me train.py from 2 hours ago" always have an answer, committed or not (0 tokens).

Each project gets a private shadow git repo in data/timemachine/<id>.git (its own history; your real .git is never
touched). The "timemachine" worker snapshots every TIMEMACHINE_EVERY_S, but only projects with files changed since
the last snapshot: git repos found under the search roots (re-scanned daily; your home folder and theme clones are
skipped) plus folders you add. Your .gitignore is respected, and venvs, data, checkpoints and files over
TIMEMACHINE_MAX_MB are never stored. Restoring a file snapshots the current state first, so it can be undone.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from jarvis.core import config, store

# Only code and text are kept (everything else is ignored): a store of code, not of datasets, PDFs or models.
KEEP = ["py", "pyi", "ipynb", "md", "rst", "txt", "cfg", "ini", "toml", "yaml", "yml", "json", "sh", "bash", "zsh",
        "js", "jsx", "ts", "tsx", "css", "scss", "html", "vue", "svelte", "sql", "r", "jl", "c", "cc", "cpp", "h", "hpp",
        "cu", "java", "kt", "go", "rs", "rb", "php", "lua", "swift", "dart", "proto", "graphql", "tex", "bib", "env.example"]
EXCLUDES = (["*", "!*/", "!Dockerfile", "!Makefile", "!.gitignore", "!.dockerignore"] + [f"!*.{e}" for e in KEEP]
            + ["venv/", ".venv/", "env/", "node_modules/", "__pycache__/", ".ipynb_checkpoints/", "wandb/", "mlruns/",
               "site-packages/", ".git/", ".env", "*.min.js", "package-lock.json", "*.lock"])


_LOW = [x for x in ("ionice", "-c3") if shutil.which("ionice")] + (["nice", "-n", "10"] if shutil.which("nice") else [])


class TMError(Exception):
    pass


def root() -> Path:
    d = Path(config.DATA_DIR) / "timemachine"
    d.mkdir(parents=True, exist_ok=True)
    return d


def shadow(project: Path) -> Path:
    return root() / (hashlib.sha1(str(project).encode()).hexdigest()[:12] + ".git")


def _git(project: Path, *args: str, timeout: float = 60, check: bool = True, binary: bool = False):
    sd = shadow(project)
    cmd = [*_LOW, "git", f"--git-dir={sd}", f"--work-tree={project}", "-c", "user.name=KURAMA",
           "-c", "user.email=kurama@localhost", "-c", "core.quotepath=off", "-c", "commit.gpgsign=false", *args]
    cp = subprocess.run(cmd, capture_output=True, timeout=timeout, text=not binary,
                        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"})
    if check and cp.returncode != 0:
        err = cp.stderr if isinstance(cp.stderr, str) else cp.stderr.decode("utf-8", "replace")
        raise TMError((err.strip().splitlines() or [f"git {args[0]} failed"])[-1][:200])
    return cp


def _ensure(project: Path) -> None:
    sd = shadow(project)
    if (sd / "HEAD").exists():
        return
    subprocess.run(["git", "init", "--bare", "-q", str(sd)], check=True, capture_output=True, timeout=20)
    (sd / "info").mkdir(exist_ok=True)
    (sd / "info" / "exclude").write_text("\n".join(EXCLUDES) + "\n")
    (sd / "kurama.json").write_text(json.dumps({"project": str(project), "created": time.time()}))


# ---------------------------------------------------------------- which projects
def projects() -> list[Path]:
    """Protected projects: added by the user + git repos found under the search roots."""
    added = json.loads(store.kv_get("tm_added") or "[]")
    found = json.loads(store.kv_get("tm_found") or "[]")
    hidden = set(json.loads(store.kv_get("tm_hidden") or "[]"))
    out = []
    for p in dict.fromkeys(added + found):
        if Path(p).is_dir() and p not in hidden:
            out.append(Path(p))
    return out


def discover(force: bool = False) -> list[str]:
    """Find git repos under the search roots (depth 4), at most once a day."""
    last = float(store.kv_get("tm_found_at") or 0)
    if not force and time.time() - last < 86400:
        return json.loads(store.kv_get("tm_found") or "[]")
    home = Path.home().resolve()
    skip = ("whitesur", "/.cache/", "/.local/", "/.cargo/", "/.npm/", "/snap/", "/site-packages/")
    found: list[str] = []
    for r in [Path(p).expanduser() for p in config.SEARCH_ROOTS]:
        if not r.is_dir():
            continue
        base_depth = len(r.parts)
        for dirpath, dirnames, _ in os.walk(r):
            depth = len(Path(dirpath).parts) - base_depth
            if ".git" in dirnames:
                p = Path(dirpath).resolve()
                if p != home and not any(s in str(p).lower() + "/" for s in skip):
                    found.append(str(p))
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in
                           ("node_modules", "venv", "env", "__pycache__", "site-packages")] if depth < 4 else []
    store.kv_set("tm_found", json.dumps(sorted(set(found))))
    store.kv_set("tm_found_at", str(time.time()))
    return found


def add_project(path: Path) -> str:
    added = json.loads(store.kv_get("tm_added") or "[]")
    if str(path) not in added:
        added.append(str(path))
        store.kv_set("tm_added", json.dumps(added))
    snap = snapshot(path, "first snapshot")
    return f"{path.name} is protected now: I'll keep a snapshot of its code every {config.TIMEMACHINE_EVERY_S // 60} " \
           f"minutes when it changes. {snap}"


def _find(name: str) -> Path | None:
    """A watched project by a loose name ('kurama', 'civic report')."""
    key = name.strip().lower().replace(" ", "")
    hits = [p for p in projects() if key and key in p.name.lower().replace(" ", "").replace("_", "").replace("-", "")]
    if not hits:
        return None
    return max(hits, key=last_activity)


def pin(name: str) -> str:
    p = _find(name)
    if p is None:
        return f"I don't watch a project called '{name}'. Say 'list my coding projects' to see them."
    store.kv_set("tm_pinned", str(p))
    return f"The Coding card now always shows {p.name} ({p}). Say 'unpin the project' to go back to automatic."


def unpin() -> str:
    store.kv_delete("tm_pinned")
    return "Automatic again: the Coding card shows the project you changed most recently."


def forget(name: str) -> str:
    """Stop watching a project (its folder and code are NOT touched)."""
    p = _find(name)
    if p is None:
        return f"I don't watch a project called '{name}'."
    hidden = json.loads(store.kv_get("tm_hidden") or "[]")
    if str(p) not in hidden:
        hidden.append(str(p))
        store.kv_set("tm_hidden", json.dumps(hidden))
    added = [x for x in json.loads(store.kv_get("tm_added") or "[]") if x != str(p)]
    store.kv_set("tm_added", json.dumps(added))
    if store.kv_get("tm_pinned") == str(p):
        store.kv_delete("tm_pinned")
    return f"I stopped watching {p.name}. Its folder and code are untouched. 'watch {p.name} again' brings it back."


def unforget(name: str) -> str:
    hidden = json.loads(store.kv_get("tm_hidden") or "[]")
    key = name.strip().lower().replace(" ", "")
    back = [h for h in hidden if key and key in Path(h).name.lower().replace(" ", "").replace("_", "").replace("-", "")]
    if not back:
        return f"{name} isn't on my 'not watched' list."
    store.kv_set("tm_hidden", json.dumps([h for h in hidden if h not in back]))
    return f"Watching {Path(back[0]).name} again."


def overview() -> str:
    """'list my coding projects': which one the Coding card shows and why, then all watched ones."""
    ps = sorted(projects(), key=last_activity, reverse=True)
    if not ps:
        return "I'm not watching any coding project yet. Say 'protect my <name> project'."
    try:
        cur = resolve("")
    except TMError:
        cur = ps[0]
    why = "you pinned it" if store.kv_get("tm_pinned") == str(cur) else "you changed it most recently"
    lines = [f"💻 The Coding card shows {cur.name} ({why}).", f"I watch {len(ps)} git projects (newest first):"]
    lines += [f"{i}. {p.name} — {p}" for i, p in enumerate(ps[:15], 1)]
    if len(ps) > 15:
        lines.append(f"…and {len(ps) - 15} more.")
    lines.append("Say 'pin <name> project' to always show one, 'stop watching <name>' to hide one (code is never deleted).")
    return "\n".join(lines)


def resolve(project: str = "") -> Path:
    """A project folder from a loose name, or the project you touched most recently."""
    if project.strip():
        from jarvis.tools.interactive import _proc
        try:
            return _proc.resolve_dir(project)
        except _proc.ProcError as e:
            raise TMError(str(e)) from None
    pinned = store.kv_get("tm_pinned") or ""
    if pinned and Path(pinned).is_dir():  # the user chose the project the Coding card shows
        return Path(pinned)
    best, when = None, 0.0
    for p in projects():
        t = last_activity(p)
        if t > when:
            best, when = p, t
    if best is None:
        raise TMError("which project? (none is protected yet; say e.g. 'protect my kurama project')")
    return best


# ---------------------------------------------------------------- snapshots
def _changed_files(project: Path) -> list[str]:
    if (project / ".git").exists():
        cp = subprocess.run(["git", "-C", str(project), "status", "--porcelain", "-uall", "--no-renames"],
                            capture_output=True, text=True, timeout=30)
        return [ln[3:].strip().strip('"') for ln in cp.stdout.splitlines() if len(ln) > 3]
    return [str(f.relative_to(project)) for f in project.rglob("*")
            if f.is_file() and not any(part in ("venv", ".venv", "node_modules", "__pycache__", ".git")
                                       for part in f.parts)][:5000]


def last_activity(project: Path) -> float:
    """When you last edited a file there (uncommitted changes; else the last commit)."""
    best = 0.0
    for n in _changed_files(project):
        try:
            best = max(best, (project / n).stat().st_mtime)
        except OSError:
            continue
    if not best and (project / ".git").exists():
        out = subprocess.run(["git", "-C", str(project), "log", "-1", "--format=%ct"], capture_output=True,
                             text=True, timeout=10).stdout.strip()
        best = float(out or 0)
    return best


def changed_since(project: Path, since: float) -> bool:
    """Any file in the project (git status, .gitignore respected) modified after `since`?"""
    if (project / ".git").exists():
        cp = subprocess.run(["git", "-C", str(project), "status", "--porcelain", "-uall", "--no-renames"],
                            capture_output=True, text=True, timeout=30)
        names = [ln[3:].strip().strip('"') for ln in cp.stdout.splitlines() if len(ln) > 3]
    else:
        names = [str(f.relative_to(project)) for f in project.rglob("*")
                 if f.is_file() and not any(part in ("venv", ".venv", "node_modules", "__pycache__", ".git")
                                            for part in f.parts)][:5000]
    for n in names:
        try:
            if (project / n).stat().st_mtime > since:
                return True
        except OSError:
            if since:  # deleted since
                return True
    return not shadow(project).joinpath("HEAD").exists() and bool(names)


def snapshot(project: Path, reason: str = "auto") -> str:
    _ensure(project)
    _git(project, "add", "-A", timeout=120)
    staged = _git(project, "diff", "--cached", "--name-only", "-z").stdout.split("\0")
    big = []
    for rel in filter(None, staged):
        try:
            if (project / rel).stat().st_size > config.TIMEMACHINE_MAX_MB * 1048576:
                big.append(rel)
        except OSError:
            continue
    if big:
        _git(project, "rm", "--cached", "-q", "-f", "--", *big)
        with open(shadow(project) / "info" / "exclude", "a") as f:
            f.write("\n".join("/" + b for b in big) + "\n")
    head = _git(project, "rev-parse", "-q", "--verify", "HEAD", check=False).returncode == 0
    if head and _git(project, "diff", "--cached", "--quiet", check=False).returncode == 0:
        store.kv_set(f"tm_last:{project}", str(time.time()))
        return "no changes since the last snapshot"
    n = len([s for s in staged if s]) - len(big)
    _git(project, "commit", "-q", "--no-verify", "-m", f"{reason} ({n} files)")
    store.kv_set(f"tm_last:{project}", str(time.time()))
    return f"snapshot saved ({n} changed files)"


def auto_snapshots() -> list[str]:
    """Worker tick: snapshot every protected project with changes since its last snapshot."""
    discover()
    done = []
    for p in projects():
        since = float(store.kv_get(f"tm_last:{p}") or 0)
        try:
            if changed_since(p, since):
                msg = snapshot(p)
                if msg.startswith("snapshot"):
                    done.append(f"{p.name}: {msg}")
        except (TMError, OSError, subprocess.SubprocessError) as e:
            store.kv_set(f"tm_last:{p}", str(time.time()))  # don't retry a broken one every tick
            done.append(f"{p.name}: failed ({e})")
    return done


# ---------------------------------------------------------------- questions
def commit_at(project: Path, when: str) -> str:
    """The snapshot just before `when` ('2 hours ago', 'yesterday 5pm', '10:30', a snapshot id)."""
    if not shadow(project).joinpath("HEAD").exists():
        raise TMError(f"no snapshots of {project.name} yet")
    w = (when or "").strip()
    if w and all(c in "0123456789abcdef" for c in w.lower()) and len(w) >= 6:
        return _git(project, "rev-parse", w).stdout.strip()
    c = _git(project, "rev-list", "-1", f"--before={w or 'now'}", "HEAD", check=False).stdout.strip()
    if not c:
        first = _git(project, "log", "--reverse", "--format=%cr", "HEAD").stdout.splitlines()
        raise TMError(f"no snapshot that old (the first is from {first[0] if first else '?'})")
    return c


def history(project: Path, path: str = "", n: int = 12) -> str:
    if not shadow(project).joinpath("HEAD").exists():
        return f"No snapshots of {project.name} yet."
    args = ["log", f"-{n}", "--format=%h  %cd  %s", "--date=format:%a %d %b %H:%M"]
    out = _git(project, *args, *(["--", path] if path else [])).stdout.strip()
    return f"Snapshots of {project.name}{' / ' + path if path else ''}:\n{out}" if out else "No snapshots for that file."


def diff(project: Path, when: str, path: str = "", max_chars: int = 3000) -> str:
    note = ""
    try:
        c = commit_at(project, when)
    except TMError as e:
        if "no snapshot that old" not in str(e):
            raise
        c = _git(project, "rev-list", "--max-parents=0", "HEAD").stdout.split()[-1]
        note = "(Snapshots only go back to the first one, so this is everything since then.)\n"
    snapshot(project, "before compare")
    stamp = _git(project, "show", "-s", "--format=%cd", "--date=format:%a %H:%M", c).stdout.strip()
    stat = _git(project, "diff", "--stat", c, "HEAD", *(["--", path] if path else [])).stdout.strip()
    if not stat:
        return note + f"Nothing changed in {project.name}{' / ' + path if path else ''} since {stamp}."
    patch = _git(project, "diff", "-U2", c, "HEAD", *(["--", path] if path else [])).stdout
    if len(patch) > max_chars:
        patch = patch[:max_chars] + "\n...[more]"
    return note + f"Changes in {project.name} since {stamp}:\n{stat}\n\n{patch}"


def restore(project: Path, path: str, when: str) -> str:
    c = commit_at(project, when)
    rel = str(Path(path)) if not os.path.isabs(path) else os.path.relpath(path, project)
    cp = _git(project, "show", f"{c}:{rel}", check=False, binary=True)
    if cp.returncode != 0:
        raise TMError(f"{rel} isn't in that snapshot")
    snapshot(project, f"before restoring {rel}")
    before = _git(project, "rev-parse", "HEAD").stdout.strip()
    store.kv_set("tm_undo", json.dumps({"project": str(project), "path": rel, "commit": before}))
    target = project / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(cp.stdout)
    stamp = _git(project, "show", "-s", "--format=%cd", "--date=format:%a %H:%M", c).stdout.strip()
    return f"Restored {rel} as it was at {stamp}. The version you had is saved too (say 'undo the restore')."


def undo() -> str:
    u = json.loads(store.kv_get("tm_undo") or "{}")
    if not u:
        return "Nothing to undo."
    store.kv_set("tm_undo", "")
    return restore(Path(u["project"]), u["path"], u["commit"]).replace("Restored", "Put back", 1)
