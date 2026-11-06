"""Do the files fit together? (0 tokens) Every <script src>, stylesheet and local image an HTML page names exists;
every relative JS/TS import resolves; every local Python module imported exists. Returns problem lines like
"index.html: links style.css, which doesn't exist" (the fix step gets these)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from coder import repomap
from coder.run import Run

_HTML_REF = re.compile(r"""<(?:script|link|img|source)\b[^>]*?\b(?:src|href)\s*=\s*["']([^"'#?]+)["']""", re.I)
_JS_EXT = ("", ".js", ".mjs", ".jsx", ".ts", ".tsx", "/index.js", "/index.ts", "/index.tsx", "/index.jsx")


def _html(p: Path, root: Path) -> list[str]:
    out = []
    src = p.read_text(encoding="utf-8", errors="replace")
    for ref in _HTML_REF.findall(src):
        if re.match(r"^(?:[a-z]+:|//|data:)", ref, re.I):
            continue  # a web address
        target = (root / ref.lstrip("/")) if ref.startswith("/") else (p.parent / ref)
        if not target.exists() and not (root / "public" / ref.lstrip("/")).exists():
            out.append(f"{p.relative_to(root)}: links {ref}, which doesn't exist")
    return out


def _js(p: Path, root: Path) -> list[str]:
    out = []
    for ref in repomap.local_imports(p):
        base = (p.parent / ref)
        if not any(Path(str(base) + ext).exists() for ext in _JS_EXT) and not base.with_suffix("").exists():
            out.append(f"{p.relative_to(root)}: imports {ref}, which doesn't exist")
    return out


def _py(p: Path, root: Path, planned: set[str]) -> list[str]:
    """A local module that is imported but missing: one the plan meant as a project file (planned stems) or that
    names a folder of the project; pip packages are never reported."""
    out = []
    std = set(sys.stdlib_module_names)
    for mod in repomap.local_imports(p):
        if mod.startswith("."):
            continue
        top = mod.split(".")[0]
        if top in std or top not in planned:
            continue
        if not any((d / f"{top}.py").exists() or (d / top / "__init__.py").exists() or (d / top).is_dir()
                   for d in (p.parent, root, root / "src")):
            out.append(f"{p.relative_to(root)}: imports {mod}, which isn't in the project")
    return out


_JS_ID = re.compile(r"""getElementById\(\s*['"]([\w-]+)['"]""")
_JS_SEL = re.compile(r"""querySelector(?:All)?\(\s*['"]([^'"]+)['"]""")


def _web_names(root: Path) -> tuple[set[str], set[str]]:
    """Every id and class the project's HTML pages have (and classes its scripts add)."""
    ids: set[str] = set()
    classes: set[str] = set()
    for p in repomap.files(root):
        if p.suffix not in (".html", ".js", ".mjs"):
            continue
        src = p.read_text(encoding="utf-8", errors="replace")
        if p.suffix == ".html":
            ids |= set(re.findall(r"""\bid\s*=\s*["']([\w-]+)["']""", src))
            for c in re.findall(r"""\bclass\s*=\s*["']([^"']+)["']""", src):
                classes |= set(c.split())
        else:  # made by the script itself: el.id = 'x', classList.add('x'), className = 'a b', innerHTML templates
            ids |= set(re.findall(r"""\.id\s*=\s*['"]([\w-]+)['"]""", src))
            ids |= set(re.findall(r"""\bid\s*=\s*\\?["']([\w-]+)""", src))
            for c in re.findall(r"""classList\.(?:add|toggle)\(([^)]*)\)""", src):
                classes |= set(re.findall(r"""['"]([\w-]+)['"]""", c))
            for c in re.findall(r"""(?:className\s*=\s*|class\s*=\s*\\?)["'`]([^"'`$]+)""", src):
                classes |= set(c.split())
    return ids, classes


def _web_selectors(run: Run) -> list[str]:
    """A script looking for an id / class no page has ('#result-message' when the page says 'round-result')."""
    pages = [p for p in repomap.files(run.root) if p.suffix == ".html"]
    if not pages:
        return []
    ids, classes = _web_names(run.root)
    out = []
    for p in repomap.files(run.root):
        if p.suffix not in (".js", ".mjs"):
            continue
        src = p.read_text(encoding="utf-8", errors="replace")
        wanted = {("#", x) for x in _JS_ID.findall(src)}
        for sel in _JS_SEL.findall(src):
            for kind, name in re.findall(r"([#.])([\w-]+)", sel):
                wanted.add((kind, name))
        for kind, name in sorted(wanted):
            if (kind == "#" and name not in ids) or (kind == "." and name not in classes):
                out.append(f"{p.relative_to(run.root)}: looks for {kind}{name}, which no page or script has")
    return out[:15]


def _py_names(run: Run) -> list[str]:
    """'from game import Game, decide' where game.py has no `decide`: the two files disagree (0 tokens)."""
    import ast
    defined: dict[str, set[str]] = {}
    for p in repomap.files(run.root):
        if p.suffix != ".py":
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        names: set[str] = set()
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(n.name)
            elif isinstance(n, (ast.Assign, ast.AnnAssign)):
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    names |= {x.id for x in ast.walk(t) if isinstance(x, ast.Name)}
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                names |= {(a.asname or a.name).split(".")[0] for a in n.names}
        defined[p.relative_to(run.root).with_suffix("").as_posix().replace("/", ".")] = names
        defined.setdefault(p.stem, names)
    out = []
    for p in repomap.files(run.root):
        if p.suffix != ".py":
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module and not n.level and n.module in defined:
                missing = [a.name for a in n.names if a.name != "*" and a.name not in defined[n.module]]
                if missing:
                    out.append(f"{p.relative_to(run.root)}: imports {', '.join(missing)} from {n.module}, "
                               f"which {n.module} doesn't define")
    return out


def check(run: Run) -> list[str]:
    out: list[str] = []
    planned = {Path(f.path).stem for f in run.files} | {Path(f.path).parts[0] for f in run.files if "/" in f.path}
    for p in repomap.files(run.root):
        try:
            if p.suffix == ".html":
                out += _html(p, run.root)
            elif p.suffix in (".js", ".mjs", ".jsx", ".ts", ".tsx"):
                out += _js(p, run.root)
            elif p.suffix == ".py":
                out += _py(p, run.root, planned)
        except OSError:
            continue
    try:
        out += _web_selectors(run) + _py_names(run)
    except OSError:
        pass
    return out
