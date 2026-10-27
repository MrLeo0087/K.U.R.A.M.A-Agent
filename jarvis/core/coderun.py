"""Run the highlighted code and show what it prints (0 tokens): 'run this code' / '/run'.

Python: the file's imports + function/class definitions are put in front of the selection (so `print(add(1, 2))`
works when add() is defined above), run with the project's own Python in a temp folder (the project folder on the
import path), 20 s / 1 GB / no keyboard input. JavaScript: node. On an error KURAMA remembers it for 3 minutes:
'fix it' sends the code + the error to the code fixer (1 call, shown first, replaced only after yes).
"""
from __future__ import annotations

import ast
import os
import re
import resource
import subprocess
import tempfile
import time
from pathlib import Path

from jarvis.core import codenav

TIMEOUT_S = 20
MEM_MB = 1024
OUT_MAX = 1800
FIX_TTL_S = 180
_last_error: dict = {}


def _limits() -> None:  # in the child: no runaway memory/CPU, its own process group
    resource.setrlimit(resource.RLIMIT_AS, (MEM_MB * 2 ** 20, MEM_MB * 2 ** 20))
    resource.setrlimit(resource.RLIMIT_CPU, (TIMEOUT_S, TIMEOUT_S + 1))
    os.setsid()


def _context(selection: str, here: Path | None) -> tuple[str, int]:
    """(imports + defs of the open file that the selection doesn't already contain, their line count)."""
    if not here or here.suffix != ".py" or not here.is_file():
        return "", 0
    src = here.read_text(errors="replace")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return "", 0
    try:
        sel_names = {n.name for n in ast.parse(selection).body if hasattr(n, "name")}
    except SyntaxError:
        sel_names = set()
    lines = src.splitlines()
    keep = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name not in sel_names):
            start = min([d.lineno for d in getattr(node, "decorator_list", [])] + [node.lineno]) - 1
            keep.append("\n".join(lines[start:node.end_lineno]))
    ctx = "\n".join(keep)
    return (ctx + "\n\n", ctx.count("\n") + 2) if ctx else ("", 0)


def only_definitions(selection: str) -> list[str]:
    """Names, when the selection only defines things (nothing would run); [] otherwise."""
    try:
        body = ast.parse(selection).body
    except SyntaxError:
        return []
    if body and all(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom))
                    for n in body):
        return [n.name for n in body if hasattr(n, "name")]
    return []


def _clean(out: str, script: Path, offset: int) -> str:
    """Tracebacks point at the user's selection lines, not at our temp file."""
    def line(m):
        n = int(m.group(1)) - offset
        return f"line {n} of your selection" if n > 0 else "line in the file's definitions"
    out = re.sub(rf'File "{re.escape(str(script))}", line (\d+)', lambda m: line(m), out)
    return out.strip()


def run(selection: str, root: Path | None, here: Path | None, whole: bool = False) -> str:
    """whole=True: the saved file itself, run in its own folder (its relative paths like data.csv work)."""
    code = (selection or "").strip("\n")
    if not code.strip():
        return "Highlight the code you want to run, then say 'run this'."
    lang = "js" if here and here.suffix in (".js", ".mjs", ".cjs") else "py"
    if lang == "py":
        import textwrap
        code = textwrap.dedent(code)
        if names := only_definitions(code):
            return (f"That only defines {', '.join(names)}, so nothing would run. Highlight a line that calls it, or "
                    f"say 'how can I use this function' and I'll write the call for you.")
    ctx, offset = _context(code, here) if lang == "py" and not whole else ("", 0)
    with tempfile.TemporaryDirectory(prefix="kurama-run-") as d:
        script = Path(d) / ("snippet.py" if lang == "py" else "snippet.js")
        script.write_text(ctx + code + "\n", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not re.search(r"KEY|TOKEN|SECRET|PASS", k)}
        if lang == "py":
            env["PYTHONPATH"] = os.pathsep.join(str(p) for p in {root, here.parent if here else None} if p)
            cmd = [codenav._python_for(root), str(script)]
        else:
            cmd = ["node", str(script)]
        t0 = time.time()
        try:
            r = subprocess.run(cmd, cwd=str(here.parent) if whole and here else d, capture_output=True, text=True, timeout=TIMEOUT_S, env=env,
                               stdin=subprocess.DEVNULL, preexec_fn=_limits)
        except subprocess.TimeoutExpired:
            return f"It was still running after {TIMEOUT_S} s, so I stopped it (an endless loop or a slow job?)."
        except OSError as e:
            return f"I couldn't run it: {e}"
        ms = int((time.time() - t0) * 1000)
        out = (r.stdout or "").rstrip()
        err = _clean(r.stderr or "", script, offset)
    if r.returncode == 0:
        _last_error.clear()
        if not out:
            return f"It ran without errors in {ms} ms, but printed nothing."
        return f"It ran in {ms} ms. Output:\n```\n{out[-OUT_MAX:]}\n```"
    if "EOFError" in err and "input" in err:
        return "It stopped at input(): it wants you to type something. Run it in the terminal for that part."
    last = err.strip().splitlines()[-1] if err.strip() else f"exit code {r.returncode}"
    _last_error.update(code=code, error=err[-1500:], at=time.time())
    return (f"❌ It failed: {last}\n```\n{(out + chr(10) if out else '')}{err[-OUT_MAX:]}\n```\n"
            "Say 'fix it' and I'll fix the code.")


def pending_fix() -> dict | None:
    """The last failed run, if it is recent (for 'fix it')."""
    if _last_error and time.time() - _last_error.get("at", 0) < FIX_TTL_S:
        return dict(_last_error)
    return None


def take_fix() -> str:
    """The request for the code fixer, and forget the error."""
    e = pending_fix() or {}
    _last_error.clear()
    return f"Fix this code so it runs without the error. Error:\n{e.get('error', '')}"
