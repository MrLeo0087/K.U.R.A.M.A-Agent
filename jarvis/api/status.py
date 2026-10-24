"""Laptop + KURAMA status snapshot for /api/v1/status (LAPTOP-LOCAL: it describes the machine the API
runs on; a future server deployment needs a small "laptop agent" to report this instead).

Cheap by design: psutil counters are O(1) except the process walk, which is cached for
procs_refresh_s; the whole snapshot is cached for status_cache_s and shared by every client.
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import sys
import threading
import time
from typing import Any

import psutil

from jarvis.api.settings import Settings

_MB = 1048576
_GB = 1073741824
STARTED = time.time()


def _round(x: float, n: int = 1) -> float:
    return round(float(x), n)


class StatusCollector:
    def __init__(self, settings: Settings, engine: Any = None) -> None:
        self.s = settings
        self.engine = engine
        self._lock = threading.Lock()
        self._snap: dict | None = None
        self._snap_ts = 0.0
        self._procs: dict = {"by_rss": [], "by_cpu": [], "count": 0}
        self._procs_ts = 0.0
        self._me = psutil.Process()
        self._ncpu = psutil.cpu_count() or 1
        psutil.cpu_percent(None)  # prime the interval-less counters
        self._me.cpu_percent(None)
        self._net_prev: tuple[float, int, int] | None = None  # (monotonic, rx bytes, tx bytes)
        self._temp: float | None = None
        self._temp_ts = -1e9

    # --- pieces ---
    def _processes(self) -> dict:
        now = time.monotonic()
        if now - self._procs_ts < self.s.procs_refresh_s and self._procs["count"]:
            return self._procs
        rows = []
        # process_iter caches Process objects between calls, so cpu_percent is a real delta
        for p in psutil.process_iter(["pid", "name", "memory_info", "cpu_percent", "username"]):
            info = p.info
            mi = info.get("memory_info")
            if mi is None:
                continue
            rows.append({"pid": info["pid"], "name": (info.get("name") or "?")[:40],
                         "rss_mb": _round(mi.rss / _MB), "cpu": _round((info.get("cpu_percent") or 0.0) / self._ncpu)})
        self._procs = {"by_rss": sorted(rows, key=lambda r: r["rss_mb"], reverse=True)[:5],
                       "by_cpu": sorted(rows, key=lambda r: r["cpu"], reverse=True)[:5], "count": len(rows)}
        self._procs_ts = now
        return self._procs

    @staticmethod
    def _freq_ghz() -> float | None:
        with contextlib.suppress(Exception):
            f = psutil.cpu_freq()
            if f and f.current:
                return _round(f.current / 1000, 2)
        return None

    def _temp_c(self) -> float | None:
        """CPU package temperature; hwmon reads are cached for 10 s (they are the slowest part)."""
        now = time.monotonic()
        if now - self._temp_ts < 10:
            return self._temp
        self._temp_ts, self._temp = now, None
        with contextlib.suppress(Exception):
            temps = psutil.sensors_temperatures() or {}
            for key in ("coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz"):
                vals = [t.current for t in temps.get(key, []) if t.current and t.current > 0]
                if vals:
                    self._temp = _round(max(vals) if key != "coretemp" else vals[0])
                    break
        return self._temp

    def _net(self) -> dict:
        """Bytes/s since the previous snapshot (all interfaces except loopback)."""
        rx = tx = 0
        with contextlib.suppress(Exception):
            for nic, c in psutil.net_io_counters(pernic=True).items():
                if nic != "lo":
                    rx += c.bytes_recv
                    tx += c.bytes_sent
        now = time.monotonic()
        prev, self._net_prev = self._net_prev, (now, rx, tx)
        if prev is None or now - prev[0] <= 0:
            return {"rx_bps": 0, "tx_bps": 0}
        dt = now - prev[0]
        return {"rx_bps": max(0, int((rx - prev[1]) / dt)), "tx_bps": max(0, int((tx - prev[2]) / dt))}

    def _jarvis(self) -> dict:
        eng = self.engine
        out = {"pid": os.getpid(), "rss_mb": _round(self._me.memory_info().rss / _MB),
               "cpu": _round(self._me.cpu_percent(None) / self._ncpu),
               "agent_loaded": "jarvis.core.agent" in sys.modules, "agent_ready": bool(eng and eng.ready),
               "busy": bool(eng and eng.turn_lock.locked()), "pending_confirms": len(eng.pending) if eng else 0,
               "uptime_s": int(time.time() - STARTED)}
        return out

    def _jarvis_data(self, out: dict) -> None:
        from jarvis.core import config, store
        with contextlib.suppress(Exception):
            p = config.WORKERS_STATUS_PATH
            if p.exists():
                out["workers"] = json.loads(p.read_text())
        with contextlib.suppress(Exception):
            jobs = store.jobs_list(self.s.status_jobs, ("queued", "running"))
            out["jobs"] = {"running": sum(j.get("status") == "running" for j in jobs),
                           "queued": sum(j.get("status") == "queued" for j in jobs),
                           "items": [{k: j.get(k) for k in ("id", "title", "kind", "status", "progress", "created")}
                                     for j in jobs]}
        with contextlib.suppress(Exception):
            unread = store.alerts_pending(50)
            out["alerts"] = {"unread": len(unread),
                             "recent": [{k: a.get(k) for k in ("id", "ts", "title", "text", "level", "source")}
                                        for a in store.alerts_recent(self.s.status_alerts)]}
        with contextlib.suppress(Exception):
            from jarvis.core import usage
            u = usage.summary("today")
            out["tokens"] = {"today": u.get("tokens", 0), "calls": u.get("calls", 0),
                             "fastpath_hits": u.get("fastpath_hits", 0), "saved_est": u.get("tokens_saved_est", 0),
                             "budget_pct": u.get("budget_pct_today", {})}

    # --- snapshot ---
    def collect(self, percpu: bool = False) -> dict:
        vm, sw = psutil.virtual_memory(), psutil.swap_memory()
        out: dict[str, Any] = {
            "ts": time.time(),
            "cpu": {"percent": _round(psutil.cpu_percent(None)), "count": self._ncpu,
                    "load": [_round(x, 2) for x in os.getloadavg()] if hasattr(os, "getloadavg") else [],
                    "freq_ghz": self._freq_ghz(), "temp_c": self._temp_c()},
            "net": self._net(),
            "ram": {"total_gb": _round(vm.total / _GB, 2), "used_gb": _round((vm.total - vm.available) / _GB, 2),
                    "available_gb": _round(vm.available / _GB, 2), "percent": _round(vm.percent)},
            "swap": {"total_gb": _round(sw.total / _GB, 2), "used_gb": _round(sw.used / _GB, 2),
                     "percent": _round(sw.percent)},
            "disk": {}, "processes": self._processes(), "jarvis": self._jarvis(),
            "uptime": {"system_s": int(time.time() - psutil.boot_time()), "api_s": int(time.time() - STARTED)},
            "workers": None, "jobs": {"running": 0, "queued": 0, "items": []},
            "alerts": {"unread": 0, "recent": []}, "tokens": {},
        }
        with contextlib.suppress(Exception):
            du = shutil.disk_usage(os.path.expanduser("~"))
            out["disk"] = {"total_gb": _round(du.total / _GB), "used_gb": _round(du.used / _GB),
                           "free_gb": _round(du.free / _GB), "percent": _round(du.used * 100 / du.total)}
        with contextlib.suppress(Exception):
            bat = psutil.sensors_battery()
            if bat is not None:
                secs = bat.secsleft if isinstance(bat.secsleft, int) and bat.secsleft >= 0 else None
                out["battery"] = {"percent": _round(bat.percent), "plugged": bool(bat.power_plugged),
                                  "secs_left": None if bat.power_plugged else secs}
        if percpu:
            out["cpu"]["per_core"] = [_round(x) for x in psutil.cpu_percent(None, percpu=True)]
        self._jarvis_data(out)
        return out

    def snapshot(self, percpu: bool = False) -> dict:
        if percpu:  # per-core is opt-in and never cached
            with self._lock:
                return self.collect(percpu=True)
        with self._lock:
            if self._snap is None or time.monotonic() - self._snap_ts >= self.s.status_cache_s:
                self._snap = self.collect()
                self._snap_ts = time.monotonic()
            return self._snap
