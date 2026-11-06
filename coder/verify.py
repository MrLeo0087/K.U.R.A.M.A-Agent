"""Check the written files without the AI and without running the program (0 tokens):
  Python      ruff format (tidy), then compile + ruff's error rules (syntax, undefined names, bad imports)
  JavaScript  node --check (as a script, else as an ES module)
  JSON        parses
Problems come back as lines "file:line: message" for the fix step. TypeScript / JSX are checked by the project's
own build (`npm run build`) once its packages are installed: the README says so."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from coder.run import Run


def _ruff() -> str | None:
    p = Path(sys.executable).parent / "ruff"
    return str(p) if p.exists() else shutil.which("ruff")


def _run(cmd: list[str], cwd: Path, timeout: float = 60) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return 0, f"(check skipped: {e})"


def python(run: Run, files: list[Path]) -> list[str]:
    if not files:
        return []
    out: list[str] = []
    rel = [str(p.relative_to(run.root)) for p in files]
    if ruff := _ruff():
        _run([ruff, "format", "--quiet", *rel], run.root)
    for p in files:
        code, msg = _run([sys.executable, "-m", "py_compile", str(p)], run.root)
        if code:
            out.append(f"{p.relative_to(run.root)}: {msg.strip().splitlines()[-1][:300]}")
    if ruff and not out:
        code, msg = _run([ruff, "check", "--no-cache", "--quiet", "--output-format", "concise",
                          "--select", "E9,F63,F7,F82,F401", "--ignore", "F401", *rel], run.root)
        out += [ln.strip()[:300] for ln in msg.splitlines() if re.match(r"^\S+:\d+:\d+:", ln.strip())][:12]
    return out


def javascript(run: Run, files: list[Path]) -> list[str]:
    if not files or not shutil.which("node"):
        return []
    out = []
    for p in files:
        code, msg = _run(["node", "--check", str(p)], run.root, 20)
        if code and re.search(r"import|export|module", msg):  # an ES module: check it as one
            with tempfile.TemporaryDirectory() as d:
                m = Path(d) / (p.stem + ".mjs")
                m.write_text(p.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
                code, msg = _run(["node", "--check", str(m)], run.root, 20)
                msg = msg.replace(str(m), str(p.relative_to(run.root)))
        if code:
            first = next((ln for ln in msg.splitlines() if "Error" in ln), msg.strip().splitlines()[-1] if msg.strip() else "")
            where = re.search(r":(\d+)\s*$", msg.splitlines()[0]) if msg.strip() else None
            out.append(f"{p.relative_to(run.root)}:{where.group(1) if where else '?'}: {first.strip()[:250]}")
    return out


def data(run: Run, files: list[Path]) -> list[str]:
    out = []
    for p in files:
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except ValueError as e:
            out.append(f"{p.relative_to(run.root)}: invalid JSON ({e})")
    return out


def check(run: Run, only: list[str] | None = None) -> list[str]:
    """The written files (or `only` these), checked."""
    paths = [run.root / r for r in (only if only is not None else run.written) if (run.root / r).is_file()]
    return (python(run, [p for p in paths if p.suffix == ".py"])
            + javascript(run, [p for p in paths if p.suffix in (".js", ".mjs")])
            + data(run, [p for p in paths if p.suffix == ".json" and p.name != "tsconfig.json"]))
