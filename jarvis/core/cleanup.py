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


# the desktop's own background services (notifications, file access, phone link...): never offered for closing
_DESKTOP = ("xdg-", "gsd-", "gvfs", "evolution-", "tracker-", "at-spi", "ibus", "kdeconnect", "snapd", "goa-",
            "gnome-", "gjs", "ubuntu-", "update-", "pk", "packagekit", "fwupd", "colord", "geoclue", "dconf")


def _window_pids() -> set[int]:
    """Processes that own a window on the desktop (wmctrl -lp): someone may be using them."""
    import subprocess
    try:
        out = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return {int(f[2]) for f in (line.split(None, 4) for line in out.splitlines()) if len(f) > 2 and f[2].isdigit()}


def idle_background(min_mb: float = config.FREE_RAM_MIN_MB) -> list[tuple[str, list[int], int]]:
    """[(app, pids, RSS bytes)] of the user's apps that NOBODY can be using: no window anywhere in their family (a
    browser's tab processes belong to the browser window), no CPU over a second, at least min_mb, never KURAMA or
    the desktop's own services (kill_app.protected)."""
    import getpass
    import psutil
    from jarvis.tools.general.kill_app import _ancestors, protected
    win = _window_pids()
    if not win:  # can't see the windows (no X / no wmctrl): never guess what is in use
        return []
    me, mine = getpass.getuser(), _ancestors()
    procs = [p for p in psutil.process_iter(["pid", "name", "cmdline", "username", "ppid", "memory_info"])]
    for p in procs:
        try:
            p.cpu_percent(None)
        except psutil.Error:
            pass
    time.sleep(1.0)
    by_pid = {p.pid: p for p in procs}
    windowed_names = {(by_pid[w].info["name"] or "") for w in win if w in by_pid}

    def in_use(p) -> bool:
        q, seen = p, 0
        while q is not None and seen < 40:
            if q.pid in win or (q.info["name"] or "") in windowed_names:
                return True
            q, seen = by_pid.get(q.info.get("ppid") or 0), seen + 1
        return False
    apps: dict[str, tuple[list[int], int, float]] = {}
    for p in procs:
        try:
            if protected(p.info, me, mine) or in_use(p) or not p.info["memory_info"] \
                    or (p.info["name"] or "").lower().startswith(_DESKTOP):
                continue
            cpu = p.cpu_percent(None)
        except psutil.Error:
            continue
        name = (p.info["name"] or "?")[:30]
        pids, rss, c = apps.get(name, ([], 0, 0.0))
        apps[name] = (pids + [p.pid], rss + p.info["memory_info"].rss, c + cpu)
    return sorted(((n, pids, rss) for n, (pids, rss, c) in apps.items() if rss >= min_mb * 1e6 and c < 1.0),
                  key=lambda x: -x[2])


def close_idle_background() -> str:
    """Ask once, then close the idle background apps (politely: SIGTERM, then a kill after 3 s). '' = nothing to do."""
    import psutil
    from jarvis.core import safety
    found = idle_background()
    if not found:
        return ""
    total = sum(r for _, _, r in found)
    names = ", ".join(f"{n} {_fmt(r)}" for n, _, r in found[:8])
    if not safety.ask(f"These run in the background with no window and do nothing right now: {names}. "
                      f"Close them to free about {_fmt(total)}?"):
        return f"Left the background apps running ({names})."
    procs = []
    for _, pids, _ in found:
        for pid in pids:
            try:
                q = psutil.Process(pid)
                q.terminate()
                procs.append(q)
            except psutil.Error:
                continue
    _, alive = psutil.wait_procs(procs, timeout=3)
    for q in alive:
        try:
            q.kill()
        except psutil.Error:
            pass
    return f"Closed {len(found)} idle background app(s) ({names}), about {_fmt(total)}."


def ram() -> str:
    import psutil
    before = psutil.virtual_memory()
    try:
        from jarvis.core import semantic
        semantic.free_now()  # KURAMA's meaning model (~250 MB): it reloads by itself when needed (~0.6 s)
    except Exception:  # noqa: BLE001
        pass
    gc.collect()
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)  # give Python's freed memory back to the system
    except (OSError, AttributeError):
        pass
    by_ram, by_cpu = top_apps()
    closed = close_idle_background()
    after = psutil.virtual_memory()
    freed = max(0, after.available - before.available)
    lines = [f"RAM: {after.percent:.0f}% used, {_fmt(after.available)} free"
             + (f" ({_fmt(freed)} freed from KURAMA's own memory)" if freed > 20e6 else "") + "."]
    if closed:
        lines.append(closed)
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
