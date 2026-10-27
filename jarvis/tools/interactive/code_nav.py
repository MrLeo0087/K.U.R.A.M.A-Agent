"""code_nav: jump to the real code of the highlighted function/class (project or installed library), 0 tokens (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="codequality", safety="safe", description="Go to the real code of a function/class: finds where the "
      "highlighted (or named) function is defined, in the project or a library, and opens it in VS Code. 0 tokens.")
def code_nav(action: Literal["find"] = "find", name: str = "") -> str:
    """Code navigation.

    Args:
        action: find (go to where it is defined).
        name: the function/class name; empty = the text highlighted in VS Code.
    """
    from jarvis.core import assist, codenav, rewrite, timemachine

    text = name.strip()
    if not text:
        g = rewrite.grab()
        if isinstance(g, str):
            return "Highlight the function name in VS Code, then say 'find this function'."
        text = g.text
    return codenav.go(text, timemachine.vscode_folder(), assist.open_file_in_editor())
