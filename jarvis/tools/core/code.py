"""code: help with the owner's coding: explain/fix an error, run tests, where was I, what changed, git status /
commit, a new project, the Python environment, requirements.txt, notebook -> script, dependency check, review code, ML
training status (safe dispatcher). No path = the project (or notebook) open in VS Code."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from jarvis.core.registry import tool
from jarvis.tools.core._hub import Act, run

_HERE = re.compile(r"^(?:this|current|the|my|open|opened|vs\s*code|vscode|project|folder|repo|\s)*$", re.I)


def _project(a: dict) -> str:
    """The folder asked for, else the one open in VS Code ('.' if none)."""
    path = a.get("path", "")
    if path and not _HERE.match(path):
        return path
    from jarvis.core.timemachine import vscode_folder
    return str(vscode_folder() or ".")


def _notebook(a: dict) -> str:
    """The .ipynb asked for, else the notebook open in VS Code (its window title), else the newest one in that project."""
    path = a.get("path", "")
    from jarvis.core.timemachine import vscode_folder
    if path and not _HERE.match(path):
        if Path(path).expanduser().exists() or "/" in path or (root := vscode_folder()) is None:
            return path
        return str(next(iter(sorted(Path(root).rglob(Path(path).name))), path))  # 'train.ipynb' = the one in that project
    root = vscode_folder()
    if root is None:
        return path
    try:
        import subprocess as sp
        title = next((ln for ln in sp.run(["wmctrl", "-l"], check=False, capture_output=True, text=True, timeout=3).stdout.splitlines()
                      if ln.rstrip().endswith("Visual Studio Code")), "")
    except (OSError, sp.SubprocessError):
        title = ""
    name = title.split(None, 3)[-1].split(" - ")[0].lstrip("● ").strip() if title else ""
    if name.endswith(".ipynb") and (hits := sorted(Path(root).rglob(name))):
        return str(hits[0])
    books = sorted(Path(root).rglob("*.ipynb"), key=lambda f: f.stat().st_mtime, reverse=True)
    return str(books[0]) if books else path

TABLE = {
    "fix_error": Act("fix_error", lambda a: {"action": "explain", "text": a.get("text", "")}),
    "run_tests": Act("run_tests", lambda a: {"path": a.get("path", "")}),
    "where_was_i": Act("where_was_i", lambda a: {"project": a.get("path", "")}),
    "changes": Act("time_machine", lambda a: {"action": "changes", "project": a.get("path", ""), "when": a.get("text", "")}),
    "git": Act("git_info", lambda a: {"action": a.get("text", "status") if a.get("text") in ("status", "log", "diff") else "status",
                                      "repo": a.get("path", "")}),
    "commit": Act("git_change", lambda a: {"action": "commit", "message": a.get("text", ""), "repo": a.get("path", "")}),
    "new_project": Act("scaffold_project", lambda a: {"name": a.get("text", "project"), "path": a.get("path", "")}),
    "env": Act("python_env", lambda a: {"action": "install" if a.get("text") else "check", "package": a.get("text", ""),
                                        "folder": a.get("path", "")}),
    "requirements": Act("generate_requirements", lambda a: {"path": _project(a)}),
    "notebook_to_py": Act("notebook_to_script", lambda a: {"path": _notebook(a)}),
    "check_deps": Act("dependency_doctor", lambda a: {"repo": _project(a)}),
    "review": Act("review_code", lambda a: {"path": a.get("path", "")}),
    "training": Act("training", lambda a: {"action": a.get("text", "status") if a.get("text") in ("status", "stop", "watch") else "status"}),
}


@tool(group="core", safety="safe",
      description="Coding help: fix_error (explain an error/traceback), run_tests, where_was_i, changes (what changed "
                  "lately), git (status/log/diff), commit, new_project, env (check / install a package), requirements (make "
                  "requirements.txt from imports), notebook_to_py (.ipynb -> .py), check_deps (missing/unpinned/outdated "
                  "packages), review, training "
                  "(ML training / Colab status).")
def code(action: Literal["fix_error", "run_tests", "where_was_i", "changes", "git", "commit", "new_project", "env",
                         "requirements", "notebook_to_py", "check_deps", "review", "training"], text: str = "", path: str = "") -> str:
    """Coding.

    Args:
        action: What to do.
        text: The error text / commit message / project name / package to install / 'last hour' / git: status, log, diff.
        path: The project folder or file (empty = the one open in VS Code).
    """
    return run(TABLE, {"action": action, "text": text, "path": path})
