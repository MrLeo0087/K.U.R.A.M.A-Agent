"""Run a Python project for a few seconds to see that it starts (0 tokens): the checks that read the code can't see
everything (11-06: a game passed them all and crashed on its first frame). The program runs in its folder with the
project's own .venv when it has one, no screen or sound (SDL dummy drivers) and no keyboard input, for SMOKE_S
seconds: still running = it starts; a crash = a problem line for the fix step. A missing package is not a code
problem: it is reported as "needs: pygame" (setup() installs the requirements, after the owner's yes).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from coder.run import Run

SMOKE_S = 6.0
_MISSING = re.compile(r"ModuleNotFoundError: No module named '([\w.]+)'")


def python_of(root: Path) -> str:
    for d in (".venv", "venv", "env"):
        if (root / d / "bin" / "python").exists():
            return str(root / d / "bin" / "python")
    return sys.executable


def entry(run: Run) -> str | None:
    """The file that starts the program: from the run command ('python main.py'), else a usual name."""
    if m := re.search(r"python3?\s+([\w./-]+\.py)", run.run_cmd or ""):
        if (run.root / m.group(1)).is_file():
            return m.group(1)
    for name in ("main.py", "app.py", "game.py", "run.py", "__main__.py"):
        if (run.root / name).is_file():
            return name
    return None


def smoke(run: Run) -> tuple[list[str], list[str]]:
    """(problems, missing packages). Nothing to run (not Python, a web server app) = ([], [])."""
    rel = entry(run)
    if rel is None or re.search(r"\b(?:uvicorn|flask|streamlit|gunicorn)\b", run.run_cmd or ""):
        return [], []
    src = " ".join((run.root / f).read_text(encoding="utf-8", errors="replace") for f in run.written
                   if f.endswith(".py") and (run.root / f).is_file())
    if re.search(r"^\s*(?:import|from)\s+(?:tkinter|PyQt\d|PySide\d|wx|kivy)\b", src, re.M):
        return [], []  # a desktop window would pop up on the owner's screen (no virtual display here): not run
    env = {**os.environ, "SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy", "MPLBACKEND": "Agg",
           "PYGAME_HIDE_SUPPORT_PROMPT": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        p = subprocess.run([python_of(run.root), rel], cwd=run.root, env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=SMOKE_S)
        out, code = (p.stdout or "") + (p.stderr or ""), p.returncode
    except subprocess.TimeoutExpired:
        return [], []  # still running after a few seconds: it starts
    except OSError as e:
        run.note(f"smoke run failed to start: {e}")
        return [], []
    if code == 0 or "Traceback" not in out:
        return [], []
    if m := _MISSING.search(out):
        local = (run.root / f"{m.group(1).split('.')[0]}.py").exists()
        if not local:
            return [], [m.group(1).split(".")[0]]
    if re.search(r"\bEOFError\b", out):  # it waits for typed input (a terminal game): not a bug
        return [], []
    frames = [(f, int(n)) for f, n in re.findall(r'File "([^"]+)", line (\d+)', out)
              if Path(f).resolve().is_relative_to(run.root.resolve())]
    last = out.strip().splitlines()[-1][:250]
    if frames:
        f, n = frames[-1]
        where = Path(f).resolve().relative_to(run.root.resolve()).as_posix()
        return [f"{where}:{n}: crashes when it starts: {last}"], []
    return [f"{rel}: crashes when it starts: {last}"], []


def setup(root: Path) -> tuple[bool, str]:
    """Make .venv (if missing) and install requirements.txt into it. (True, '') or (False, why)."""
    req = root / "requirements.txt"
    if not req.is_file():
        return True, ""
    from coder.github import HEAVY
    if HEAVY.search(req.read_text(encoding="utf-8", errors="replace")):  # no GPU here: never pull torch & co.
        return False, "requirements.txt asks for GPU / deep-learning packages; install those yourself (CPU builds)"
    try:
        if not (root / ".venv" / "bin" / "python").exists():
            r = subprocess.run(["python3", "-m", "venv", ".venv"], cwd=root,
                               capture_output=True, text=True, timeout=180)
            if r.returncode:
                return False, (r.stderr or r.stdout)[-300:]
        r = subprocess.run([str(root / ".venv" / "bin" / "python"), "-m", "pip", "install", "-q", "-r", "requirements.txt"],
                           cwd=root, capture_output=True, text=True, timeout=900)
        return (r.returncode == 0), (r.stderr or r.stdout)[-400:]
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
