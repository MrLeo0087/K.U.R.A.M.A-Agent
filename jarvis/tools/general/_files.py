"""Shared helpers for the file tools (not a tool): path resolution, safe roots, trash."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from jarvis.core import config, safety


def resolve(path: str) -> Path:
    raw = str(path).strip().strip("\"'")
    if raw and not raw.startswith(("/", "~")):
        # Models sometimes drop the leading slash ("tmp/x" for "/tmp/x"): trust the user's own words.
        ctx = safety.context()
        said = f"{ctx.get('request', '')} {ctx.get('user_text', '')}"
        parts = raw.rstrip("/").split("/")
        for k in range(len(parts), 0, -1):  # "tmp/x/main.py" when the user said "/tmp/x"
            pre = "/".join(parts[:k])
            m = re.search(r"(?<![\w~])(/(?:[^\s\"',;]*/)?" + re.escape(pre) + r")(?=[/\s\"',;.?!)]|$)", said)
            if m:
                raw = m.group(1) + raw.rstrip("/")[len(pre):]
                break
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = Path.home() / p
    return p.resolve()


def inside(p: Path, root: Path) -> bool:
    try:
        p.relative_to(root.expanduser().resolve())
        return True
    except (ValueError, OSError):
        return False


def in_safe_roots(p: Path) -> bool:
    return any(inside(p, r) for r in config.FILE_SAFE_ROOTS)


def guard(p: Path) -> None:
    """Never touch the filesystem root, home itself or system folders."""
    bad = {Path("/"), Path.home().resolve()} | {Path(x) for x in ("/bin", "/boot", "/dev", "/etc", "/lib",
                                                                 "/proc", "/sbin", "/sys", "/usr", "/var")}
    if p in bad or any(inside(p, Path(x)) for x in ("/bin", "/boot", "/dev", "/etc", "/lib", "/proc",
                                                     "/sbin", "/sys", "/usr")):
        raise ValueError(f"refusing to touch {p}")


def ask_outside(p: Path, what: str) -> bool:
    """Writes under FILE_SAFE_ROOTS are fine; anywhere else needs the user's yes."""
    return in_safe_roots(p) or safety.ask(f"Should I {what} {p}? It's outside your project folders.")


def trash(p: Path) -> None:
    """Move to the desktop trash with `gio trash` (never rm -rf). Patched in tests."""
    exe = shutil.which("gio")
    if not exe:
        raise RuntimeError("gio not found (install libglib2.0-bin)")
    r = subprocess.run([exe, "trash", str(p)], capture_output=True, text=True, timeout=20)
    if r.returncode:
        raise RuntimeError((r.stderr or "gio trash failed").strip()[:200])
