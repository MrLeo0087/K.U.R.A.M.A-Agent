"""code_tidy: format / check / safely fix a code file on this laptop with ruff, 0 tokens (safe; backups kept)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="codequality", safety="safe", description="Format a code file (ruff format / pretty JSON), check it for "
      "problems (ruff check) or fix the safe ones. 0 tokens. Default file: the one open in VS Code.")
def code_tidy(action: Literal["format", "check", "fix"] = "check", path: str = "") -> str:
    """Format or check a code file locally.

    Args:
        action: format (rewrite the layout), check (list problems with line numbers) or fix (apply ruff's safe fixes).
        path: the file; empty = the file open in VS Code.
    """
    from jarvis.core import codetidy

    return codetidy.run(action, path)
