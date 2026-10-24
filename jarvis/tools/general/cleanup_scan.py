"""cleanup_scan: the old disk report.

No longer a tool of its own: `disk_cleaner` replaced it (old name kept as an alias)."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path



def _size(p: Path) -> int:
    """Folder size in bytes (du, 20 s cap; 0 if unknown)."""
    exe = shutil.which("du")
    if not exe or not p.exists():
        return 0
    try:
        out = subprocess.run([exe, "-sxb", str(p)], capture_output=True, text=True, timeout=20).stdout
        return int(out.split()[0]) if out else 0
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        return 0


def _gb(n: int) -> str:
    return f"{n / 1024 ** 3:.1f} GB" if n >= 1024 ** 3 else f"{n / 1024 ** 2:.0f} MB"


def cleanup_scan(path: str = "~") -> str:
    """Disk cleanup report (deletes nothing).

    Args:
        path: Folder to inspect (default: home).
    """
    root = Path(os.path.expanduser(path or "~"))
    if not root.is_dir():
        return f"error: no folder {path!r}"
    du = shutil.disk_usage(root)
    kids = [p for p in root.iterdir() if p.is_dir() and not p.is_symlink()]
    sizes = sorted(((_size(p), p.name) for p in kids[:40]), reverse=True)[:6]
    home = Path.home()
    dl = home / "Downloads"
    old = sum(f.stat().st_size for f in dl.glob("*") if f.is_file() and time.time() - f.stat().st_mtime > 30 * 86400) \
        if dl.is_dir() else 0
    cache, trash = _size(home / ".cache"), _size(home / ".local/share/Trash")
    lines = [f"Disk: {_gb(du.used)} used of {_gb(du.total)} ({_gb(du.free)} free).",
             "Biggest folders in " + str(root) + ": " + ", ".join(f"{n} {_gb(s)}" for s, n in sizes if s) + ".",
             f"Could free: old downloads (30+ days) {_gb(old)}, cache {_gb(cache)}, trash {_gb(trash)}.",
             "I didn't delete anything. Ask me to empty a specific folder or move files to trash if you want."]
    return "\n".join(lines)
