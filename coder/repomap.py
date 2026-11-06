"""A project's map without the AI: its files, and in each the functions, classes, exports and local imports. The
planner and the writer get this small map instead of whole files (a big project costs a few hundred tokens)."""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

from coder import settings

CODE = {".py", ".js", ".mjs", ".jsx", ".ts", ".tsx", ".html", ".css", ".scss", ".vue", ".svelte", ".json", ".md", ".toml",
        ".go", ".rs", ".java", ".kt", ".php", ".rb", ".c", ".h", ".cpp", ".cs", ".swift", ".dart", ".sql", ".sh", ".yml",
        ".yaml"}
_OTHER_DEF = re.compile(r"^\s*(?:pub\s+)?(?:func|fn|def|class|interface|struct|type)\s+(?:\([^)]*\)\s*)?(\w+)", re.M)
_JS_DEF = re.compile(r"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?(?:function\s*\*?\s*(\w+)|class\s+(\w+)|"
                     r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>)", re.M)
_JS_IMPORT = re.compile(r"""(?:import\s[^'"]*?from\s*|import\s*\(\s*|require\s*\(\s*)['"](\.{1,2}/[^'"]+)['"]""")


def files(root: Path, limit: int = 300) -> list[Path]:
    out: list[Path] = []
    for d, dirs, names in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in settings.SKIP_DIRS and not x.startswith(".")
                         and not (x == "coder" and Path(d).name == "data"))  # (KURAMA's own run backups)
        for n in sorted(names):
            p = Path(d) / n
            if p.suffix.lower() in CODE and p.stat().st_size < 400_000:
                out.append(p)
                if len(out) >= limit:
                    return out
    return out


def symbols(p: Path) -> list[str]:
    try:
        src = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if p.suffix == ".py":
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return ["(syntax error)"]
        out = []
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append(f"def {n.name}()")
            elif isinstance(n, ast.ClassDef):
                meths = [m.name for m in n.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))][:8]
                out.append(f"class {n.name}({', '.join(meths)})")
        return out[:20]
    if p.suffix in (".js", ".mjs", ".jsx", ".ts", ".tsx", ".vue", ".svelte"):
        return [f"{'class ' if m.group(2) else ''}{m.group(1) or m.group(2) or m.group(3)}" for m in _JS_DEF.finditer(src)][:20]
    if p.suffix in (".go", ".rs", ".java", ".kt", ".php", ".rb", ".cs", ".swift", ".dart"):
        return _OTHER_DEF.findall(src)[:20]
    if p.suffix == ".html":
        links = re.findall(r"""(?:src|href)\s*=\s*["']([^"':#?]+\.(?:js|css|mjs))["']""", src)
        return [f"uses {x}" for x in links][:10]
    return []


def text(root: Path, limit_chars: int = 4000) -> str:
    """'src/App.tsx: App, useGame | src/game.ts: class Game(play, reset)' ... (cut at limit_chars)."""
    lines = []
    for p in files(root):
        rel = p.relative_to(root).as_posix()
        syms = symbols(p)
        lines.append(f"{rel}: {', '.join(syms)}" if syms else rel)
    out = "\n".join(lines)
    return out if len(out) <= limit_chars else out[:limit_chars].rsplit("\n", 1)[0] + "\n…"


def local_imports(p: Path) -> list[str]:
    """The local files this file imports (as written: './game', 'utils')."""
    try:
        src = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if p.suffix == ".py":
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return []
        mods = []
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                mods.append(n.module)
            elif isinstance(n, ast.ImportFrom) and n.level:
                mods.append("." * n.level + (n.module or ""))
            elif isinstance(n, ast.Import):
                mods += [a.name for a in n.names]
        return mods
    return _JS_IMPORT.findall(src)
