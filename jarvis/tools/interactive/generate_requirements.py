"""generate_requirements: build requirements.generated.txt from a project's imports (safe; no LLM).
ast collects absolute imports, drops stdlib (sys.stdlib_module_names) and the project's own modules,
maps import names to PyPI names (installed distributions first, then a small built-in map), and pins
versions installed in the project's venv (venv/.venv/env) or else the active one; anything not installed
is listed unpinned with a note. Imports inside try/except ImportError are marked optional.
requirements.txt is never overwritten without a yes; the reply compares against it."""
from __future__ import annotations

import ast
import re
import sys
from importlib import metadata
from pathlib import Path

from jarvis.core import safety
from jarvis.core.registry import tool
from jarvis.tools.general import _files
from jarvis.tools.interactive import _proc

MAX_FILES = 3000
MAX_BYTES = 1_000_000
PYPI_NAMES = {  # import name -> PyPI name (used when the package is not installed)
    "cv2": "opencv-python", "sklearn": "scikit-learn", "skimage": "scikit-image", "PIL": "Pillow",
    "yaml": "PyYAML", "bs4": "beautifulsoup4", "dotenv": "python-dotenv", "dateutil": "python-dateutil",
    "jwt": "PyJWT", "serial": "pyserial", "usb": "pyusb", "Crypto": "pycryptodome", "OpenSSL": "pyOpenSSL",
    "magic": "python-magic", "docx": "python-docx", "pptx": "python-pptx", "fitz": "PyMuPDF",
    "git": "GitPython", "attr": "attrs", "telegram": "python-telegram-bot", "discord": "discord.py",
    "faiss": "faiss-cpu", "websocket": "websocket-client", "zmq": "pyzmq", "Levenshtein": "python-Levenshtein",
    "multipart": "python-multipart", "slugify": "python-slugify", "gi": "PyGObject", "wx": "wxPython",
    "MySQLdb": "mysqlclient", "psycopg2": "psycopg2-binary", "edge_tts": "edge-tts", "mpl_toolkits": "matplotlib",
    "google.protobuf": "protobuf", "google.generativeai": "google-generativeai", "jose": "python-jose",
    "ruamel": "ruamel.yaml", "sentence_transformers": "sentence-transformers", "Bio": "biopython",
    "lxml": "lxml", "win32api": "pywin32", "pkg_resources": "setuptools", "setuptools": "setuptools",
    "markdown": "Markdown", "jinja2": "Jinja2", "flask": "Flask", "socketio": "python-socketio",
    "engineio": "python-engineio", "speech_recognition": "SpeechRecognition", "pydub": "pydub",
}
NOT_PACKAGES = {"__future__", "__main__", "_typeshed", "typing_extensions"}  # typing_extensions kept below
OPTIONAL_EXC = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}


def canon(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def py_files(root: Path) -> list[Path]:
    out = []
    for p in root.rglob("*.py"):
        rel = p.relative_to(root).parts
        if any(part in _proc.EXCLUDES or part.startswith(".") for part in rel[:-1]):
            continue
        out.append(p)
        if len(out) >= MAX_FILES:
            break
    return out


def local_names(root: Path, files: list[Path]) -> set[str]:
    names = {p.stem for p in files}
    for p in files:
        for parent in p.relative_to(root).parents:
            if parent.name:
                names.add(parent.name)
    return names


def _optional_handler(t: ast.Try) -> bool:
    for h in t.handlers:
        if h.type is None:
            return True
        types = h.type.elts if isinstance(h.type, ast.Tuple) else [h.type]
        if any(isinstance(x, ast.Name) and x.id in OPTIONAL_EXC for x in types):
            return True
    return False


def scan_imports(files: list[Path]) -> tuple[dict[str, set[str]], set[str]]:
    """({top-level name: {full dotted names}}, names only ever imported inside try/except ImportError)."""
    found: dict[str, set[str]] = {}
    required: set[str] = set()
    for p in files:
        try:
            if p.stat().st_size > MAX_BYTES:
                continue
            tree = ast.parse(p.read_text("utf-8", "replace"))
        except (SyntaxError, ValueError, OSError):
            continue
        optional_ids = set()
        for t in ast.walk(tree):
            if isinstance(t, ast.Try) and _optional_handler(t):
                for s in t.body:
                    optional_ids.update(id(x) for x in ast.walk(s))
        for n in ast.walk(tree):
            mods = []
            if isinstance(n, ast.Import):
                mods = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom) and not n.level and n.module:
                mods = [n.module]
            for m in mods:
                top = m.split(".")[0]
                found.setdefault(top, set()).add(m)
                if id(n) not in optional_ids:
                    required.add(top)
    return found, set(found) - required


def site_packages(root: Path) -> tuple[list[str] | None, str]:
    for name in ("venv", ".venv", "env"):
        sp = sorted((root / name).glob("lib/python3*/site-packages"))
        if sp:
            return [str(sp[-1])], f"{name}/"
    return None, f"active env ({Path(sys.prefix).name})"


def _tops(dist: metadata.Distribution) -> set[str]:
    txt = dist.read_text("top_level.txt")
    if txt:
        return {t.strip().replace("/", ".") for t in txt.split() if t.strip()}
    out = set()
    for f in dist.files or []:
        parts = f.parts
        if not parts or parts[0] in ("..", "__pycache__") or parts[0].endswith((".dist-info", ".egg-info", ".pth")):
            continue
        if len(parts) == 1:
            if parts[0].endswith(".py"):
                out.add(parts[0][:-3])
            elif parts[0].endswith((".so", ".pyd")):
                out.add(parts[0].split(".")[0])
        else:
            out.add(parts[0])
    return out


def installed(path: list[str] | None) -> tuple[dict[str, list[tuple[str, str]]], dict[str, tuple[str, str]]]:
    """({import top: [(dist, version)]}, {canonical dist: (dist, version)})."""
    by_top: dict[str, list[tuple[str, str]]] = {}
    by_name: dict[str, tuple[str, str]] = {}
    dists = metadata.distributions(path=path) if path else metadata.distributions()
    for d in dists:
        name = (d.metadata["Name"] or "").strip()
        if not name or canon(name) in by_name:
            continue
        by_name[canon(name)] = (name, d.version)
        for t in _tops(d):
            by_top.setdefault(t, []).append((name, d.version))
    return by_top, by_name


def resolve(top: str, full: set[str], by_top: dict, by_name: dict) -> tuple[str, str]:
    """(PyPI name, installed version or '')."""
    cands = by_top.get(top, [])
    if len(cands) > 1:  # namespace packages (google.*): pick the dist that matches the sub-module
        subs = {m.split(".")[1] for m in full if m.count(".")}
        best = [c for c in cands if any(s.lower() in canon(c[0]) for s in subs)]
        cands = best or sorted(cands)
    if cands:
        return cands[0]
    for m in sorted(full, key=len, reverse=True):
        if m in PYPI_NAMES:
            pypi = PYPI_NAMES[m]
            break
    else:
        pypi = PYPI_NAMES.get(top, top)
    hit = by_name.get(canon(pypi))
    return (hit[0], hit[1]) if hit else (pypi, "")


def read_requirements(path: Path) -> set[str]:
    names = set()
    try:
        for ln in path.read_text("utf-8", "replace").splitlines():
            m = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)", ln.split("#", 1)[0])
            if m and not ln.lstrip().startswith("-"):
                names.add(canon(m.group(1)))
    except OSError:
        pass
    return names


@tool(group="devutils", safety="safe",
      description="Generate requirements.generated.txt from a project's imports, pinned to installed versions.")
def generate_requirements(path: str = ".", output: str = "requirements.generated.txt") -> str:
    """Scan a project's imports and write a requirements file.

    Args:
        path: Project folder (default: current folder).
        output: File name to write inside the project (default requirements.generated.txt).
    """
    root = _proc.resolve_dir(path)
    files = py_files(root)
    if not files:
        return f"no Python files in {root}"
    found, optional = scan_imports(files)
    local = local_names(root, files)
    std = set(sys.stdlib_module_names) | NOT_PACKAGES
    tops = sorted(t for t in found if t not in std and t not in local and not t.startswith("_"))
    if "typing_extensions" in found:
        tops.append("typing_extensions")
    sp, env_label = site_packages(root)
    by_top, by_name = installed(sp)
    rows: dict[str, tuple[str, str, bool]] = {}
    for t in tops:
        name, ver = resolve(t, found[t], by_top, by_name)
        prev = rows.get(canon(name))
        rows[canon(name)] = (name, ver, (t in optional) and (prev is None or prev[2]))
    lines, unpinned = [], []
    for key in sorted(rows):
        name, ver, opt = rows[key]
        note = "  # optional (try/except ImportError)" if opt else ""
        if ver:
            lines.append(f"{name}=={ver}{note}")
        else:
            unpinned.append(name)
            lines.append(f"{name}  # not installed in {env_label}: version unknown{note.replace('  #', ';')}")
    out = root / (output or "requirements.generated.txt")
    _files.guard(out)
    if out.name == "requirements.txt" and out.exists():
        if not safety.ask(f"Overwrite {out}? (a generated list replaces your hand-written one)"):
            out = root / "requirements.generated.txt"
    elif not out.exists() and not _files.ask_outside(out, "write"):
        return "The user declined: nothing written."
    head = (f"# Generated by KURAMA generate_requirements from {len(files)} files in {root.name}; "
            f"versions from {env_label}.\n")
    out.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    msg = f"wrote {out.name}: {len(rows)} packages ({len(rows) - len(unpinned)} pinned from {env_label}"
    msg += f", {len(unpinned)} unpinned: {', '.join(unpinned[:6])})" if unpinned else ")"
    req = root / "requirements.txt"
    if req.exists() and out != req:
        have = read_requirements(req)
        missing = [rows[k][0] for k in sorted(rows) if k not in have]
        extra = sorted(have - set(rows))
        msg += (f". vs requirements.txt: missing {', '.join(missing[:8]) or 'none'}"
                f"{f' +{len(missing) - 8}' if len(missing) > 8 else ''}; listed but not imported "
                f"{', '.join(extra[:8]) or 'none'}{f' +{len(extra) - 8}' if len(extra) > 8 else ''}"
                " (may be transitive or CLI tools)")
    return _proc.clip(msg, 800)
