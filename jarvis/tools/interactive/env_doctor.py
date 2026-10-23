"""env_doctor: CPU-only environment check (python, venv, pip, disk, RAM/swap, CLIs, Groq key) (safe)."""
from __future__ import annotations

import json
import os
import platform
import shutil
import sys
from importlib import metadata
from pathlib import Path

from jarvis.core import config
from jarvis.core.registry import tool
from jarvis.tools.interactive import _proc

CLIS = ("git", "rg", "fdfind", "ffmpeg", "ffplay", "xdotool", "wmctrl", "xclip", "pactl",
        "brightnessctl", "notify-send")
MIN_PY = (3, 11)
LOW_DISK_GB, LOW_RAM_GB = 5.0, 1.0


def _gb(n: float) -> str:
    return f"{n / 2**30:.1f}G"


def _outdated() -> str:
    py = Path(sys.executable).with_name("python3")
    try:
        cp = _proc.run([str(py) if py.exists() else "python3", "-m", "pip", "list", "--outdated",
                        "--format=json", "--disable-pip-version-check"], timeout=40)
        return f"{len(json.loads(cp.stdout or '[]'))} outdated"
    except Exception as e:
        return f"outdated check failed ({str(e)[:40]})"


@tool(group="dev", safety="safe", description="Environment doctor: python/venv/pip, disk, RAM/swap, CLI tools, API key check.")
def env_doctor(path: str = ".", check_outdated: bool = False) -> str:
    """Check the dev environment.

    Args:
        path: Project folder whose disk is checked (default: current folder).
        check_outdated: Also count outdated pip packages (slow, uses network).
    """
    import psutil

    warn: list[str] = []
    v = sys.version_info
    venv = os.environ.get("VIRTUAL_ENV") or (sys.prefix if sys.prefix != sys.base_prefix else "")
    if v[:2] < MIN_PY:
        warn.append(f"python<{MIN_PY[0]}.{MIN_PY[1]}")
    if not venv:
        warn.append("no venv active")
    try:
        pip = f"pip {metadata.version('pip')}"
    except metadata.PackageNotFoundError:
        pip = "pip missing"
        warn.append(pip)
    if check_outdated:
        pip += f" ({_outdated()})"
    lines = [f"Python {v.major}.{v.minor}.{v.micro} ({platform.system()}), "
             f"venv: {Path(venv).name if venv else 'none'}, {pip}"]

    base = _proc.resolve_dir(path)
    disks = []
    for label, p in (("/", "/"), (base.name or str(base), str(base))):
        du = shutil.disk_usage(p)
        disks.append(f"{label} {_gb(du.free)} free of {_gb(du.total)}")
        if du.free / 2**30 < LOW_DISK_GB:
            warn.append(f"low disk on {label}")
    lines.append("Disk: " + "; ".join(dict.fromkeys(disks)))

    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    lines.append(f"RAM {_gb(vm.available)} free of {_gb(vm.total)} ({vm.percent:.0f}% used), "
                 f"swap {_gb(sw.used)}/{_gb(sw.total)}, CPU {psutil.cpu_count()} cores, "
                 f"load {os.getloadavg()[0]:.1f}")
    if vm.available / 2**30 < LOW_RAM_GB:
        warn.append("low RAM")

    missing = [c for c in CLIS if not shutil.which(c)]
    lines.append(f"CLIs: {len(CLIS) - len(missing)}/{len(CLIS)} ok" + (f", missing {', '.join(missing)}" if missing else ""))
    if missing:
        warn.append("missing CLIs")
    has_key = bool(config.GROQ_API_KEY)  # presence only: the key itself is never printed
    lines.append(f"GROQ key: {'set' if has_key else 'MISSING (add GROQ_API_KEY to .env)'}")
    if not has_key:
        warn.append("no Groq key")
    lines.append("Verdict: " + ("all good" if not warn else "check " + ", ".join(warn)))
    return _proc.clip("\n".join(lines))
