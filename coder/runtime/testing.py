"""Tests: "write tests for this project" (pytest files for its Python modules, one call each, checked and run) and
"make the tests pass" (run them, send only the failures and the code they point at to the smart model, fix the
code, run again; at most settings.MAX_FIX_ROUNDS). Every change is backed up (undo)."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from coder.agent import fixloop
from coder.builder import writer
from coder.core import safety, settings
from coder.core.run import FileSpec, Run, new
from coder.llm import models
from coder.memory import repomap

_SYS = ("You write pytest tests for ONE module of a project: real behaviour (normal cases, edge cases, errors), no "
        "network, no GUI windows (mock pygame / tkinter / input()), fast. Import the module the way the project "
        "does. Reply with ONLY the test file in one fenced code block.")


def python_for(root: Path) -> str:
    """The project's own .venv python when it has pytest, else KURAMA's."""
    for v in (root / ".venv", root / "venv"):
        py = v / "bin" / "python"
        if py.exists() and subprocess.run([str(py), "-c", "import pytest"], capture_output=True).returncode == 0:
            return str(py)
    return sys.executable


def run_tests(root: Path, timeout: float = 300) -> tuple[bool, str]:
    """(passed, output tail). Python projects: pytest -x -q; a JS project with node_modules: npm test."""
    if (root / "package.json").exists() and (root / "node_modules").exists():
        cmd = ["npm", "test", "--silent"]
    else:
        cmd = [python_for(root), "-m", "pytest", "-x", "-q", "--no-header", "-p", "no:cacheprovider"]
    try:
        r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=timeout,
                           env={**__import__("os").environ, "SDL_VIDEODRIVER": "dummy", "MPLBACKEND": "Agg",
                                "PYTHONDONTWRITEBYTECODE": "1"})  # (a stale .pyc of a just-fixed file of the same
        #                            size, written in the same second, ran the OLD code)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"the tests didn't finish ({e})"
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode == 5:  # pytest: no tests collected
        return False, "no tests found"
    return r.returncode == 0, out[-4000:]


def modules(root: Path) -> list[Path]:
    return [p for p in repomap.files(root) if p.suffix == ".py" and not p.name.startswith("test_")
            and "tests" not in p.parts and p.name not in ("setup.py", "conftest.py") and p.stat().st_size > 15]


def write(root: Path, only: str = "") -> tuple[Run, list[str]]:
    """Test files for the project's modules (or the one named). Returns the run and the written test paths."""
    run = new(f"tests for {root.name}", root)
    run.kind = "add"
    targets = [p for p in modules(root) if not only or only in p.name][:6]
    written = []
    for m in targets:
        rel = m.relative_to(root).as_posix()
        test_rel = f"tests/test_{m.stem}.py"
        run.files.append(FileSpec(test_rel, f"pytest tests for {rel}", [rel], "hard"))
        user = (f"Project map:\n{repomap.text(root, 1500)}\n\n--- {rel} ---\n"
                f"{m.read_text(encoding='utf-8', errors='replace')[:6000]}\n\nWrite `{test_rel}`.")
        body = writer.code_of(models.ask(run, "hard", _SYS, user, 2500))
        if body.strip():
            safety.write(run, test_rel, body)
            run.written.append(test_rel)
            written.append(test_rel)
    if written and not (root / "tests" / "conftest.py").exists() and not (root / "conftest.py").exists():
        safety.write(run, "conftest.py", "# lets the tests import the project's modules\n")
        run.written.append("conftest.py")
    return run, written


def _blamed(root: Path, output: str) -> list[str]:
    """The project files a failure points at (source files first, then the tests)."""
    seen: list[str] = []
    for m in re.finditer(r"([\w./-]+\.py):(\d+)", output):
        p = Path(m.group(1))
        p = p if p.is_absolute() else root / p
        try:
            rel = p.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            continue  # a library's file
        if rel not in seen and (root / rel).exists():
            seen.append(rel)
    for rel in [r for r in seen if Path(r).name.startswith("test_")]:  # a failing assert names only the test: the
        for mod in repomap.local_imports(root / rel):  # code it tests (its local imports) is the likely culprit
            top = mod.lstrip(".").replace(".", "/")
            for cand in (f"{top}.py", f"src/{top}.py", f"{top}/__init__.py"):
                if (root / cand).exists() and cand not in seen:
                    seen.append(cand)
    return sorted(seen, key=lambda r: (Path(r).name.startswith("test_"), r))


def make_pass(root: Path, on_round=None) -> tuple[bool, str, Run]:
    """Run the tests; fix the code they blame; again (max rounds). Returns (passed, last output, run)."""
    run = new(f"make the tests pass in {root.name}", root)
    run.kind = "add"
    ok, out = run_tests(root)
    for i in range(settings.MAX_FIX_ROUNDS):
        if ok or out == "no tests found":
            break
        blamed = _blamed(root, out)[:2]
        if not blamed:
            break
        if on_round:
            on_round(i + 1, blamed)
        fail = re.sub(r"\n{3,}", "\n\n", out)[-2500:]
        problems = [f"{rel}: the tests fail:\n{fail}" for rel in blamed[:1]]
        if not fixloop.fix_round(run, problems):
            break
        ok, out = run_tests(root)
    return ok, out, run
