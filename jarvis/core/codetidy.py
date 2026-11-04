"""Format and check a code file on this laptop, 0 tokens (ruff for Python, the json module for JSON).

  format  ruff format (Python) / pretty JSON: exact and instant; VS Code reloads the file
  check   ruff check: the real problems with line numbers (syntax errors, unused imports, undefined names...)
  fix     ruff check --fix: only ruff's SAFE fixes, then what is left
Every change keeps a backup in data/code_backups. The target is the file open in VS Code, or a named file.
Other languages: the AI formats it instead (assist.improve_whole_file, waits for a yes).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from jarvis.core import config


# ruff's default checks always, whatever a project's narrower gate says (KURAMA's pyproject.toml gate is small)
_RULES = ("--extend-select", "E4,E7,E9,F")


def _ruff() -> str | None:
    venv = Path(sys.executable).with_name("ruff")
    return str(venv) if venv.is_file() else shutil.which("ruff")


def target(path: str = "") -> Path | str:
    """The file to work on: a name/path, or the file open in VS Code. Path, or a message."""
    from jarvis.core import assist
    if path.strip() and path.strip().lower() not in ("this", "this file", "it", "my code", "the code", "code"):
        from jarvis.core.paths import resolve_target
        return resolve_target(path)
    f = assist.open_file_in_editor()
    return f if f and f.is_file() else "Open the file in VS Code first (or tell me its name)."


def _unsaved() -> bool:
    from jarvis.core import rewrite
    wid, _ = rewrite.target_window()
    return bool(wid) and rewrite._window_name(wid).lstrip().startswith(("●", "•"))


def _backup(f: Path, text: str) -> None:
    b = Path(config.DATA_DIR) / "code_backups" / f"{f.name}.{int(time.time())}.bak"
    b.parent.mkdir(parents=True, exist_ok=True)
    b.write_text(text, encoding="utf-8")


def _changed_lines(a: str, b: str) -> int:
    import difflib
    return sum(1 for ln in difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=0)
               if ln[:1] in "+-" and not ln.startswith(("+++", "---")))


def _syntax_hint(err: str, f: Path) -> str:
    m = re.search(r"(\d+):(\d+):\s*(.+)", err)
    where = f" at line {m.group(1)}: {m.group(3).strip()[:120]}" if m else ""
    return (f"I can't format {f.name}: it has a syntax error{where}. Fix that first, or say 'fix this file' and the "
            f"AI will repair it (it asks before replacing).")


def format_file(f: Path) -> str:
    from jarvis.core import editor
    ext = f.suffix.lower()
    text = editor.read(f)  # what VS Code shows (unsaved edits included)
    if ext in (".py", ".pyi"):
        ruff = _ruff()
        if not ruff:
            return "ruff isn't installed: venv/bin/pip install ruff"
        r = subprocess.run([ruff, "format", "--stdin-filename", str(f), "-"], input=text, capture_output=True,
                           text=True, timeout=60)
        if r.returncode != 0:
            return _syntax_hint(r.stderr or r.stdout, f)
        new = r.stdout
    elif ext == ".json":
        try:
            new = json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n"
        except ValueError as e:
            return f"{f.name} isn't valid JSON: {e}"
    else:
        return ""  # not ours: the caller lets the AI do it
    if new == text:
        return f"{f.name} is already well formatted."
    _backup(f, text)
    how = editor.save_text(f, new)
    return f"Formatted {f.name} ({_changed_lines(text, new)} lines changed)." + (" Ctrl+Z in VS Code undoes it." if how == "editor" else "")


def check_file(f: Path, fix: bool = False) -> str:
    if f.suffix.lower() == ".json":
        try:
            json.loads(f.read_text(errors="replace"))
            return f"{f.name} is valid JSON."
        except ValueError as e:
            return f"{f.name}: {e}"
    if f.suffix.lower() not in (".py", ".pyi"):
        return f"I can check Python and JSON files for free; {f.name} isn't one. Say 'review {f.name}' for an AI review."
    ruff = _ruff()
    if not ruff:
        return "ruff isn't installed: venv/bin/pip install ruff"
    before = f.read_text(errors="replace")
    if fix:
        r = subprocess.run([ruff, "check", "--fix", "--quiet", "--exit-zero", *_RULES, str(f)], capture_output=True, text=True,
                           timeout=60)
        after = f.read_text(errors="replace")
        if after != before:
            _backup(f, before)
    args = [ruff, "check", "--output-format", "concise", "--no-cache", "--exit-zero", *_RULES, str(f)]
    out = subprocess.run(args, capture_output=True, text=True, timeout=60).stdout
    probs = []
    for ln in out.splitlines():
        m = re.match(r".*?:(\d+):\d+:\s*(?:(\w+\d+)\s+)?(?:\[\*\]\s*)?(.+)", ln)
        if m:
            probs.append((int(m.group(1)), m.group(2) or "", m.group(3).strip(), "[*]" in ln))
    fixed = _changed_lines(before, f.read_text(errors="replace")) if fix else 0
    head = f"Fixed {fixed} lines in {f.name}. " if fix and fixed else ""
    if not probs:
        return head + f"No problems in {f.name}."
    lines = [f"line {n}: {msg}" + (f" ({code})" if code else "") for n, code, msg, _ in probs[:12]]
    more = f"\n…and {len(probs) - 12} more." if len(probs) > 12 else ""
    can_fix = sum(1 for p in probs if p[3])
    tail = f"\nSay 'fix the problems' to fix {can_fix} of them safely." if can_fix and not fix else ""
    return head + f"{len(probs)} problem{'s' if len(probs) > 1 else ''} in {f.name}:\n" + "\n".join(lines) + more + tail


def run(action: str = "check", path: str = "") -> str:
    f = target(path)
    if isinstance(f, str):
        return f
    if action in ("format", "fix") and _unsaved():
        return f"{f.name} has unsaved changes. Press Ctrl+S in VS Code, then ask again."
    if action == "format":
        out = format_file(f)
        if out:
            return out
        from jarvis.core import assist  # another language: the AI formats it and asks before replacing
        return assist.improve_whole_file("format this whole file (indentation, spacing, line breaks only)")
    return check_file(f, fix=action == "fix")
