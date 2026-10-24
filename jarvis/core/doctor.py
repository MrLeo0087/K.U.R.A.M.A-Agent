"""Laptop doctor: "why is my laptop slow?" answered from real measurements, with fixes it can do for you (0 tokens).

check(): RAM/swap pressure and who uses it (grouped per app: all Chrome processes count as Chrome), CPU hogs over a
short sample, temperature, disks almost full, and known culprits (idle Jupyter kernels, tracker indexing, snap or
apt updates, stuck processes). Each finding comes with a fix; the ones KURAMA can do (stop idle kernels, free a port,
stop a process) always ask first.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field

import psutil

from jarvis.core import config

ME = {os.getpid(), os.getppid()}


@dataclass
class Report:
    findings: list[str] = field(default_factory=list)  # "problem -> fix" lines, worst first
    facts: list[str] = field(default_factory=list)
    kernels: list[tuple[int, float, float]] = field(default_factory=list)  # (pid, MB, idle minutes)


def _gb(b: float) -> str:
    return f"{b / 1e9:.1f} GB" if b >= 1e9 else f"{b / 1e6:.0f} MB"


def app_name(p: psutil.Process) -> str:
    try:
        name = p.name()
        cmd = " ".join(p.cmdline()[:3]).lower()
    except psutil.Error:
        return "?"
    low = name.lower()
    for key, label in (("chrome", "Chrome"), ("chromium", "Chromium"), ("brave", "Brave"), ("firefox", "Firefox"),
                       ("code", "VS Code"), ("slack", "Slack"), ("discord", "Discord"), ("telegram", "Telegram"),
                       ("spotify", "Spotify"), ("gnome-shell", "GNOME Shell"), ("gjs", "GNOME extensions")):
        if low.startswith(key) or (key == "code" and "/code" in cmd and "electron" in cmd):
            return label
    if "kurama_wallpaper" in cmd:  # the window and its WebKit page are one thing to the user
        return "KURAMA screen"
    if low.startswith("webkit"):
        try:
            parent = " ".join(p.parent().cmdline()[:3]) if p.parent() else ""
        except psutil.Error:
            parent = ""
        return "KURAMA screen" if "kurama_wallpaper" in parent else "WebKit"
    if "ipykernel" in cmd or "jupyter" in cmd:
        return "Jupyter"
    if "jarvis" in cmd:
        return "KURAMA"
    if low.startswith("python"):
        try:
            script = next((a for a in p.cmdline()[1:] if a.endswith(".py") or not a.startswith("-")), "")
        except psutil.Error:
            script = ""
        return f"python {os.path.basename(script)}".strip()
    return name


def memory_by_app(limit: int = 6) -> list[tuple[str, float, int]]:
    """[(app, bytes, process count)] biggest first (RSS summed per app)."""
    groups: dict[str, list[float]] = {}
    for p in psutil.process_iter(["pid"]):
        try:
            rss = p.memory_info().rss
        except psutil.Error:
            continue
        groups.setdefault(app_name(p), []).append(rss)
    out = sorted(((a, sum(v), len(v)) for a, v in groups.items()), key=lambda t: t[1], reverse=True)
    return out[:limit]


def cpu_hogs(sample_s: float = 0.6, limit: int = 4) -> list[tuple[str, float, int]]:
    procs = []
    for p in psutil.process_iter(["pid"]):
        try:
            p.cpu_percent(None)
            procs.append(p)
        except psutil.Error:
            continue
    time.sleep(sample_s)
    out = []
    for p in procs:
        try:
            c = p.cpu_percent(None)
        except psutil.Error:
            continue
        if c >= 15 and p.pid not in ME:
            out.append((app_name(p), c, p.pid))
    return sorted(out, key=lambda t: t[1], reverse=True)[:limit]


def idle_kernels(min_idle_min: float | None = None) -> list[tuple[int, float, float]]:
    """Jupyter kernels that used no CPU for a while: (pid, MB, minutes idle-ish = age when CPU time is tiny)."""
    out = []
    min_idle = config.DOCTOR_KERNEL_IDLE_MIN if min_idle_min is None else min_idle_min
    for p in psutil.process_iter(["pid", "cmdline", "create_time"]):
        cmd = " ".join(p.info.get("cmdline") or [])
        if "ipykernel" not in cmd and "ipykernel_launcher" not in cmd:
            continue
        try:
            age_min = (time.time() - p.info["create_time"]) / 60
            cpu = p.cpu_times()
            busy = cpu.user + cpu.system
            pct = p.cpu_percent(interval=0.2)
            mb = p.memory_info().rss / 1e6
        except psutil.Error:
            continue
        if age_min >= min_idle and pct < 1.0:
            out.append((p.info["pid"], mb, age_min if busy < 5 else min(age_min, busy)))
    return sorted(out, key=lambda t: t[1], reverse=True)


def temperature() -> float | None:
    try:
        temps = psutil.sensors_temperatures()
    except Exception:
        return None
    for key in ("coretemp", "k10temp", "acpitz", "acpitz_0", "cpu_thermal"):
        for e in temps.get(key, []):
            if e.current:
                return float(e.current)
    return None


def check() -> Report:
    r = Report()
    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    apps = memory_by_app()
    r.facts.append(f"RAM {vm.percent:.0f}% used ({_gb(vm.used)} of {_gb(vm.total)}), swap {sw.percent:.0f}%")
    r.facts.append("Memory: " + ", ".join(f"{a} {_gb(b)}" + (f" ({n} procs)" if n > 3 else "") for a, b, n in apps[:5]))
    if vm.percent >= config.DOCTOR_RAM_WARN:
        top = apps[0]
        r.findings.append(f"RAM is {vm.percent:.0f}% full; {top[0]} uses the most ({_gb(top[1])}). Close what you "
                          f"don't need" + (" (each Chrome tab is its own process)" if "Chrom" in top[0] else "") + ".")
    if sw.percent >= 50 and sw.total:
        r.findings.append(f"Swap is {sw.percent:.0f}% used: the disk is standing in for RAM, which makes everything "
                          f"slow. Freeing RAM fixes it.")
    r.kernels = idle_kernels()
    if r.kernels:
        mb = sum(k[1] for k in r.kernels)
        r.findings.append(f"{len(r.kernels)} idle Jupyter kernel(s) hold {mb:.0f} MB. I can stop them "
                          f"(say 'free some RAM').")
    hogs = cpu_hogs()
    load = os.getloadavg()[0] / (psutil.cpu_count() or 1) * 100
    r.facts.append(f"CPU load {load:.0f}%" + ("; busy: " + ", ".join(f"{a} {c:.0f}%" for a, c, _ in hogs)
                                               if hogs else ""))
    culprits = {"tracker-miner": "GNOME file indexing (tracker) is busy; it settles by itself",
                "snapd": "a snap update is running", "unattended-upgr": "system updates are installing",
                "apt": "a package install/update is running", "packagekitd": "software updates are being checked",
                "kswapd": "the kernel is swapping memory (RAM is too full)"}
    for a, c, pid in hogs:
        for key, why in culprits.items():
            if key in a.lower():
                r.findings.append(f"{why} ({c:.0f}% CPU).")
                break
        else:
            if c >= 80:
                r.findings.append(f"{a} uses {c:.0f}% CPU (PID {pid}). If it's not something you're running on "
                                  f"purpose, I can stop it.")
    if (t := temperature()) is not None:
        r.facts.append(f"CPU temperature {t:.0f}°C")
        if t >= config.DOCTOR_TEMP_WARN:
            r.findings.append(f"The CPU is hot ({t:.0f}°C), so it slows itself down. Check the vents, use a flat "
                              f"surface, and switch to balanced power mode.")
    for mount in ("/", *[str(p) for p in config.SEARCH_ROOTS if str(p).startswith("/media")]):
        try:
            du = psutil.disk_usage(mount)
        except OSError:
            continue
        if du.percent >= 90:
            r.findings.append(f"Disk {mount} is {du.percent:.0f}% full ({_gb(du.free)} free); a nearly full disk "
                              f"slows the system. Say 'what is using my disk space'.")
    zombies = sum(1 for p in psutil.process_iter(["status"]) if p.info.get("status") == psutil.STATUS_ZOMBIE)
    if zombies >= 5:
        r.findings.append(f"{zombies} zombie processes (finished programs nobody cleaned up); a restart of the "
                          f"app that started them clears them.")
    if not r.findings:
        r.findings.append("Nothing looks wrong right now: RAM, CPU, temperature and disks are fine.")
    return r


def text(r: Report) -> str:
    return "\n".join(r.findings) + "\n\n" + "\n".join(r.facts)


# ---------------------------------------------------------------- ports and stopping things
def listeners(port: int | None = None) -> list[tuple[int, int, str]]:
    """[(port, pid, app)] listening TCP sockets (yours; others' show without a name)."""
    out = []
    try:
        conns = psutil.net_connections(kind="tcp")
    except psutil.Error:
        conns = []
    for c in conns:
        if c.status != psutil.CONN_LISTEN or not c.laddr:
            continue
        if port and c.laddr.port != port:
            continue
        name = "?"
        if c.pid:
            try:
                p = psutil.Process(c.pid)
                name = f"{app_name(p)}: {' '.join(p.cmdline()[:4])[:80]}"
            except psutil.Error:
                pass
        out.append((c.laddr.port, c.pid or 0, name))
    return sorted(set(out))


def stop(pids: list[int]) -> list[str]:
    done = []
    for pid in pids:
        if pid in ME or pid <= 1:
            continue
        try:
            p = psutil.Process(pid)
            name = app_name(p)
            p.terminate()
            try:
                p.wait(3)
            except psutil.TimeoutExpired:
                p.kill()
            done.append(f"{name} (PID {pid})")
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            done.append(f"PID {pid}: not allowed (another user's process)")
    return done


def find(target: str) -> list[psutil.Process]:
    t = target.strip().lower()
    if t.isdigit():
        try:
            return [psutil.Process(int(t))]
        except psutil.Error:
            return []
    out = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        if p.info["pid"] in ME:
            continue
        cmd = " ".join(p.info.get("cmdline") or []).lower()
        if t == (p.info.get("name") or "").lower() or (len(t) >= 4 and t in cmd and "jarvis" not in cmd):
            out.append(p)
    return out


PORT_RE = re.compile(r"\b(\d{2,5})\b")
