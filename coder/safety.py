"""Nothing the agent does is lost: before a file changes its old text is kept in the run's folder, new files and
folders are listed, and undo puts it all back (new files go to the trash, never deleted for good). And a secret
guard: no API key / token / password is ever written into code (an .env.example instead)."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from coder.run import Run

SECRET = re.compile(r"""(?:(?:api[_-]?key|secret|token|passw(?:or)?d)\s*[:=]\s*['"][A-Za-z0-9_\-./+]{12,}['"]|"""
                    r"""\bgsk_[A-Za-z0-9]{20,}|\bsk-[A-Za-z0-9]{20,}|\bghp_[A-Za-z0-9]{20,}|\bAIza[0-9A-Za-z_\-]{30,})""", re.I)


def _record(run: Run) -> dict:
    p = run.dir / "undo.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"root": str(run.root), "changed": {}, "created": [], "new_root": False}
    except ValueError:
        return {"root": str(run.root), "changed": {}, "created": [], "new_root": False}


def _save(run: Run, rec: dict) -> None:
    (run.dir / "undo.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")


def begin(run: Run) -> None:
    rec = _record(run)
    rec["new_root"] = not run.root.exists()
    _save(run, rec)


def before_write(run: Run, p: Path) -> None:
    """Keep the old text of a file about to change (once per run), or note it as new."""
    rec = _record(run)
    key = str(p)
    if key in rec["changed"] or key in rec["created"]:
        return
    if p.exists():
        backup = run.dir / "backup" / f"{len(rec['changed'])}{p.suffix}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(p.read_bytes())
        rec["changed"][key] = str(backup)
    else:
        rec["created"].append(key)
    _save(run, rec)


def write(run: Run, rel: str, text: str) -> Path:
    """Write one file of the project (backup first; secrets refused)."""
    p = (run.root / rel).resolve()
    if not p.is_relative_to(run.root.resolve()):
        raise ValueError(f"{rel} is outside the project")
    if SECRET.search(text):
        text = SECRET.sub(lambda m: re.sub(r"(['\"])[^'\"]+(['\"])$", r"\1CHANGE_ME\2", m.group(0))
                          if "=" in m.group(0) or ":" in m.group(0) else "CHANGE_ME", text)
        run.note(f"secret guard: a key-like value in {rel} was replaced by CHANGE_ME")
    before_write(run, p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    if p.suffix == ".py":  # its old compiled copy must never run instead of the new code
        for c in (p.parent / "__pycache__").glob(f"{p.stem}.*.pyc"):
            c.unlink(missing_ok=True)
    return p


def _trash(p: Path) -> None:
    try:
        subprocess.run(["gio", "trash", str(p)], capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        pass


def undo(run_dir: Path) -> str:
    """Put back what that run changed; its new files / its new folder go to the trash."""
    p = run_dir / "undo.json"
    if not p.exists():
        return "Nothing of mine to undo."
    rec = json.loads(p.read_text(encoding="utf-8"))
    root = Path(rec["root"])
    if rec.get("new_root") and root.exists():
        _trash(root)
        p.unlink()
        return f"Undone: the new project {root.name} went to the trash."
    for path, backup in rec["changed"].items():
        Path(path).write_bytes(Path(backup).read_bytes())
    for path in rec["created"]:
        if Path(path).exists():
            _trash(Path(path))
    p.unlink()
    return (f"Undone in {root.name}: {len(rec['changed'])} file(s) put back, {len(rec['created'])} new file(s) moved "
            "to the trash.")
