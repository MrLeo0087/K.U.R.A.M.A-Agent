"""run_tests: run pytest -q in a project and report counts plus the first failure (safe).
A timeout over 30 s runs the suite as a background job instead of blocking the conversation."""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

from jarvis.core.registry import tool
from jarvis.tools.interactive import _proc

FOREGROUND_MAX_S = 30
MAX_TIMEOUT_S = 1800
COUNT_RE = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?)")
HEADER_RE = re.compile(r"^_{3,} (.+?) _{3,}$")


def find_python(start: Path) -> tuple[str, Path]:
    """(python3 to use, working dir): the nearest venv/.venv up to 4 levels up, else KURAMA's own."""
    for d in [start, *list(start.parents)[:4]]:
        for v in ("venv", ".venv"):
            py = d / v / "bin" / "python3"
            if py.exists():
                return str(py), d
    own = Path(sys.executable).with_name("python3")
    return (str(own) if own.exists() else shutil.which("python3") or "python3"), start


def first_failure(out: str, limit: int = 520) -> str:
    """First FAILURES/ERRORS block, trimmed to keep its header and its last (assertion) lines."""
    lines, block, inside = out.splitlines(), [], False
    for ln in lines:
        if HEADER_RE.match(ln.strip()):
            if inside:
                break
            inside = True
        elif inside and (ln.startswith("=====") or ln.startswith("-- Captured")):
            break
        if inside:
            block.append(ln)
    if not block:
        return ""
    text = "\n".join(block)
    return text if len(text) <= limit else text[:120] + "\n...\n" + text[-(limit - 125):]


def summarize(out: str, code: int) -> str:
    counts: dict[str, int] = {}
    tail = "\n".join(out.strip().splitlines()[-3:])
    for n, word in COUNT_RE.findall(tail):
        counts[word.rstrip("s") if word.startswith(("error", "warning")) else word] = int(n)
    if code == 5:
        return "no tests collected"
    parts = ", ".join(f"{n} {w}" for w, n in counts.items() if w != "warning")
    if code == 0:
        return f"PASS: {parts or 'all passed'}"
    head = f"FAIL: {parts or f'pytest exit code {code}'}"
    fail = first_failure(out)
    if not fail:
        fail = "\n".join(ln for ln in out.splitlines() if ln.startswith(("FAILED", "ERROR", "E ")))[:520]
    return _proc.clip(f"{head}\nfirst failure:\n{fail}" if fail else head)


def build(path: str, pattern: str) -> tuple[list[str], Path]:
    target = Path(path or ".").expanduser().resolve()
    if not target.exists():
        raise _proc.ProcError(f"not found: {target}")
    py, cwd = find_python(target if target.is_dir() else target.parent)
    argv = [py, "-m", "pytest", "-q", "--tb=short", "--color=no", "-p", "no:cacheprovider", str(target)]
    if pattern:
        argv += ["-k", pattern]
    return argv, cwd


def execute(argv: list[str], cwd: Path, timeout: float, cancel=None) -> str:
    try:
        cp = _proc.run(argv, cwd=cwd, timeout=timeout, cancel=cancel)
    except _proc.ProcError as e:
        if "timed out" in str(e):
            return f"tests timed out after {int(timeout)}s (ask again with a longer timeout to run in the background)"
        raise
    if cp.returncode == 4 or (cp.returncode != 0 and "No module named pytest" in cp.stderr):
        return f"error: pytest unavailable or bad arguments: {(cp.stderr or cp.stdout).strip()[-200:]}"
    return summarize(cp.stdout + ("\n" + cp.stderr if cp.returncode == 2 else ""), cp.returncode)


def _background(argv: list[str], cwd: Path, timeout: float, label: str) -> str:
    from jarvis.core import jobs, writer

    def job(ctx) -> str:
        ctx.progress("running pytest")
        result = execute(argv, cwd, timeout, cancel=ctx.job.cancel_event)
        ctx.progress(result.splitlines()[0][:120])
        path = writer.output_path(ctx.job.title)
        path.write_text(f"# {ctx.job.title}\n\n```\n{result}\n```\n", encoding="utf-8")
        return str(path)

    j = jobs.get_manager().submit(f"tests {label}", "tests", job, " ".join(argv[3:]))
    return f"started job #{j.id}: running tests for {label} in the background (up to {int(timeout)}s)"


@tool(group="dev", safety="safe", description="Run pytest on a project/file; returns pass/fail counts and the first failure.")
def run_tests(path: str = ".", pattern: str = "", timeout: int = FOREGROUND_MAX_S) -> str:
    """Run tests.

    Args:
        path: Project folder or test file (default: current folder).
        pattern: Only tests matching this -k expression.
        timeout: Seconds; above 30 the suite runs as a background job.
    """
    argv, cwd = build(path, pattern)
    timeout = max(5, min(int(timeout or FOREGROUND_MAX_S), MAX_TIMEOUT_S))
    if timeout > FOREGROUND_MAX_S:
        return _background(argv, cwd, timeout, Path(argv[-1] if not pattern else argv[-3]).name)
    return execute(argv, cwd, timeout)
