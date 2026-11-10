"""Your Android phone from the laptop (plan 11-09 phase 9), free, local Wi-Fi / USB, 0 tokens:

- "show my phone": the phone's screen in a window you can click and type in (scrcpy over adb, USB or Wi-Fi).
- "ring my phone", "send this file / link / text to my phone" over Wi-Fi (GSConnect on the laptop + the KDE Connect
  app on the phone; already installed here, the phone just has to be paired once).
Nothing runs while you don't use it (owner 11-10: "not a single byte of RAM when not using"): the screen window takes
adb's background server with it when it closes; GSConnect is turned on for a Wi-Fi action and off 10 minutes later;
"close my phone" stops everything at once.
What is missing is said with the exact steps (installing needs your password, so KURAMA never does it itself).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

GSC = Path.home() / ".local/share/gnome-shell/extensions/gsconnect@andyholmes.github.io/service/daemon.js"
ADB_KEY = "phone_adb_addr"

SETUP_GSC = ("To pair your phone over Wi-Fi (once): install 'KDE Connect' from the Play Store, open it on the same "
             "Wi-Fi as the laptop, tap this laptop's name and Pair, then accept on the laptop (top bar → GSConnect).")
SETUP_SCRCPY = ("To see and control the phone's screen: 1) in a terminal: sudo snap install scrcpy  2) on the "
                "phone: Settings → About phone → tap 'Build number' 7 times, then Developer options → USB debugging "
                "ON (and 'Wireless debugging' for Wi-Fi)  3) plug in the USB cable once and allow the laptop. Then say "
                "'show my phone'. For Wi-Fi: say 'phone wifi <ip>:<port>' with the address Wireless debugging shows.")


def _gsc(*args: str, timeout: float = 15) -> subprocess.CompletedProcess | None:
    if not GSC.exists():
        return None
    try:
        return subprocess.run(["gjs", str(GSC), *args] if not GSC.stat().st_mode & 0o111 else [str(GSC), *args],
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def devices() -> list[dict]:
    """[{id, name, connected, paired}] known to GSConnect."""
    r = _gsc("-a")
    out = []
    for ln in (r.stdout if r else "").splitlines():
        parts = ln.split("\t")
        if len(parts) >= 4:
            out.append({"id": parts[0], "name": parts[1], "connected": parts[2] == "true", "paired": parts[3] == "true"})
    return out


def _phone() -> dict | None:
    ds = [d for d in devices() if d["paired"]]
    return next((d for d in ds if d["connected"]), ds[0] if ds else None)


def _send(action: list[str], what: str) -> str:
    if not GSC.exists():
        return "GSConnect isn't installed on the laptop (GNOME extension 'GSConnect'). " + SETUP_GSC
    gsc_on()  # (off while not used: turned on for this, off again 10 min later)
    p = _phone()
    if p is None:
        return "Your phone isn't paired yet. " + SETUP_GSC
    if not p["connected"]:
        return f"{p['name']} is paired but not reachable now: is it on the same Wi-Fi with KDE Connect running?"
    r = _gsc("-d", p["id"], *action)
    if r is None or r.returncode != 0:
        return f"error: GSConnect didn't send it ({(r.stderr if r else '').strip()[:120]})."
    return f"📱 {what} → {p['name']}."


def ring() -> str:
    return _send(["--ring"], "Ringing")


def share_file(path: str) -> str:
    f = Path(path).expanduser()
    if not f.exists():
        return f"error: {f} doesn't exist"
    return _send(["--share-file", str(f)], f"Sent {f.name} over Wi-Fi")


def share_link(url: str) -> str:
    return _send(["--share-link", url], "Opened the link on the phone")


def share_text(text: str) -> str:
    return _send(["--share-text", text], "Sent the text (it's on the phone's clipboard)")


def _adb() -> str:
    return shutil.which("adb") or ""


def _scrcpy() -> str:
    """The newest scrcpy on the laptop (the snap one first: Ubuntu's apt scrcpy 1.25 can't read Android 14+ phones)."""
    for c in ("/snap/bin/scrcpy", shutil.which("scrcpy") or ""):
        if c and Path(c).exists():
            return c
    return ""


def _adb_for(exe: str) -> str:
    """The adb that scrcpy itself uses (the snap has its own)."""
    return "/snap/bin/scrcpy.adb" if exe.startswith("/snap/") and Path("/snap/bin/scrcpy.adb").exists() else (_adb() or "adb")


def close() -> str:
    """'close my phone': the screen window, adb's background server and the Wi-Fi link stop (0 RAM left)."""
    stopped = []
    for adb in {a for a in ("/snap/bin/scrcpy.adb", _adb()) if a and Path(a).exists()}:
        if subprocess.run([adb, "kill-server"], capture_output=True, timeout=10).returncode == 0:
            stopped.append("screen")
    if gsc_off():
        stopped.append("Wi-Fi link")
    return ("📱 Phone link closed" + (f" ({', '.join(dict.fromkeys(stopped))})" if stopped else "")
            + ": nothing of it runs now.")


# GSConnect (the Wi-Fi link: ring / send files) runs only while used: on for a phone action, off GSC_IDLE_S later
EXT = "gsconnect@andyholmes.github.io"
GSC_IDLE_S = 600
_gsc_timer: list = [None]


def gsc_on() -> None:
    import threading
    import time
    if shutil.which("gnome-extensions"):
        subprocess.run(["gnome-extensions", "enable", EXT], capture_output=True, timeout=10)
        for _ in range(20):  # the phone reconnects to the laptop within a few seconds
            if any(d["connected"] for d in devices()):
                break
            time.sleep(0.5)
    if _gsc_timer[0] is not None:
        _gsc_timer[0].cancel()
    _gsc_timer[0] = threading.Timer(GSC_IDLE_S, gsc_off)
    _gsc_timer[0].daemon = True
    _gsc_timer[0].start()


def gsc_off() -> bool:
    """The extension off AND its background service told to quit (disabling alone left it running, 26 MB)."""
    if not shutil.which("gnome-extensions"):
        return False
    ok = subprocess.run(["gnome-extensions", "disable", EXT], capture_output=True, timeout=10).returncode == 0
    if shutil.which("gdbus"):
        subprocess.run(["gdbus", "call", "--session", "--dest", "org.gnome.Shell.Extensions.GSConnect", "--object-path",
                        "/org/gnome/Shell/Extensions/GSConnect", "--method", "org.gtk.Actions.Activate", "quit", "[]",
                        "{}"], capture_output=True, timeout=10)
    return ok


def _version(exe: str) -> tuple[int, int]:
    import re
    meta = Path("/snap/scrcpy/current/meta/snap.yaml")
    if exe.startswith("/snap/") and meta.exists():  # (running the snap's launcher pops notice windows, even for
        out = "scrcpy " + next((ln.split(":", 1)[1].strip() for ln in meta.read_text().splitlines()  # --version)
                                if ln.startswith("version:")), "0.0")
        m = re.search(r"scrcpy (\d+)\.(\d+)", out)
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return (0, 0)
    m = re.search(r"scrcpy (\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def _open(host: str, port: int, t: float = 0.4) -> bool:
    import socket
    s = socket.socket()
    s.settimeout(t)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def find_port(addr: str) -> str:
    """The phone's Wireless-debugging address now: the saved one if it still answers, else its new port (it changes
    every time Wireless debugging is turned off and on; 30000-49999, scanned in ~10 s) checked with adb."""
    import concurrent.futures as cf
    host, _, port = addr.rpartition(":")
    if not host or (port.isdigit() and _open(host, int(port))):
        return addr
    with cf.ThreadPoolExecutor(300) as ex:
        ports = [p for p, ok in zip(range(30000, 50000), ex.map(lambda p: _open(host, p), range(30000, 50000))) if ok]
    adb = "/snap/bin/scrcpy.adb" if Path("/snap/bin/scrcpy.adb").exists() else _adb()
    for p in ports:
        try:
            out = subprocess.run([adb, "connect", f"{host}:{p}"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        if out.startswith(("connected", "already connected")):
            return f"{host}:{p}"
    return ""


def screen(addr: str = "") -> str:
    """The phone's screen in a window (scrcpy), over Wi-Fi when its wireless-debugging address is known."""
    exe = _scrcpy()
    if not exe:
        return "scrcpy isn't installed yet. " + SETUP_SCRCPY
    if _version(exe) < (2, 0):
        return ("Your scrcpy is too old for this phone (Ubuntu's apt version is 1.25; Android 14+ needs 2.0+). Run: "
                "sudo apt remove scrcpy && sudo snap install scrcpy — then say 'show my phone' again.")
    from jarvis.core import store
    addr = addr.strip() or (store.kv_get(ADB_KEY) or "")
    if addr:
        addr = find_port(addr) or addr  # Wireless debugging's port changes when it is turned off / on: found again
        store.kv_set(ADB_KEY, addr)
        target = [f"--tcpip={addr}"]  # scrcpy connects over Wi-Fi itself (its own adb)
    else:
        target = []  # a phone on the USB cable
    import os
    env = {**os.environ, "SNAP_LAUNCHER_NOTICE_ENABLED": "false"}  # the snap's "unofficial build" notice, every run
    args = [exe, *target, "--max-size", "1280", "--max-fps", "30", "--stay-awake",  # (30 fps: half the laptop CPU
            "--window-title", "My phone"]  # of 60, still smooth for reading / typing)
    # when the window closes, the adb background server goes too: nothing of the phone link stays in RAM
    p = subprocess.Popen(["sh", "-c", '"$@"; code=$?; ' + f'"{_adb_for(exe)}" kill-server >/dev/null 2>&1; exit $code',
                          "scrcpy", *args],
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, start_new_session=True, env=env)
    try:
        err = p.communicate(timeout=2.5)[1]  # still running after 2.5 s = it is opening (answer at once, not a job)
    except subprocess.TimeoutExpired:
        return "📱 Your phone's screen is opening in a window (a few seconds): click and type there. Close it to stop."
    last = [ln for ln in (err or "").splitlines() if "ERROR" in ln][-1:] or ["it closed at once"]
    return (f"Couldn't open the phone's screen ({last[0][:160]}). Is Wireless debugging still ON (its port changes "
            f"when it is turned off and on)? Then: /phone screen <ip>:<port> with the address it shows now.")


def status() -> str:
    lines = []
    p = _phone() if GSC.exists() else None
    lines.append(f"Wi-Fi link (GSConnect): {'installed' if GSC.exists() else 'not installed'}; phone: "
                 + (f"{p['name']} ({'connected' if p['connected'] else 'paired, not reachable now'})" if p else "not paired"))
    lines.append(f"Screen (scrcpy): {'ready' if _scrcpy() else 'not installed'}")
    if not p:
        lines.append(SETUP_GSC)
    if not _scrcpy():
        lines.append(SETUP_SCRCPY)
    return "\n".join(lines)
