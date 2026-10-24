"""ML disk cleaner: what fills the disk, with the ML culprits named, and safe ways to free it (0 tokens).

Scan (read-only): disk use, biggest folders, and these categories with sizes:
  hf_cache   ~/.cache/huggingface (downloaded models/datasets; re-downloaded when needed)
  torch_cache ~/.cache/torch (hub weights), pip_cache ~/.cache/pip, trash, old_downloads (30+ days)
  checkpoints *.ckpt/*.pt/*.pth/*.safetensors/*.h5 not touched for CHECKPOINT_AGE_DAYS, except the newest per folder
  dead_venvs  venv/.venv/env whose project hasn't been touched for VENV_AGE_DAYS (recreate with pip install -r)
  pycache     __pycache__ and .ipynb_checkpoints folders
  duplicates  identical big files (>= 50 MB), all but one copy
Clean: the chosen categories go to the Trash (files you made) or are deleted (caches that refill themselves);
always after the user's yes (the tool asks).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
from pathlib import Path

from jarvis.core import config

HOME = Path.home()
CKPT_EXT = {".ckpt", ".pt", ".pth", ".safetensors", ".h5", ".keras", ".bin", ".onnx", ".pkl", ".joblib"}
CATEGORIES = ("hf_cache", "torch_cache", "pip_cache", "trash", "old_downloads", "checkpoints", "dead_venvs", "pycache",
              "duplicates")
LABEL = {"hf_cache": "Hugging Face cache", "torch_cache": "PyTorch hub cache", "pip_cache": "pip cache",
         "trash": "Trash", "old_downloads": "downloads older than 30 days", "checkpoints": "old model checkpoints",
         "dead_venvs": "venvs of untouched projects", "pycache": "__pycache__/.ipynb_checkpoints",
         "duplicates": "duplicate big files"}
DUP_OF: dict[Path, Path] = {}  # duplicate -> the copy that is kept (filled by find("duplicates"))
SKIP_DIRS = {".git", "node_modules", "site-packages", ".cache", "snap", ".local", ".mozilla", ".config"}


def gb(n: float) -> str:
    return f"{n / 1024 ** 3:.1f} GB" if n >= 1024 ** 3 else f"{n / 1024 ** 2:.0f} MB"


def size_of(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    exe = shutil.which("du")
    if not exe or not p.exists():
        return 0
    try:
        out = subprocess.run([exe, "-sxb", str(p)], capture_output=True, text=True, timeout=30).stdout
        return int(out.split()[0]) if out else 0
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        return 0


def _walk(roots: list[Path], max_depth: int = 6):
    for r in roots:
        if not r.is_dir():
            continue
        base = len(r.parts)
        for dirpath, dirnames, filenames in os.walk(r):
            depth = len(Path(dirpath).parts) - base
            dirnames[:] = [] if depth >= max_depth else [d for d in dirnames if d not in SKIP_DIRS]
            yield Path(dirpath), dirnames, filenames


def project_roots() -> list[Path]:
    return [Path(p).expanduser() for p in config.SEARCH_ROOTS if Path(p).expanduser().is_dir()]


def find(category: str) -> list[Path]:
    """The files/folders a category would remove."""
    now = time.time()
    if category == "hf_cache":
        return [p for p in [HOME / ".cache" / "huggingface"] if p.exists()]
    if category == "torch_cache":
        return [p for p in [HOME / ".cache" / "torch"] if p.exists()]
    if category == "pip_cache":
        return [p for p in [HOME / ".cache" / "pip"] if p.exists()]
    if category == "trash":
        t = HOME / ".local" / "share" / "Trash"
        return [p for p in (t / "files", t / "info") if p.exists() and any(p.iterdir())]
    if category == "old_downloads":
        dl = HOME / "Downloads"
        return [f for f in dl.iterdir() if now - f.stat().st_mtime > 30 * 86400] if dl.is_dir() else []
    out: list[Path] = []
    if category == "checkpoints":
        age = config.CHECKPOINT_AGE_DAYS * 86400
        for d, _, files in _walk(project_roots()):
            ck = [d / f for f in files if Path(f).suffix.lower() in CKPT_EXT]
            ck = [f for f in ck if f.stat().st_size >= 5 * 1048576]
            if len(ck) < 2:
                continue
            ck.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            out += [f for f in ck[1:] if now - f.stat().st_mtime > age]  # keep the newest in each folder
    elif category == "dead_venvs":
        age = config.VENV_AGE_DAYS * 86400
        for d, dirnames, _ in _walk(project_roots(), 5):
            for v in [d / n for n in dirnames if n in ("venv", ".venv", "env")]:
                if not (v / "bin" / "python").exists() or Path(config.ROOT) in v.parents:
                    continue
                newest = max((f.stat().st_mtime for f in d.glob("*") if f.is_file()), default=0)
                if newest and now - newest > age:
                    out.append(v)
    elif category == "pycache":
        for d, dirnames, _ in _walk(project_roots()):
            out += [d / n for n in dirnames if n in ("__pycache__", ".ipynb_checkpoints")]
    elif category == "duplicates":
        by_size: dict[int, list[Path]] = {}
        for d, _, files in _walk(project_roots() + [HOME / "Downloads"]):
            for f in files:
                p = d / f
                try:
                    s = p.stat().st_size
                except OSError:
                    continue
                if s >= 50 * 1048576 and not p.is_symlink():
                    by_size.setdefault(s, []).append(p)
        for same in by_size.values():
            if len(same) < 2:
                continue
            groups: dict[str, list[Path]] = {}
            for p in same:
                try:
                    with open(p, "rb") as fh:
                        h = hashlib.md5(fh.read(1048576)).hexdigest()  # first MB + equal size: same file
                except OSError:
                    continue
                groups.setdefault(h, []).append(p)
            for g in groups.values():
                g.sort(key=lambda p: p.stat().st_mtime)
                for p in g[1:]:  # keep the oldest copy
                    DUP_OF[p] = g[0]
                    out.append(p)
    return list(dict.fromkeys(out))


def scan(path: str = "") -> str:
    root = Path(os.path.expanduser(path or "~"))
    du = shutil.disk_usage(root)
    lines = [f"Disk: {gb(du.used)} used of {gb(du.total)} ({gb(du.free)} free, {du.used / du.total:.0%} full)."]
    if path:
        kids = [p for p in root.iterdir() if p.is_dir() and not p.is_symlink()][:40]
        sizes = sorted(((size_of(p), p.name) for p in kids), reverse=True)[:6]
        lines.append(f"Biggest in {root}: " + ", ".join(f"{n} {gb(s)}" for s, n in sizes if s) + ".")
    found = []
    for c in CATEGORIES:
        items = find(c)
        total = sum(size_of(p) for p in items)
        if total >= 20 * 1048576:
            found.append((total, c, len(items)))
    found.sort(reverse=True)
    if found:
        lines.append("You could free:")
        lines += [f"- {LABEL[c]}: {gb(s)}" + (f" ({n} items)" if n > 1 else "") + f"  [{c}]" for s, c, n in found]
        lines.append(f"In total about {gb(sum(s for s, _, _ in found))}. Say e.g. 'clean the {found[0][1].replace('_', ' ')}'"
                     f" (I'll ask before deleting).")
    else:
        lines.append("Nothing big to clean: caches, trash, checkpoints and duplicates are all small.")
    return "\n".join(lines)


def trash(p: Path) -> None:
    """Move to the desktop Trash (restorable)."""
    subprocess.run(["gio", "trash", str(p)], check=True, capture_output=True, timeout=60)


SELF_REFILLING = {"hf_cache", "torch_cache", "pip_cache", "pycache", "trash"}


def clean(category: str) -> tuple[int, int]:
    """Free one category. Caches are deleted (they refill themselves); your files go to the Trash. (count, bytes)."""
    items = find(category)
    freed, n = 0, 0
    for p in items:
        s = size_of(p)
        if category == "duplicates":
            import filecmp
            keep = DUP_OF.get(p)
            if keep is None or not keep.exists() or not filecmp.cmp(p, keep, shallow=False):
                continue  # only a byte-for-byte copy is removed
        try:
            if category == "trash":
                for child in p.iterdir():
                    shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
            elif category in SELF_REFILLING:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
            else:
                trash(p)
        except (OSError, subprocess.SubprocessError):
            continue
        freed += s
        n += 1
    return n, freed
