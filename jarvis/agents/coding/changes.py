"""Change sets: every file change the coding agent makes is first SHOWN (a diff in the workspace + one line in the
chat) and waits for a yes; applying it keeps the old versions, so "undo what you did" puts them back. Files open
in VS Code are changed through the editor (one Ctrl+Z there too). 0 tokens.
"""
from __future__ import annotations

import difflib
import json
import time
from pathlib import Path

from jarvis.core import config, editor

_pending: dict = {}  # {"files": {path: [old, new]}, "title": str, "then": command or "", "cwd": str, "until": ts}


def _undo_dir() -> Path:
    return Path(config.DATA_DIR) / "agent_undo"


def _counts(old: str, new: str) -> tuple[int, int]:
    plus = minus = 0
    for ln in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0):
        if ln.startswith("+") and not ln.startswith("+++"):
            plus += 1
        elif ln.startswith("-") and not ln.startswith("---"):
            minus += 1
    return plus, minus


def stage(files: dict[Path, str], title: str, then: str = "", cwd: str = "", note: str = "") -> str:
    """Show the change and wait for yes. files: path -> its complete new text (new files too)."""
    changes: dict[str, list[str]] = {}
    for p, new in files.items():
        p = Path(p).expanduser()
        old = editor.read(p) if p.exists() else ""
        if old != new:
            changes[str(p)] = [old, new]
    if not changes:
        return "Nothing to change: the files already look like that."
    diff = []
    for path, (old, new) in changes.items():
        diff += [f"### {Path(path).name}{' (new file)' if not old else ''}", "```diff",
                 *difflib.unified_diff(old.splitlines(), new.splitlines(), f"a/{Path(path).name}",
                                       f"b/{Path(path).name}", lineterm="", n=2), "```", ""]
    try:
        from jarvis.core import workspace
        workspace.publish(title, f"# {title}\n\n{note + chr(10) * 2 if note else ''}" + "\n".join(diff), folder="answers")
    except Exception:  # noqa: BLE001 - the chat line still says what changes
        pass
    _pending.clear()
    _pending.update(files=changes, title=title, then=then, cwd=cwd, until=time.time() + config.AGENT_PENDING_TTL_S)
    parts = []
    for path, (old, new) in changes.items():
        a, r = _counts(old, new)
        parts.append(f"{Path(path).name} ({'new' if not old else f'+{a} −{r}'})")
    then_txt = f" and run `{then}` again" if then else ""
    return f"Ready: {', '.join(parts)} (the diff is in the workspace). Say yes to apply{then_txt}, or no."


def waiting() -> bool:
    return bool(_pending) and time.time() < _pending.get("until", 0)


def cancel() -> str:
    had = waiting()
    _pending.clear()
    return "Okay, nothing changed." if had else "No change is waiting."


def apply() -> str:
    """'yes': write every file (old versions kept for undo), then re-run the command if there is one."""
    if not waiting():
        return "No change is waiting (they expire after a few minutes)."
    p = dict(_pending)
    _pending.clear()
    if not p["files"]:  # only a command (e.g. pip install + run again)
        from jarvis.agents.coding import terminal
        return terminal.run_again(p["then"], p.get("cwd", "")) if p.get("then") else "Nothing to do."
    snap = _undo_dir() / time.strftime("%Y%m%d-%H%M%S")
    snap.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, (path, (old, new)) in enumerate(p["files"].items()):
        f = Path(path)
        (snap / f"{i}.old").write_text(old, encoding="utf-8")
        manifest.append({"path": path, "existed": bool(old) or f.exists(), "i": i})
        editor.save_text(f, new)
    (snap / "manifest.json").write_text(json.dumps({"title": p["title"], "files": manifest}))
    _prune()
    names = ", ".join(Path(x).name for x in p["files"])
    if p.get("then"):
        from jarvis.agents.coding import terminal
        ran = terminal.run_again(p["then"], p.get("cwd", ""))
        return f"Applied to {names}. {ran}"
    return f"Applied to {names}. Say 'undo that' to put the old version back."


def undo() -> str:
    """Put back the files of the last applied change."""
    snaps = sorted(_undo_dir().glob("*/manifest.json")) if _undo_dir().is_dir() else []
    if not snaps:
        return "There is no change of mine to undo."
    m = snaps[-1]
    data = json.loads(m.read_text())
    for e in data["files"]:
        f = Path(e["path"])
        old = (m.parent / f"{e['i']}.old").read_text(encoding="utf-8")
        if not e["existed"] and not old:
            if f.exists():
                f.unlink()  # a file I created: undo removes it again
        else:
            editor.save_text(f, old)
    for x in m.parent.iterdir():
        x.unlink()
    m.parent.rmdir()
    return f"Undone: {data['title']} ({', '.join(Path(e['path']).name for e in data['files'])} put back)."


def _prune(keep: int = 20) -> None:
    for d in sorted(p for p in _undo_dir().iterdir() if p.is_dir())[:-keep]:
        for x in d.iterdir():
            x.unlink()
        d.rmdir()
