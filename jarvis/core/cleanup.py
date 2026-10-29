"""Clean RAM / storage / KURAMA (0 tokens, no internet). Only safe things happen by themselves:

- RAM: the top apps by RAM and by CPU (grouped by app, so 30 Chrome processes are one line), KURAMA's own idle
  memory freed (its meaning model, Python's free lists), idle Jupyter kernels found. Your apps are never closed by
  themselves: "close <app>" stops one (asks first).
- storage: caches that rebuild themselves (pip, uv, npm, yarn, go-build, thumbnails, GPU shader caches, Hugging Face,
  PyTorch hub) and Trash items older than 30 days. Browsers (logins!) and your files are never touched. Cleanups
  that need your password are listed as commands for you to run.
- KURAMA: its run logs older than 7 days, Python bytecode caches, temp folders, the song cache, and leftover
  half-downloaded video parts. Your chats, memory, settings, traces and downloaded videos stay.
"""
from __future__ import annotations

import gc
import logging
import shutil
import time
from pathlib import Path

from jarvis.core import config

log = logging.getLogger(__name__)
HOME = Path.home()
STORAGE_CACHES = (".cache/pip", ".cache/uv", ".npm/_cacache", ".cache/yarn", ".cache/go-build", ".cache/thumbnails",
                  ".cache/mesa_shader_cache", ".cache/nvidia/GLCache", ".cache/huggingface", ".cache/torch/hub",
                  ".cache/typescript", ".cache/node-gyp")
SUDO_TIPS = ("sudo apt clean    # downloaded install packages",
             "sudo journalctl --vacuum-size=200M    # old system logs",
             "snap list --all | awk '/disabled/{print $1, $3}' | while read n r; do sudo snap remove \"$n\" "
             "--revision=\"$r\"; done    # old snap versions")


def _size(p: Path) -> int:
    if p.is_file() or p.is_symlink():
        try:
            return p.lstat().st_size
        except OSError:
            return 0
    total = 0
    for f in p.rglob("*"):
        try:
            if f.is_file() and not f.is_symlink():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def _rm(p: Path) -> int:
    """Delete one cache path; returns the bytes freed (0 when it couldn't)."""
    n = _size(p)
    try:
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        else:
            p.unlink()
    except OSError as e:
        log.info("couldn't remove %s: %s", p, e)
        return 0
    return n


def _fmt(n: float) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def top_apps(n: int = 5) -> tuple[list[tuple[str, int]], list[tuple[str, float]]]:
    """([(app, RSS bytes)], [(app, CPU %)]) of the busiest apps, processes grouped by name."""
    import psutil
    procs = list(psutil.process_iter(["name", "memory_info"]))
    for p in procs:
        try:
            p.cpu_percent(None)
        except psutil.Error:
            pass
    time.sleep(0.5)
    ram: dict[str, int] = {}
    cpu: dict[str, float] = {}
    for p in procs:
        try:
            name = (p.info["name"] or "?").split("/")[0][:30]
            ram[name] = ram.get(name, 0) + (p.info["memory_info"].rss if p.info["memory_info"] else 0)
            cpu[name] = cpu.get(name, 0.0) + p.cpu_percent(None)
        except psutil.Error:
            continue
    by_ram = sorted(ram.items(), key=lambda kv: kv[1], reverse=True)[:n]
    by_cpu = [(k, v) for k, v in sorted(cpu.items(), key=lambda kv: kv[1], reverse=True)[:n] if v >= 0.5]
    return by_ram, by_cpu


def ram() -> str:
    import psutil
    before = psutil.virtual_memory()
    try:
        from jarvis.core import semantic
        semantic.free_now()  # KURAMA's meaning model (~120 MB): it reloads by itself when needed
    except Exception:  # noqa: BLE001
        pass
    gc.collect()
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)  # give Python's freed memory back to the system
    except (OSError, AttributeError):
        pass
    by_ram, by_cpu = top_apps()
    after = psutil.virtual_memory()
    freed = max(0, after.available - before.available)
    lines = [f"RAM: {after.percent:.0f}% used, {_fmt(after.available)} free"
             + (f" ({_fmt(freed)} freed from KURAMA's own memory)" if freed > 20e6 else "") + "."]
    lines.append("Top RAM: " + ", ".join(f"{a} {_fmt(b)}" for a, b in by_ram) + ".")
    if by_cpu:
        lines.append("Top CPU: " + ", ".join(f"{a} {c:.0f}%" for a, c in by_cpu) + ".")
    try:
        from jarvis.core import doctor
        if ks := doctor.idle_kernels():
            lines.append(f"{len(ks)} idle Jupyter kernel(s) hold memory: say 'free up some ram' to stop them.")
    except Exception:  # noqa: BLE001
        pass
    lines.append(f"To free more, close what you don't need, or say 'close {by_ram[0][0]}' (I ask first)."
                 if by_ram else "")
    return "\n".join(x for x in lines if x)


def storage() -> str:
    before = shutil.disk_usage(HOME).free
    freed, done = 0, []
    for rel in STORAGE_CACHES:
        p = HOME / rel
        if p.exists() and (n := _rm(p)):
            freed += n
            done.append(f"{rel.split('/')[-1] if rel.count('/') < 2 else rel} {_fmt(n)}")
    trash = HOME / ".local/share/Trash"
    old = time.time() - 30 * 86400
    t_freed = 0
    for info in (trash / "info").glob("*.trashinfo") if (trash / "info").is_dir() else []:
        try:
            if info.stat().st_mtime < old:
                t_freed += _rm(trash / "files" / info.stem)
                info.unlink()
        except OSError:
            pass
    if t_freed:
        freed += t_freed
        done.append(f"Trash older than 30 days {_fmt(t_freed)}")
    after = shutil.disk_usage(HOME)
    head = (f"Freed {_fmt(freed)}: " + ", ".join(done) + "." if done else "Nothing to clean: the caches are already empty.")
    return (f"{head}\nDisk: {_fmt(after.free)} free of {_fmt(after.total)}. Browsers and your files weren't touched.\n"
            "More needs your password (run in a terminal):\n" + "\n".join(SUDO_TIPS))


def kurama() -> str:
    from jarvis.core import ytdl
    freed, done = 0, []
    root = Path(__file__).resolve().parents[2]
    week = time.time() - 7 * 86400
    runs = [f for f in (config.DATA_DIR / "runs").glob("*") if f.is_file() and f.stat().st_mtime < week] \
        if (config.DATA_DIR / "runs").is_dir() else []
    if n := sum(_rm(f) for f in runs):
        freed += n
        done.append(f"{len(runs)} old run logs {_fmt(n)}")
    caches = [p for p in (root / "jarvis").rglob("__pycache__")] + [p for p in (root / "tests").rglob("__pycache__")]
    if n := sum(_rm(p) for p in caches):
        freed += n
        done.append(f"bytecode caches {_fmt(n)}")
    tmp = [p for p in Path("/tmp").glob("kurama-*") if p.stat().st_mtime < time.time() - 3600]
    if n := sum(_rm(p) for p in tmp):
        freed += n
        done.append(f"temp folders {_fmt(n)}")
    music = HOME / ".cache/kurama-music"
    try:
        from jarvis.core import music as m
        playing = m.running()
    except Exception:  # noqa: BLE001
        playing = True
    if music.exists() and not playing and (n := _rm(music)):
        freed += n
        done.append(f"song cache {_fmt(n)}")
    from jarvis.core import store
    busy = {Path(w["state"].get("tmp") or "").name for w in store.watches_list(("active", "paused")) if w["kind"] == "ytdl"}
    parts = [f for f in ytdl.out_dir().rglob("*") if f.is_file() and f.name not in busy
             and (f.suffix in (".part", ".ytdl") or ".part-Frag" in f.name) and f.stat().st_mtime < time.time() - 86400]
    if n := sum(_rm(f) for f in parts):
        freed += n
        done.append(f"{len(parts)} leftover video parts {_fmt(n)}")
    if not done:
        return "KURAMA is already clean (no old logs, caches or leftovers). Your chats, memory and videos stay."
    return f"Cleaned KURAMA: freed {_fmt(freed)} ({', '.join(done)}). Your chats, memory, settings and videos stay."


def word(action: str) -> str:
    """'RAM' / 'memory' / 'disk' / 'kurama' ... -> ram | storage | kurama (unknown words stay as they are)."""
    a = (action or "").strip().lower()
    return "ram" if a in ("ram", "memory", "cpu", "processes", "optimize", "optimise") else \
        "storage" if a in ("storage", "disk", "space", "cache", "caches", "drive") else \
        "kurama" if a in ("self", "yourself", "app", config.ASSISTANT_NAME.lower(), *config.ASSISTANT_NAMES) else a


def run(action: str) -> str:
    a = word(action)
    if a == "ram":
        return ram()
    if a == "storage":
        return storage()
    if a == "kurama":
        return kurama()
    return "Say clean RAM, clean storage or clean KURAMA."
