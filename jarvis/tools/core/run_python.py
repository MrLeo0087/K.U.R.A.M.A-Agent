"""run_python: run a short Python snippet on the laptop (for calculations, data, files, anything no tool does).
Asks the owner before EVERY run (confirm) and shows the code; isolated interpreter, 60 s limit."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from jarvis.core.registry import tool

TIMEOUT_S = 60


@tool(group="core", safety="confirm", max_chars=1500,
      description="Run a short Python program on the laptop and return what it prints; asks the user first, every time. "
                  "Use when no other tool fits (math on data, quick scripts). Never just to READ or list a file: "
                  "the file tools / the open file already give it.")
def run_python(code: str, folder: str = "") -> str:
    """Run Python code.

    Args:
        code: The complete Python program; print() the result.
        folder: Folder to run it in (default: home).
    """
    src = (code or "").strip()
    if not src:
        return "error: no code"
    cwd = Path(os.path.expanduser(folder or "~"))
    try:
        cp = subprocess.run([sys.executable, "-I", "-c", src], cwd=cwd if cwd.is_dir() else Path.home(),
                            capture_output=True, text=True, timeout=TIMEOUT_S, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return f"Stopped: the program ran longer than {TIMEOUT_S} s."
    out = (cp.stdout or "") + (("\n" + cp.stderr[-800:]) if cp.returncode else "")
    return out.strip() or "(it printed nothing)"
