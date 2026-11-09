"""Resource guard (worker "resource_guard") and the snapshot behind the resource_status tool.

Checks RAM, swap, CPU (5-minute average of samples), disk ("/" and the home filesystem) and KURAMA's
own memory (PSS: shared libraries split fairly) against the CLAUDE.md caps (core < 600 MB, everything
< 1.5 GB). An alert names the top 3 memory hogs. A metric alerts once, then stays quiet for
RESOURCE_COOLDOWN_S (2 h) even if it dips and comes back (RAM hovering at 89-91% used to alert every
15 min). When KURAMA's own memory grows past RESOURCE_TRIM_AT of its cap, it first cleans itself
(gc + malloc_trim: returns freed memory to the OS, nothing is stopped) and only alerts if still high.
Muted alerts ("no RAM warnings for 20 minutes") are handled by notify.
"""
from __future__ import annotations

import collections
import ctypes
import gc
import os
import time
from pathlib import Path

import psutil

from jarvis.core import config, notify
from jarvis.workers.base import Worker

MB = 1024 * 1024


def top_memory(n: int = 3) -> list[tuple[str, int, float]]:
    """[(name, pid, rss MB)] of the biggest processes."""
    procs = []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        mi = p.info.get("memory_info")
        if mi:
            procs.append((p.info.get("name") or "?", p.info["pid"], mi.rss / MB))
    return sorted(procs, key=lambda x: -x[2])[:n]


_NOT_APPS = ("python", "python3", "systemd", "Xorg", "gnome-shell", "pipewire", "pulseaudio", "dbus-daemon", "mpv",
             "kworker", "snapd", "gsd-", "tracker-miner", "Xwayland", "WebKitWebProcess")


def user_apps(n: int = 2) -> list[tuple[str, float]]:
    """[(app, MB)] of the biggest apps you opened (only at alert time: PSS reads each process) (processes grouped by name; KURAMA and the desktop left out)."""
    groups: dict[str, float] = {}
    for p in psutil.process_iter(["name", "memory_info", "username"]):
        mi, name = p.info.get("memory_info"), (p.info.get("name") or "").split("/")[0]
        if mi and name and not name.startswith(_NOT_APPS) and p.info.get("username") == psutil.Process().username():
            key = {"brave": "brave", "chrome": "chrome", "code": "code"}.get(name.split("-")[0].lower(), name)
            groups[key] = groups.get(key, 0.0) + _pss(p, mi.rss) / MB  # (PSS: shared memory counted once)
    return [(a, mb) for a, mb in sorted(groups.items(), key=lambda kv: -kv[1]) if mb >= 300][:n]


def _pss(p, rss: int) -> int:
    """Proportional set size (Linux smaps_rollup); RSS when it can't be read."""
    try:
        return p.memory_full_info().pss
    except (psutil.Error, AttributeError, OSError):
        return rss


def trim_memory() -> None:
    """Give KURAMA's freed memory back to the OS (this process: the server runs the workers inside)."""
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass


def jarvis_rss() -> tuple[float, float]:
    """(core MB, total MB): PSS of `python -m jarvis…` processes; core excludes the workers."""
    core = total = 0.0
    for p in psutil.process_iter(["pid", "cmdline", "memory_info"]):
        cmd = p.info.get("cmdline") or []
        mi = p.info.get("memory_info")
        if not mi or "-m" not in cmd:
            continue
        i = cmd.index("-m")
        mod = cmd[i + 1] if i + 1 < len(cmd) else ""
        if mod != "jarvis" and not mod.startswith("jarvis."):
            continue
        rss = _pss(p, mi.rss) / MB
        total += rss
        if not mod.startswith("jarvis.workers"):
            core += rss
    return core, total


def disks() -> dict[str, float]:
    """{mount label: used %} for / and home (one entry when they share a filesystem)."""
    out: dict[str, float] = {}
    seen = set()
    for label, path in (("/", "/"), ("home", str(Path.home()))):
        try:
            dev = os.stat(path).st_dev
            if dev in seen:
                continue
            seen.add(dev)
            out[label] = psutil.disk_usage(path).percent
        except OSError:
            continue
    return out


def snapshot(cpu_avg: float | None = None) -> dict:
    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    if cpu_avg is None:  # no sample history (tool call): 5-min load average as % of all cores
        try:
            cpu_avg = min(100.0, os.getloadavg()[1] / (psutil.cpu_count() or 1) * 100)
        except OSError:
            cpu_avg = psutil.cpu_percent(interval=0.2)
    core, total = jarvis_rss()
    return {"ram_pct": vm.percent, "ram_used_gb": round((vm.total - vm.available) / MB / 1024, 1),
            "ram_total_gb": round(vm.total / MB / 1024, 1), "swap_pct": sw.percent, "cpu_pct": round(cpu_avg, 1),
            "disk": disks(), "jarvis_core_mb": round(core), "jarvis_total_mb": round(total)}


def summary(snap: dict | None = None) -> str:
    s = snap or snapshot()
    disk = ", ".join(f"{k} {v:.0f}%" for k, v in s["disk"].items())
    return (f"RAM {s['ram_pct']:.0f}% ({s['ram_used_gb']}/{s['ram_total_gb']} GB), swap {s['swap_pct']:.0f}%, "
            f"CPU {s['cpu_pct']:.0f}% (5-min avg), disk {disk}; KURAMA {s['jarvis_core_mb']} MB core / "
            f"{s['jarvis_total_mb']} MB total")


def checks(s: dict) -> dict[str, tuple[float, float, str]]:
    """metric -> (value, threshold, unit)."""
    out = {"ram": (s["ram_pct"], config.RAM_ALERT_PCT, "%"), "swap": (s["swap_pct"], config.SWAP_ALERT_PCT, "%"),
           "cpu": (s["cpu_pct"], config.CPU_ALERT_PCT, "%"),
           "jarvis_core": (s["jarvis_core_mb"], config.JARVIS_CORE_MAX_MB, " MB"),
           "jarvis_total": (s["jarvis_total_mb"], config.JARVIS_TOTAL_MAX_MB, " MB")}
    for label, pct in s["disk"].items():
        out[f"disk {label}"] = (pct, config.DISK_ALERT_PCT, "%")
    return out


_SAY = {"jarvis_core": "KURAMA core", "jarvis_total": "KURAMA total", "ram": "RAM", "cpu": "CPU", "swap": "swap"}


class ResourceGuard(Worker):
    name = "resource_guard"
    interval_s = config.RESOURCE_GUARD_INTERVAL_S

    def __init__(self, interval_s: float | None = None):
        super().__init__(interval_s)
        n = max(2, int(300 / self.interval_s))
        self.cpu_samples: collections.deque[float] = collections.deque(maxlen=n)
        self.alerting: dict[str, float] = {}  # metric -> last alert time (present = above threshold)
        self.sent: dict[str, float] = {}  # metric -> last alert time (kept after recovery: cooldown)
        self.last: dict = {}
        self.last_trim = 0.0
        self.trims = 0

    def setup(self) -> None:
        psutil.cpu_percent(interval=None)  # prime: the first call always returns 0

    def info(self) -> dict:
        return {"summary": summary(self.last)} if self.last else {}

    def tick(self) -> None:
        self.cpu_samples.append(psutil.cpu_percent(interval=None))
        avg = sum(self.cpu_samples) / len(self.cpu_samples)
        snap = snapshot(cpu_avg=avg)
        now = time.time()
        if (snap["jarvis_core_mb"] >= config.JARVIS_CORE_MAX_MB * config.RESOURCE_TRIM_AT
                and now - self.last_trim >= config.RESOURCE_TRIM_EVERY_S):
            self.last_trim, before = now, snap["jarvis_core_mb"]
            trim_memory()
            self.trims += 1
            snap = snapshot(cpu_avg=avg)
            self.log.info("trimmed KURAMA memory: %s -> %s MB", before, snap["jarvis_core_mb"])
        if len(self.cpu_samples) < self.cpu_samples.maxlen:
            snap["cpu_pct_partial"] = True
        self.last = snap
        self.evaluate(snap)

    def evaluate(self, snap: dict, now: float | None = None) -> list[str]:
        """Apply thresholds + hysteresis; returns the metrics alerted this time."""
        now = time.time() if now is None else now
        fired = []
        for metric, (value, limit, unit) in checks(snap).items():
            if metric == "cpu" and snap.get("cpu_pct_partial"):
                continue  # wait for a full 5-minute window
            margin = config.RESOURCE_HYSTERESIS_PCT if unit == "%" else limit * config.RESOURCE_HYSTERESIS_PCT / 100
            if value >= limit:
                last = self.sent.get(metric)
                if last is None or now - last >= config.RESOURCE_COOLDOWN_S:
                    self.alerting[metric] = self.sent[metric] = now
                    fired.append(metric)
            elif metric in self.alerting and value < limit - margin:
                del self.alerting[metric]
                self.log.info("%s recovered (%.0f%s)", metric, value, unit)
        if fired:
            hogs = ", ".join(f"{n} {mb:.0f} MB" for n, _, mb in top_memory(3))
            say = lambda m: _SAY.get(m, m)  # noqa: E731 - the user hears "KURAMA core", never "jarvis_core"
            parts = [f"{say(m)} {checks(snap)[m][0]:.0f}{checks(snap)[m][2]} (limit {checks(snap)[m][1]:.0f})"
                     for m in fired]
            tip, did, rows = "", "", []
            if any(m in ("ram", "swap", "jarvis_core") for m in fired):  # the fix, as a 0-token command (and "yes")
                from jarvis.core import nextstep
                apps = user_apps(2)
                if apps:  # plan 11-09 phase 3: it acts: one tap closes the biggest app (like clicking X: it asks to save)
                    tip = " " + nextstep.offer(f"close {apps[0][0]}", f"Say yes to close {apps[0][0]}"
                                                                     f" ({apps[0][1] / 1024:.1f} GB), or tap a button.")
                    rows = [[{"text": f"❌ Close {a} ({mb / 1024:.1f} GB)", "callback_data": f"/close {a}"[:64]}]
                            for a, mb in apps]
                else:
                    tip = " " + nextstep.offer("clean my ram", "Say 'clean my RAM' (or yes) to free memory.")
                rows.append([{"text": "🧹 Free RAM", "callback_data": "/freeram"}])
            if any(m.startswith("disk") for m in fired):  # the safe part at once, the rest as buttons
                from jarvis.core import cleanup
                try:
                    freed, done = cleanup.auto_storage()
                except Exception as e:  # noqa: BLE001
                    freed, done = 0, []
                    self.log.warning("auto storage clean failed: %s", e)
                did = (f" I freed {cleanup._fmt(freed)} by myself ({', '.join(done)})." if done
                       else " Nothing safe was left to delete by myself.")
                rows += [[{"text": "🧹 Clean ML caches too", "callback_data": "/clean storage"}],
                         [{"text": "📊 What fills the disk", "callback_data": "/disk"}]]
            notify.notify("Resource alert: " + ", ".join(map(say, fired)),
                          f"{'; '.join(parts)}. Top memory: {hogs}.{did}{tip}".rstrip(), level="warning",
                          source="resource_guard", markup={"inline_keyboard": rows} if rows else None)
        return fired
