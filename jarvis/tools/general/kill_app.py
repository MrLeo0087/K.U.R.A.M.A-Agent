"""kill_app: force-quit an app's processes (psutil). SIGTERM, then SIGKILL after 3 s for any that are
still alive (force=True kills at once). Never touches KURAMA, other users' or system processes
(pid < 1000, gnome-shell, Xorg, ...). name "frozen"/"this" targets the focused window's app (xdotool).
Needs confirmation."""
from __future__ import annotations

import getpass
import os
import re

import psutil

from jarvis.core.registry import tool
from jarvis.tools.general import _apps, _sys

PROTECTED = {"gnome-shell", "xorg", "xwayland", "systemd", "gnome-session-binary", "gnome-session",
             "dbus-daemon", "dbus-broker", "pipewire", "pipewire-pulse", "wireplumber", "pulseaudio",
             "gdm", "gdm-x-session", "gsd-xsettings", "mutter", "init", "login", "sshd", "sudo", "polkitd",
             "at-spi-bus-launcher", "ibus-daemon", "gnome-keyring-daemon", "xdg-desktop-portal"}
ACTIVE_WORDS = {"frozen", "not responding", "hung", "stuck", "this", "this app", "active", "current",
                "focused", "this window", "the frozen app", "frozen app"}
WAIT_S = 3.0


def _procs():
    return psutil.process_iter(["pid", "name", "cmdline", "username", "ppid"])


def _ancestors() -> set[int]:
    pids, p = set(), psutil.Process(os.getpid())
    while p is not None:
        pids.add(p.pid)
        try:
            p = p.parent()
        except psutil.Error:
            break
    return pids


def protected(info: dict, me: str, mine: set[int]) -> bool:
    name = (info.get("name") or "").lower()
    cmd = " ".join(info.get("cmdline") or []).lower()
    return (info["pid"] < 1000 or info["pid"] in mine or name in PROTECTED
            or (info.get("username") or me) != me or re.search(r"\bjarvis\b", cmd) is not None)


def _active_pid() -> int | None:
    try:
        return int(_sys.run(["xdotool", "getactivewindow", "getwindowpid"], timeout=3).strip())
    except (_sys.SysError, ValueError):
        return None


def find_targets(name: str) -> tuple[list[psutil.Process], str]:
    """(processes to stop, display label). Protected processes are never returned."""
    me, mine = getpass.getuser(), _ancestors()
    q = _apps.clean_query(name)
    active = None
    if q in ACTIVE_WORDS or not q:
        active = _active_pid()
        if active is None:
            return [], "the focused app"
    terms = {_apps.compact(q)} if not active else set()
    if not active:
        entry, score = _apps.find_app(name)
        if entry and score >= _apps.TOOL_MIN_SCORE:
            terms |= {_apps.compact(entry["exe"]), _apps.compact(entry["name"])}
    terms = {t for t in terms if len(t) >= 3}
    out, label = [], q
    for p in _procs():
        info = p.info
        if protected(info, me, mine):
            continue
        if active:
            if info["pid"] == active:
                out.append(p)
                label = info.get("name") or label
            continue
        exe = os.path.basename((info.get("cmdline") or [""])[0]).lower()
        if any(t in _apps.compact(info.get("name") or "") or (exe and t in _apps.compact(exe)) for t in terms):
            out.append(p)
    if active and out:  # the focused app's children too (browser tabs, renderers)
        kids = [c for c in out[0].children(recursive=True) if not protected(
            {"pid": c.pid, "name": c.name(), "cmdline": [], "username": me}, me, mine)]
        out += kids
    return out, label


def stop(procs: list[psutil.Process], force: bool) -> tuple[int, int]:
    """(terminated cleanly, killed)."""
    if not force:
        for p in procs:
            try:
                p.terminate()
            except psutil.Error:
                pass
        gone, alive = psutil.wait_procs(procs, timeout=WAIT_S)
    else:
        gone, alive = [], procs
    for p in alive:
        try:
            p.kill()
        except psutil.Error:
            pass
    if alive:
        psutil.wait_procs(alive, timeout=WAIT_S)
    return len(gone), len(alive)


@tool(group="apps", safety="confirm", description="Force-quit an app that is frozen or won't close (kills its processes).")
def kill_app(name: str, force: bool = False) -> str:
    """Kill an app.

    Args:
        name: App or process name, or "frozen"/"this" for the focused window's app.
        force: Kill immediately (SIGKILL) instead of asking it to quit first.
    """
    procs, label = find_targets(name)
    if not procs:
        return f"error: no running app matches {name!r} (system and KURAMA processes are never killed)"
    clean, killed = stop(procs, force)
    how = f", {killed} force-killed" if killed else ""
    return f"Closed {label}: {len(procs)} process{'es' if len(procs) != 1 else ''} stopped{how}."
