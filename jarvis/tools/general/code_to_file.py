"""code_to_file: put code into the file open in VS Code (or a given path): the code KURAMA just wrote (the newest
workspace result) or code given here. Only the code goes in (no explanation text); an existing file is backed up
and replaced after one yes (confirm inside)."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Literal

from jarvis.core import config, safety
from jarvis.core.registry import tool

_CODE_EXT = {".py", ".js", ".ts", ".sh", ".go", ".rs", ".java", ".cpp", ".c", ".rb", ".php", ".html", ".css", ".sql"}


def latest_code() -> str:
    """The code of the newest workspace result (a code file, or the fenced blocks of a Markdown answer)."""
    from jarvis.core.writer import code_only
    root = Path(config.OUTPUTS_DIR)
    files = sorted((f for f in root.rglob("*") if f.is_file() and (f.suffix in _CODE_EXT or f.suffix == ".md")),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files[:5]:
        text = f.read_text(errors="replace")
        if f.suffix in _CODE_EXT:
            return text
        if "```" in text:
            return code_only(text)
    return ""


@tool(group="clipboard", safety="safe",
      description="Write code into the file open in VS Code (or `path`): the code KURAMA just generated (newest "
                  "workspace result) or `code`; only the code, replaces the file (backup kept, asks first) or appends.")
def code_to_file(path: str = "", code: str = "", mode: Literal["replace", "append"] = "replace") -> str:
    """Code into a file.

    Args:
        path: The file (empty = the one open in VS Code).
        code: The code to write (empty = the code KURAMA generated last).
        mode: replace the file's content, or append at the end.
    """
    from jarvis.core import assist, context
    from jarvis.core.writer import code_only
    body = code_only(code) if code.strip() else latest_code()
    if not body.strip():
        return "error: there's no code to write yet: ask me to write the code first (or paste it)"
    if path.strip():
        from jarvis.core.paths import smart_path
        target = Path(path.strip()).expanduser()
        target = target if target.is_absolute() else (smart_path(path.strip(), want="file") or Path.home() / path.strip())
    else:
        target = context.snapshot().get("file") or assist.open_file_in_editor()
        if target is None:
            return "error: open the file in VS Code (or give its path), then ask again"
    target = Path(target)
    old = target.read_text(errors="replace") if target.is_file() else ""
    if old.strip() and mode == "replace":
        if not safety.ask(f"Replace the code in {target.name} with the new code ({len(body.splitlines())} lines)?"):
            return "The user declined: the file was not changed."
    if old.strip():
        backup = Path(config.DATA_DIR) / "backups" / f"{target.name}.{time.strftime('%Y%m%d-%H%M%S')}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(old, encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body if mode == "replace" else old.rstrip() + "\n\n" + body, encoding="utf-8")
    return (f"Wrote {len(body.splitlines())} lines of code into {target.name}"
            + (" (old version backed up; VS Code shows the new code)." if old.strip() else "."))
