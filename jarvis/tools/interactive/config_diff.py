"""config_diff: snapshot a project's config files and report what changed (safe; no LLM).
Reads .env.example/.env.sample, *.yaml/*.yml/*.toml/*.json/*.ini/*.cfg and config.py/settings.py
(never .env or other .env.* files, never credential/secret files), flattens them to dotted keys and
stores one JSON snapshot per run in SQLite (config_snapshots). Secret-looking values (by key name or by
value) are stored only as '****#<hash6>', so changes are detected without keeping the value.
Reports added/removed/changed keys since the last snapshot or between two snapshot ids."""
from __future__ import annotations

import ast
import configparser
import hashlib
import json
import re
import time
from pathlib import Path

from jarvis.core.registry import tool
from jarvis.tools.interactive import _proc, _secrets

CONFIG_EXT = (".yaml", ".yml", ".toml", ".json", ".ini", ".cfg")
CONFIG_PY = ("config.py", "settings.py")
ENV_TEMPLATES = (".env.example", ".env.sample", ".env.template", ".env.dist", "example.env", "sample.env")
SKIP_DIRS = set(_proc.EXCLUDES) | {"data", "logs", "outputs", "htmlcov", "coverage", ".idea"}
SKIP_FILE = re.compile(r"(?i)secret|credential|service[-_]?account|token|password|\.pem$|id_rsa|"
                       r"package-lock\.json$|\.lock$|composer\.lock$|\.ipynb$")
SECRET_KEY = re.compile(r"(?i)pass(?:wd|word)?|secret|token|api[_-]?key|apikey|private|credential|auth(?!or)|"
                        r"\bdsn\b|cookie|session[_-]?key|access[_-]?key|signing|salt|pwd")
ENV_REF = re.compile(r"^\$\{?\w+\}?$|os\.getenv|os\.environ|environ\[|getenv\(|^<[^>]*>$")
MAX_FILES = 150
MAX_BYTES = 256_000
MAX_KEYS = 600  # per file
VAL_MAX = 120
SCHEMA = ("CREATE TABLE IF NOT EXISTS config_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, root TEXT, "
          "ts REAL, nfiles INTEGER, nkeys INTEGER, data TEXT)")


# --- collecting ---
def is_config(p: Path) -> bool:
    name = p.name
    if name == ".env" or (name.startswith(".env") and name not in ENV_TEMPLATES) or name.endswith(".env") \
            and name not in ENV_TEMPLATES:
        return False  # real env files hold real secrets: never read them
    if SKIP_FILE.search(name):
        return False
    return name in ENV_TEMPLATES or name in CONFIG_PY or p.suffix.lower() in CONFIG_EXT


def config_files(root: Path) -> list[Path]:
    out = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).parts
        if any(part in SKIP_DIRS or part.startswith(".") and part not in (".vscode", ".github")
               for part in rel[:-1]):
            continue
        if p.is_file() and is_config(p):
            try:
                if p.stat().st_size <= MAX_BYTES:
                    out.append(p)
            except OSError:
                continue
        if len(out) >= MAX_FILES:
            break
    return out


def _scalar(v) -> str:
    return json.dumps(v) if v is None or isinstance(v, bool) else str(v)


def flatten(obj, prefix: str = "", out: dict | None = None) -> dict:
    out = {} if out is None else out
    if len(out) >= MAX_KEYS:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            flatten(v, f"{prefix}.{k}" if prefix else str(k), out)
    elif isinstance(obj, list):
        if len(obj) <= 12 and all(not isinstance(x, (dict, list)) for x in obj):
            out[prefix or "[]"] = json.dumps(obj, default=str)
        else:
            for i, v in enumerate(obj[:50]):
                flatten(v, f"{prefix}[{i}]", out)
    else:
        out[prefix or "value"] = _scalar(obj)
    return out


def _env_lines(text: str) -> dict:
    out = {}
    for ln in text.splitlines():
        m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][\w.]*)\s*=\s*(.*)$", ln)
        if m:
            out[m.group(1)] = m.group(2).split(" #", 1)[0].strip().strip("\"'")
    return out


def _yaml(text: str) -> dict:
    try:
        import yaml
    except ImportError:  # minimal "key: value" fallback
        return {m.group(1): m.group(2).strip() for m in re.finditer(r"^([\w.-]+):\s*(\S.*)$", text, re.M)}
    docs = [d for d in yaml.safe_load_all(text)]
    if len(docs) == 1:
        return flatten(docs[0])
    return flatten({f"doc{i}": d for i, d in enumerate(docs)})


def _config_py(text: str) -> dict:
    out = {}
    for n in ast.parse(text).body:
        targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, ast.AnnAssign) else []
        value = getattr(n, "value", None)
        for t in targets:
            if isinstance(t, ast.Name) and value is not None:
                try:
                    out[t.id] = _scalar(ast.literal_eval(value))
                except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
                    out[t.id] = ast.unparse(value)
    return out


def parse(p: Path) -> dict:
    text = p.read_text("utf-8", "replace")
    name, ext = p.name, p.suffix.lower()
    if name in ENV_TEMPLATES:
        return _env_lines(text)
    if name in CONFIG_PY:
        return _config_py(text)
    if ext in (".yaml", ".yml"):
        return _yaml(text)
    if ext == ".toml":
        import tomllib
        return flatten(tomllib.loads(text))
    if ext == ".json":
        return flatten(json.loads(text))
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.read_string(text)
    return {f"{s}.{k}": v for s in cp.sections() for k, v in cp.items(s, raw=True)}


def looks_secret(key: str, value: str) -> bool:
    if not value or ENV_REF.search(value) or value.lower() in ("none", "null", "true", "false", "''", '""'):
        return False
    if SECRET_KEY.search(key.rsplit(".", 1)[-1]):
        return True
    return bool(_secrets.scan_line(f'{key} = "{value}"', "cfg", 1)) or (
        len(value) >= 24 and " " not in value and _secrets.entropy(value) >= 4.2)


def clean(rel: str, key: str, value: str) -> str:
    if looks_secret(key, value):
        return "****#" + hashlib.sha256(f"{rel}:{key}:{value}".encode()).hexdigest()[:6]
    value = _secrets.redact(value)
    if len(value) > VAL_MAX:
        value = value[:80] + "…#" + hashlib.sha1(value.encode()).hexdigest()[:6]
    return value


def collect(root: Path) -> dict[str, dict[str, str]]:
    data = {}
    for p in config_files(root):
        rel = str(p.relative_to(root))
        try:
            kv = parse(p)
        except Exception as e:  # broken file: record that, not its content
            kv = {"<parse error>": type(e).__name__}
        data[rel] = {str(k)[:120]: clean(rel, str(k), str(v)) for k, v in list(kv.items())[:MAX_KEYS]}
    return data


# --- storage ---
def _db(sql: str, params: tuple = ()):
    from jarvis.core import store

    store._exec(SCHEMA)
    return store._exec(sql, params)


def save(root: Path, data: dict) -> int:
    from jarvis.core import store

    _db("SELECT 1")
    with store._lock:
        cur = store._conn.execute(  # type: ignore[union-attr]
            "INSERT INTO config_snapshots(root,ts,nfiles,nkeys,data) VALUES (?,?,?,?,?)",
            (str(root), time.time(), len(data), sum(map(len, data.values())), json.dumps(data, sort_keys=True)))
        return int(cur.lastrowid)


def load(snap_id: int) -> tuple[dict, dict] | None:
    rows = _db("SELECT id,root,ts,nfiles,nkeys,data FROM config_snapshots WHERE id=?", (snap_id,))
    return (dict(rows[0]), json.loads(rows[0]["data"])) if rows else None


def last(root: Path) -> tuple[dict, dict] | None:
    rows = _db("SELECT id FROM config_snapshots WHERE root=? ORDER BY id DESC LIMIT 1", (str(root),))
    return load(rows[0]["id"]) if rows else None


# --- diff ---
def _short(v: str, n: int = 40) -> str:
    return v if len(v) <= n else v[: n - 1] + "…"


def diff(old: dict, new: dict, limit: int = 30) -> tuple[list[str], tuple[int, int, int]]:
    lines: list[str] = []
    add = rem = chg = 0
    for f in sorted(set(old) | set(new)):
        a, b = old.get(f), new.get(f)
        if a is None:
            lines.append(f"new file {f} ({len(b)} keys)")
            add += len(b)
            continue
        if b is None:
            lines.append(f"removed file {f} ({len(a)} keys)")
            rem += len(a)
            continue
        parts = []
        for k in sorted(set(a) | set(b)):
            if k not in a:
                parts.append(f"+{k}={_short(b[k])}")
                add += 1
            elif k not in b:
                parts.append(f"-{k}")
                rem += 1
            elif a[k] != b[k]:
                chg += 1
                if a[k].startswith("****#") or b[k].startswith("****#"):
                    parts.append(f"~{k} (secret changed, masked)")
                else:
                    parts.append(f"~{k}: {_short(a[k], 30)} → {_short(b[k], 30)}")
        if parts:
            lines.append(f"{f}: " + "; ".join(parts[:12]) + (f"; +{len(parts) - 12} more" if len(parts) > 12 else ""))
    if len(lines) > limit:
        lines = lines[:limit] + [f"...{len(lines) - limit} more files"]
    return lines, (add, rem, chg)


def _ago(ts: float) -> str:
    s = int(time.time() - ts)
    return f"{s // 86400}d ago" if s >= 86400 else f"{s // 3600}h ago" if s >= 3600 else f"{s // 60}m ago"


def _report(title: str, old: dict, new: dict) -> str:
    lines, (a, r, c) = diff(old, new)
    if not lines:
        return f"{title}: no config changes"
    return _proc.clip(f"{title} (+{a} -{r} ~{c} keys):\n" + "\n".join(lines), 800)


@tool(group="devutils", safety="safe", max_chars=900,
      description="Snapshot a project's config files and show what changed since the last snapshot (secrets masked).")
def config_diff(path: str = ".", action: str = "diff", a: int = 0, b: int = 0) -> str:
    """Track config changes (yaml/toml/json/ini/config.py/.env.example; never .env).

    Args:
        path: Project folder (default: current folder).
        action: "diff" (snapshot now and compare with the last one), "snapshot", "list" or "compare".
        a: First snapshot id for "compare".
        b: Second snapshot id for "compare" (0 = current files, not saved).
    """
    root = _proc.resolve_dir(path)
    action = (action or "diff").strip().lower()
    if action == "list":
        rows = _db("SELECT id,ts,nfiles,nkeys FROM config_snapshots WHERE root=? ORDER BY id DESC LIMIT 8",
                   (str(root),))
        if not rows:
            return f"no config snapshots for {root.name} yet"
        return f"config snapshots for {root.name}: " + "; ".join(
            f"#{r['id']} {_ago(r['ts'])} ({r['nfiles']} files, {r['nkeys']} keys)" for r in rows)
    if action == "compare" or a:
        first = load(a) if a else last(root)
        if first is None:
            return f"no snapshot #{a}" if a else f"no config snapshots for {root.name} yet"
        if b:
            second = load(b)
            if second is None:
                return f"no snapshot #{b}"
            return _report(f"config #{first[0]['id']} → #{b}", first[1], second[1])
        return _report(f"config #{first[0]['id']} → now (not saved)", first[1], collect(root))
    data = collect(root)
    if not data:
        return f"no config files found in {root}"
    prev = last(root)
    if prev and prev[1] == data:
        return f"no config changes in {root.name} since snapshot #{prev[0]['id']} ({_ago(prev[0]['ts'])})"
    sid = save(root, data)
    nkeys = sum(map(len, data.values()))
    if prev is None or action == "snapshot":
        extra = "" if prev is None else f" (#{prev[0]['id']} differs; run a diff to see how)"
        return (f"saved config snapshot #{sid} for {root.name}: {len(data)} files, {nkeys} keys{extra}. "
                "Ask again later to see what changed.")
    return _report(f"config changes in {root.name} #{prev[0]['id']} → #{sid}", prev[1], data)
