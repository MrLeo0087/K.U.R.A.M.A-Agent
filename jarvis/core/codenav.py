"""Go to the real code of a function/class (0 tokens): the name highlighted in VS Code -> where it is DEFINED
(the project first, then the installed library) -> opened in VS Code at that line.

Search = ripgrep over the VS Code folder (venv / node_modules / .git skipped). Python imports in the current file
pick the right file when a name is defined in several places. Library code (numpy, requests...) is found with the
project's own Python (inspect.getsourcefile); built-in C functions have no Python code to open.
"""
from __future__ import annotations

import ast
import json
import logging
import re
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

SKIP = ("venv", ".venv", "env", "node_modules", ".git", "__pycache__", "build", "dist", "site-packages",
        ".mypy_cache", ".pytest_cache", ".tox")
_NAME = re.compile(r"[A-Za-z_][\w]*(?:\.[A-Za-z_]\w*)*")
MAX_BLOCK = 150


def name_from(selection: str) -> str:
    """'total = calc.add(a, b)' -> 'calc.add'; 'self.save()' -> 'save'; 'def run(x):' -> 'run'."""
    s = (selection or "").strip().splitlines()[0] if (selection or "").strip() else ""
    s = re.sub(r"^\s*(?:async\s+)?(?:def|class|function|func|fn)\s+", "", s)
    if "(" in s:
        s = s[:s.index("(")]
    hits = _NAME.findall(s)
    if not hits:
        return ""
    name = hits[-1]
    return re.sub(r"^(?:self|cls|this)\.", "", name)


def _patterns(n: str) -> list[tuple[str, int]]:
    """(regex, rank) for a definition of n; lower rank = surer."""
    e = re.escape(n)
    return [(rf"^\s*(?:async\s+)?def\s+{e}\s*\(", 0), (rf"^\s*class\s+{e}\b", 0),
            (rf"\bfunction\s*\*?\s+{e}\s*\(", 0), (rf"\b(?:const|let|var)\s+{e}\s*=", 1),
            (rf"^\s*(?:export\s+)?(?:default\s+)?class\s+{e}\b", 0), (rf"^\s*func\s+(?:\([^)]*\)\s*)?{e}\s*\(", 0),
            (rf"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+{e}\b", 0),
            (rf"^\s*(?:(?:public|private|protected|static|async|override)\s+)*{e}\s*\([^;]*\)\s*\{{", 1),
            (rf"^{e}\s*(?::[^=]+)?=[^=]", 2)]


def search(name: str, root: Path) -> list[dict]:
    """Every definition of name under root: [{file, line, text, rank}], surest first."""
    if not name or not root or not root.is_dir():
        return []
    rg = shutil.which("rg")
    if not rg:
        return []
    pats = _patterns(name)
    cmd = [rg, "-n", "--no-heading", "--color", "never", "-m", "20", "--max-filesize", "2M"]
    for d in SKIP:
        cmd += ["-g", f"!{d}/"]
    cmd += ["-g", "!*.min.js", "-g", "!*.map", "-g", "!*.md", "-g", "!*.txt", "-g", "!*.json", "-g", "!*.ipynb"]
    for p, _ in pats:
        cmd += ["-e", p]
    try:
        out = subprocess.run(cmd + ["--", str(root)], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("rg failed: %s", e)
        return []
    hits = []
    for line in out.splitlines()[:200]:
        f, _, rest = line.partition(":")
        num, _, text = rest.partition(":")
        if not num.isdigit():
            continue
        rank = min((r for p, r in pats if re.search(p, text)), default=3)
        hits.append({"file": Path(f), "line": int(num), "text": text.strip()[:120], "rank": rank})
    return sorted(hits, key=lambda h: (h["rank"], len(h["file"].parts), str(h["file"])))


def _imported_from(name: str, src: str) -> tuple[str, str]:
    """Where the current Python file gets `name` from: (module, attribute); ('', '') if not imported."""
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return "", ""
    head, _, tail = name.partition(".")
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                if (a.asname or a.name) == head:
                    return node.module, ".".join(x for x in (a.name, tail) if x)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if (a.asname or a.name.split(".")[0]) == head and tail:
                    return (a.name if a.asname else head), tail
    return "", ""


def _prefer(hits: list[dict], module: str, here: Path | None) -> list[dict]:
    """Imported module's file first, then the current file, then the rest."""
    mod_tail = module.replace(".", "/") if module else ""
    def key(h):
        f = str(h["file"].with_suffix(""))
        return (h["rank"], 0 if mod_tail and (f.endswith("/" + mod_tail) or f.endswith(mod_tail + "/__init__")) else
                1 if here and h["file"] == here else 2, len(h["file"].parts))
    return sorted(hits, key=key)


def _python_for(root: Path | None) -> str:
    for d in ("venv", ".venv", "env"):
        if root and (p := root / d / "bin" / "python").exists():
            return str(p)
    return shutil.which("python3") or "python3"


_INSPECT = """
import importlib, inspect, json, sys
mod, attr = sys.argv[1], sys.argv[2]
try:
    obj = importlib.import_module(mod)
    for part in [p for p in attr.split('.') if p]:
        obj = getattr(obj, part)
    obj = inspect.unwrap(obj)
    try:
        f = inspect.getsourcefile(obj); line = inspect.getsourcelines(obj)[1]
    except (TypeError, OSError):
        f, line = None, 0
    if not f or f.startswith('<'):  # frozen stdlib modules (posixpath in 3.12): the .py file is still there
        m = sys.modules.get(getattr(obj, '__module__', '') or '')
        f = getattr(m, '__file__', None)
        line = getattr(getattr(obj, '__code__', None), 'co_firstlineno', 0) if f else 0
    try:
        sig = str(inspect.signature(obj))
    except (TypeError, ValueError):
        sig = ''
    print(json.dumps({'file': f, 'line': line, 'sig': sig}))
except Exception as e:
    print(json.dumps({'error': type(e).__name__ + ': ' + str(e)[:150]}))
"""


def library(module: str, attr: str, root: Path | None) -> dict:
    """{file, line, sig} of an installed library's function, using the project's Python; {error} if not found."""
    try:
        r = subprocess.run([_python_for(root), "-I", "-c", _INSPECT, module, attr], capture_output=True, text=True,
                           timeout=15, cwd=str(root) if root else None)
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as e:
        return {"error": str(e)[:150]}


def block(path: Path, line: int) -> str:
    """The whole definition starting at line (Python: exact via ast; others: indentation / braces)."""
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return ""
    i = max(0, line - 1)
    if path.suffix == ".py":
        try:
            for node in ast.walk(ast.parse("\n".join(lines))):
                if getattr(node, "lineno", None) == line and hasattr(node, "end_lineno") and isinstance(
                        node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign)):
                    start = min([d.lineno for d in getattr(node, "decorator_list", [])] + [line]) - 1
                    return "\n".join(lines[start:min(node.end_lineno, start + MAX_BLOCK)])
        except (SyntaxError, ValueError):
            pass
    if "{" in lines[i] or (i + 1 < len(lines) and lines[i + 1].strip().startswith("{")):
        depth, out = 0, []
        for ln in lines[i:i + MAX_BLOCK]:
            out.append(ln)
            depth += ln.count("{") - ln.count("}")
            if depth <= 0 and "{" in "".join(out):
                break
        return "\n".join(out)
    base = len(lines[i]) - len(lines[i].lstrip())
    out = [lines[i]]
    for ln in lines[i + 1:i + MAX_BLOCK]:
        if ln.strip() and len(ln) - len(ln.lstrip()) <= base:
            break
        out.append(ln)
    return "\n".join(out).rstrip()


def open_in_editor(path: Path, line: int) -> bool:
    """Open path at line in the running VS Code window."""
    code = shutil.which("code")
    if not code:
        return False
    try:
        subprocess.Popen([code, "-r", "-g", f"{path}:{line}"], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def _rel(p: Path, root: Path | None) -> str:
    try:
        return str(p.relative_to(root)) if root else str(p)
    except ValueError:
        return str(p)


def find(selection: str, root: Path | None, here: Path | None) -> dict:
    """Where the highlighted name is defined: {name, file, line, code, others, where} or {error}."""
    name = name_from(selection)
    if not name:
        return {"error": "Highlight the function or class name in VS Code first, then ask again."}
    short = name.rsplit(".", 1)[-1]
    src = ""
    if here and here.suffix == ".py" and here.is_file():
        src = here.read_text(errors="replace")
    module, attr = _imported_from(name, src) if src else ("", "")
    if not module and "." in name:  # 'np.array' / 'json.dumps' even without an import line in this file
        module, attr = name.split(".", 1)
    hits = _prefer(search(short, root), module, here) if root else []
    if here and not hits:  # no folder open: at least the current file
        hits = [h for h in search(short, here.parent) if h["file"] == here]
    tail = module.replace(".", "/")
    top = module.split(".")[0]
    in_project = bool(module) and (any(str(h["file"].with_suffix("")).endswith(("/" + tail, tail + "/__init__"))
                                       for h in hits) or bool(root and ((root / top).is_dir() or (root / f"{top}.py").is_file())))
    info: dict = {}
    if module and not in_project:  # imported from an installed library: its code, not a same-named project function
        info = library(module, attr, root)
        if info.get("file"):
            p = Path(info["file"])
            return {"name": short, "file": p, "line": info["line"] or 1, "code": block(p, info["line"] or 1),
                    "others": [], "where": f"library {module}", "sig": info.get("sig", "")}
    if hits:
        h = hits[0]
        return {"name": short, "file": h["file"], "line": h["line"], "code": block(h["file"], h["line"]),
                "others": hits[1:4], "where": "project"}
    if module:
        if info and "error" not in info:
            return {"error": f"{name} comes from {module}, but it's built in C, so there's no Python code to open."
                             + (f" It takes {short}{info['sig']}." if info.get("sig") else "")}
    if root and (near := similar(short, root)):  # no 'rate_limit', but the class RateLimiter exists (11-04: it just
        best = near[0]  # said "couldn't find"): the closest real names, the surest one opened like a hit
        if best["score"] >= 0.88:
            return {"name": best["name"], "file": best["file"], "line": best["line"],
                    "code": block(best["file"], best["line"]), "others": [], "where": f"closest to '{short}'"}
        return {"error": f"There's no {short} in {root.name}. Closest: " + "; ".join(
            f"{n['name']} ({n['kind']}, {_rel(n['file'], root)}:{n['line']})" for n in near[:3]) + ". Say 'find <name>'."}
    return {"error": f"I couldn't find where {short} is defined"
                     + (f" in {root.name}" if root else "") + ". Is it from a library that isn't imported in this file?"}


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def similar(name: str, root: Path, limit: int = 5) -> list[dict]:
    """The project's functions / classes whose names are closest to `name` (spelling, case and underscores aside:
    rate_limit ~ RateLimiter): [{name, kind, file, line, score}]."""
    import difflib
    rg = shutil.which("rg")
    if not rg or not name or not root.is_dir():
        return []
    cmd = [rg, "-n", "--no-heading", "--color", "never", "--max-filesize", "2M", "-g", "*.py", "-g", "*.js", "-g", "*.ts"]
    for d in SKIP:
        cmd += ["-g", f"!{d}/"]
    cmd += ["-e", r"^\s*(?:async\s+)?(?:def|class|function)\s+[A-Za-z_]\w*", "--", str(root)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    want, found = _key(name), []
    for ln in out.splitlines()[:20000]:
        f, _, rest = ln.partition(":")
        num, _, text = rest.partition(":")
        m = re.search(r"(def|class|function)\s+([A-Za-z_]\w*)", text)
        if not m or not num.isdigit():
            continue
        k = _key(m.group(2))
        score = difflib.SequenceMatcher(None, want, k).ratio()
        if want and (want in k or k in want) and min(len(k), len(want)) >= 4:
            score = max(score, 0.8 + 0.2 * min(len(k), len(want)) / max(len(k), len(want)))
        if score >= 0.72:
            found.append({"name": m.group(2), "kind": "class" if m.group(1) == "class" else "function",
                          "file": Path(f), "line": int(num), "score": round(score, 3)})
    found.sort(key=lambda x: -x["score"])
    out_, seen = [], set()
    for x in found:
        if (x["name"], str(x["file"])) not in seen:
            seen.add((x["name"], str(x["file"])))
            out_.append(x)
    return out_[:limit]


def go(selection: str, root: Path | None, here: Path | None, open_it: bool = True) -> str:
    r = find(selection, root, here)
    if "error" in r:
        return r["error"]
    where = _rel(r["file"], root)
    opened = open_in_editor(r["file"], r["line"]) if open_it else False
    lines = r["code"].count("\n") + 1 if r["code"] else 0
    msg = (f"{r['name']} is in {where}, line {r['line']}" + (f" ({r['where']})" if r["where"] != "project" else "")
           + (f", {lines} lines" if lines > 1 else "") + ". "
           + ("I opened it in VS Code." if opened else "Here is its code:"))
    if r["others"]:
        msg += " Also defined in: " + ", ".join(f"{_rel(o['file'], root)}:{o['line']}" for o in r["others"]) + "."
    return msg if opened else f"{msg}\n\n```\n{r['code']}\n```"
