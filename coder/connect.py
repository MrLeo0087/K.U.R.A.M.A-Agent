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


def _sig(fn) -> tuple[list[str], bool, bool, int]:
    """(parameter names, has *args, has **kwargs, how many are required) of a def (self/cls dropped)."""
    a = fn.args
    names = [x.arg for x in a.posonlyargs + a.args + a.kwonlyargs]
    if names[:1] in (["self"], ["cls"]):
        names = names[1:]
    pos = [x.arg for x in a.posonlyargs + a.args if x.arg not in ("self", "cls")]
    required = len(pos) - len(a.defaults)
    return names, a.vararg is not None, a.kwarg is not None, max(0, required)


def _py_modules(run: Run) -> dict[str, tuple[set[str], dict]]:
    """module name -> (its top-level names, {function / class name: signature})."""
    import ast
    out: dict[str, tuple[set[str], dict]] = {}
    for p in repomap.files(run.root):
        if p.suffix != ".py":
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        names: set[str] = set()
        sigs: dict = {}
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(n.name)
                sigs[n.name] = _sig(n)
            elif isinstance(n, ast.ClassDef):
                names.add(n.name)
                init = next((m for m in n.body if isinstance(m, ast.FunctionDef) and m.name == "__init__"), None)
                if init is not None and not n.bases:  # (a subclass may take its parent's arguments)
                    sigs[n.name] = _sig(init)
            elif isinstance(n, (ast.Assign, ast.AnnAssign)):
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    names |= {x.id for x in ast.walk(t) if isinstance(x, ast.Name)}
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                names |= {(a.asname or a.name).split(".")[0] for a in n.names}
            elif isinstance(n, (ast.If, ast.Try)):  # names defined under `if`/`try` at the top level count too
                names |= {x.id for x in ast.walk(n) if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store)}
                names |= {x.name for x in ast.walk(n) if isinstance(x, (ast.FunctionDef, ast.ClassDef))}
        key = p.relative_to(run.root).with_suffix("").as_posix().replace("/", ".")
        out[key] = (names, sigs)
        if p.parent == run.root:
            out[p.stem] = (names, sigs)
    return out


def _call_problem(call, name: str, sig, where: str) -> str:
    params, varargs, varkw, required = sig
    for kw in call.keywords:
        if kw.arg and kw.arg not in params and not varkw:
            return f"{where}: calls {name}({kw.arg}=...), but {name} has no parameter '{kw.arg}' (it takes: {', '.join(params) or 'nothing'})"
    npos = len(call.args)
    starred = any(type(a).__name__ == "Starred" for a in call.args)
    if not varargs and not starred and npos > len(params):
        return f"{where}: calls {name} with {npos} arguments, but it takes {len(params)}"
    given = npos + len([k for k in call.keywords if k.arg])
    if given < required and not starred and not any(k.arg is None for k in call.keywords):
        return f"{where}: calls {name} with {given} arguments, but it needs {required}"
    return ""


def _mine(run: Run) -> list[Path]:
    """The files to check: this run's own (an addition to a big project must not 'fix' the rest of it; 11-06 a
    build inside KURAMA found 21 problems in files it never wrote, and spent tokens on 3 rounds of them)."""
    if run.written:
        return [run.root / w for w in dict.fromkeys(run.written) if (run.root / w).is_file()]
    return repomap.files(run.root)


def _near(mods: dict, p: Path, root: Path) -> dict:
    """Module names as THIS file sees them: a module in its own folder wins over one with the same name elsewhere
    ('from constants import X' in games/rps/ui.py is games/rps/constants.py)."""
    near = dict(mods)
    pre = p.parent.relative_to(root).as_posix().replace("/", ".")
    for key, v in mods.items():
        if pre != "." and key.startswith(pre + ".") and "." not in key[len(pre) + 1:]:
            near[key[len(pre) + 1:]] = v
    return near


def _py_names(run: Run) -> list[str]:
    """The Python files agree with each other (0 tokens): 'from game import decide' finds decide;
    'import constants as C' then C.FONT_NAME finds FONT_NAME; a call to a project function / class passes
    parameters it really has, and enough of them (11-06: create_choice_buttons(x_center=...) and a missing
    FONT_NAME passed every check, then crashed on the first run)."""
    import ast
    mods_all = _py_modules(run)
    out: list[str] = []
    for p in _mine(run):
        if p.suffix != ".py":
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        rel = p.relative_to(run.root).as_posix()
        mods = _near(mods_all, p, run.root)
        alias: dict[str, str] = {}  # local name -> module
        funcs: dict[str, tuple[str, str]] = {}  # local name -> (module, name there)
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module and not n.level and n.module in mods:
                for a in n.names:
                    if a.name == "*":
                        continue
                    if a.name not in mods[n.module][0]:
                        out.append(f"{rel}: imports {a.name} from {n.module}, which {n.module} doesn't define")
                    else:
                        funcs[a.asname or a.name] = (n.module, a.name)
            elif isinstance(n, ast.Import):
                for a in n.names:
                    if a.name in mods:
                        alias[a.asname or a.name] = a.name
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in alias:
                mod = alias[n.value.id]
                if n.attr not in mods[mod][0]:
                    out.append(f"{rel}:{n.lineno}: uses {n.value.id}.{n.attr}, which {mod}.py doesn't define")
            elif isinstance(n, ast.Call):
                target = None
                if isinstance(n.func, ast.Name) and n.func.id in funcs:
                    target = funcs[n.func.id]
                elif isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id in alias:
                    target = (alias[n.func.value.id], n.func.attr)
                if target and target[1] in mods[target[0]][1]:
                    if why := _call_problem(n, target[1], mods[target[0]][1][target[1]], f"{rel}:{n.lineno}"):
                        out.append(why)
    return list(dict.fromkeys(out))[:20]


def check(run: Run) -> list[str]:
    out: list[str] = []
    planned = {Path(f.path).stem for f in run.files} | {Path(f.path).parts[0] for f in run.files if "/" in f.path}
    for p in _mine(run):
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
