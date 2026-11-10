"""Your Android phone from the laptop (plan 11-09 phase 9), free, local Wi-Fi / USB, 0 tokens:

- "show my phone": the phone's screen in a window you can click and type in (scrcpy over adb, USB or Wi-Fi).
- "ring my phone", "send this file / link / text to my phone" over Wi-Fi (GSConnect on the laptop + the KDE Connect
  app on the phone; already installed here, the phone just has to be paired once).
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
SETUP_SCRCPY = ("To see and control the phone's screen: 1) in a terminal: sudo apt install scrcpy adb  2) on the "
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


def screen(addr: str = "") -> str:
    """The phone's screen in a window (scrcpy)."""
    if not shutil.which("scrcpy") or not _adb():
        return "scrcpy / adb aren't installed yet. " + SETUP_SCRCPY
    from jarvis.core import store
    addr = addr.strip() or (store.kv_get(ADB_KEY) or "")
    if addr:
        subprocess.run([_adb(), "connect", addr], capture_output=True, text=True, timeout=15)
        store.kv_set(ADB_KEY, addr)
    devs = [ln.split("\t")[0] for ln in subprocess.run([_adb(), "devices"], capture_output=True, text=True,
                                                       timeout=15).stdout.splitlines()[1:] if "\tdevice" in ln]
    if not devs:
        return ("No phone found by adb: plug in the USB cable (allow the laptop on the phone), or turn on Wireless "
                "debugging and say 'phone wifi <ip>:<port>'.")
    subprocess.Popen(["scrcpy", "-s", devs[0], "--max-size", "1280", "--video-bit-rate", "4M", "--stay-awake",
                      "--window-title", "My phone"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    return "📱 Your phone's screen is opening in a window: click and type there. Close the window to stop."


def status() -> str:
    lines = []
    p = _phone() if GSC.exists() else None
    lines.append(f"Wi-Fi link (GSConnect): {'installed' if GSC.exists() else 'not installed'}; phone: "
                 + (f"{p['name']} ({'connected' if p['connected'] else 'paired, not reachable now'})" if p else "not paired"))
    lines.append(f"Screen (scrcpy): {'ready' if shutil.which('scrcpy') and _adb() else 'not installed'}")
    if not p:
        lines.append(SETUP_GSC)
    if not (shutil.which("scrcpy") and _adb()):
        lines.append(SETUP_SCRCPY)
    return "\n".join(lines)
