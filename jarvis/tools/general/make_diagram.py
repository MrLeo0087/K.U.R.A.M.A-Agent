"""make_diagram: a picture of a project (from its README only), of steps (flowchart) or of a Python file's calls, 0 tokens (safe)."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from jarvis.core.registry import tool


@tool(group="image", safety="safe", description="Draw a diagram: project = from the project's README only (no README, "
      "no diagram), flow = a flowchart of the steps given, code = which function calls which in a Python file. 0 tokens.")
def make_diagram(kind: Literal["project", "flow", "code"] = "project", target: str = "") -> str:
    """Diagrams.

    Args:
        kind: project, flow or code.
        target: project: folder path or name (empty = the folder open in VS Code); flow: the steps in words;
            code: a .py file (empty = the file open in VS Code).
    """
    from jarvis.core import assist, diagram, timemachine
    from jarvis.core.paths import smart_path

    t = (target or "").strip()
    if kind == "flow":
        return diagram.flow_from_text(t)
    if kind == "code":
        f = (Path(t).expanduser() if t.startswith(("/", "~")) else smart_path(t, want="file")) if t else assist.open_file_in_editor()
        return diagram.code(f)
    folder = None
    if t:
        folder = Path(t).expanduser() if t.startswith(("/", "~")) else (timemachine._find(t) or smart_path(t, want="dir"))
    return diagram.project(folder or timemachine.vscode_folder())
