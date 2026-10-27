"""Which program uses which port (0 tokens, psutil): 'what is running on port 8000', 'show my open ports'.

Only listening TCP ports. Your own processes show name, command, project folder and age; system ones (other users,
no permission) show as 'system'. Stopping one goes through kill_app ('free port 8000', asks first; KURAMA itself and
system processes are never killed).
"""
from __future__ import annotations

import os
import time

import psutil

SKIP_HOSTS = ("127.0.0.53", "127.0.0.54")  # systemd-resolved


def listening() -> dict[int, dict]:
    """{port: {pid, host}} for every listening TCP port."""
    out: dict[int, dict] = {}
    try:
        conns = psutil.net_connections(kind="tcp")
    except (psutil.Error, OSError):
        return out
    for c in conns:
        if c.status != psutil.CONN_LISTEN or not c.laddr or c.laddr.ip in SKIP_HOSTS:
            continue
        cur = out.get(c.laddr.port)
        if cur is None or (cur["pid"] is None and c.pid):
            out[c.laddr.port] = {"pid": c.pid, "host": c.laddr.ip}
    return out


def pid_on(port: int) -> int | None:
    return (listening().get(port) or {}).get("pid")


def _ago(t: float) -> str:
    s = max(0, time.time() - t)
    return f"{int(s // 60)} min" if s < 3600 else f"{s / 3600:.1f} h" if s < 86400 else f"{int(s // 86400)} days"


def describe(pid: int | None) -> str:
    """'node vite (project civic-report, pid 4242, 2.1 h)' / 'system'."""
    if not pid:
        return "a system service"
    try:
        p = psutil.Process(pid)
        with p.oneshot():
            name, cmd, started = p.name(), p.cmdline(), p.create_time()
            try:
                cwd = os.path.basename(p.cwd())
            except psutil.Error:
                cwd = ""
    except psutil.Error:
        return f"pid {pid}"
    args = [os.path.basename(a) if a.startswith("/") else a for a in cmd[1:4] if not a.startswith("-")]
    what = " ".join(args)[:50]
    kurama = "jarvis" in " ".join(cmd)
    return (f"{name}{' ' + what if what else ''} ("
            + ("KURAMA, " if kurama else (f"project {cwd}, " if cwd and cwd != os.path.basename(os.path.expanduser('~')) else ""))
            + f"pid {pid}, running {_ago(started)})")


def check(port: int) -> str:
    info = listening().get(port)
    if not info:
        return f"Port {port} is free, nothing is using it."
    who = describe(info["pid"])
    where = "only this laptop" if info["host"].startswith("127.") or info["host"] == "::1" else "the whole network"
    tip = "" if not info["pid"] or "KURAMA" in who else f" Say 'free port {port}' to stop it."
    return f"Port {port} is used by {who}, open to {where}.{tip}"


def list_all() -> str:
    ports = listening()
    if not ports:
        return "No program is listening on any port."
    mine = [(p, i) for p, i in sorted(ports.items()) if i["pid"]]
    system = [p for p, i in sorted(ports.items()) if not i["pid"]]
    lines = [f"{p}: {describe(i['pid'])}" for p, i in mine]
    if system:
        lines.append("System: " + ", ".join(map(str, system)))
    return f"{len(ports)} ports in use:\n" + "\n".join(lines)
