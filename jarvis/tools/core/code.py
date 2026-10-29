"""code: help with the owner's coding: explain/fix an error, run tests, where was I, what changed, git status /
commit, a new project, the Python environment, review code, ML training status (safe dispatcher)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool
from jarvis.tools.core._hub import Act, run

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
    "review": Act("review_code", lambda a: {"path": a.get("path", "")}),
    "training": Act("training", lambda a: {"action": a.get("text", "status") if a.get("text") in ("status", "stop", "watch") else "status"}),
}


@tool(group="core", safety="safe",
      description="Coding help: fix_error (explain an error/traceback), run_tests, where_was_i, changes (what changed "
                  "lately), git (status/log/diff), commit, new_project, env (check / install a package), review, training "
                  "(ML training / Colab status).")
def code(action: Literal["fix_error", "run_tests", "where_was_i", "changes", "git", "commit", "new_project", "env", "review",
                         "training"], text: str = "", path: str = "") -> str:
    """Coding.

    Args:
        action: What to do.
        text: The error text / commit message / project name / package to install / 'last hour' / git: status, log, diff.
        path: The project folder or file (empty = the current project).
    """
    return run(TABLE, {"action": action, "text": text, "path": path})
