"""Your Android phone and the laptop over Wi-Fi with KDE Connect (owner 11-10: "keep KDE Connect for sharing large
files"; the screen-mirroring feature was removed). Free, local network, 0 tokens:

- "share this to my phone": the file goes over Wi-Fi (fast, any size; a folder as a zip); Telegram only when the
  phone isn't reachable.
- "ring my phone", send a link / text, "pair my phone".
The laptop side is GSConnect (the GNOME version of KDE Connect); the phone runs the KDE Connect app.
Nothing runs while you don't use it (owner 11-10: "not a single byte of RAM when not using"): GSConnect is turned on
for a phone action and off GSC_IDLE_S later; "close my phone" stops it at once.
"""
from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path

EXT = "gsconnect@andyholmes.github.io"
GSC = Path.home() / ".local/share/gnome-shell/extensions" / EXT / "service/daemon.js"
GSC_IDLE_S = 600
_gsc_timer: list = [None]

SETUP_GSC = ("To pair your phone over Wi-Fi (once): open the KDE Connect app on the phone (same Wi-Fi as the laptop) "
             "and say 'pair my phone'; then tap Accept on the phone.")
FIREWALL = ("the laptop's firewall must let KDE Connect in — run once: sudo ufw allow 1714:1764/udp && "
            "sudo ufw allow 1714:1764/tcp")


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


# --- on only while used ----------------------------------------------------------------------------------------
def gsc_on(wait_s: float = 8.0) -> None:
    """GSConnect on (it is off while unused), the phone given a few seconds to reconnect; off again GSC_IDLE_S
    after the last use."""
    if shutil.which("gnome-extensions"):
        subprocess.run(["gnome-extensions", "enable", EXT], capture_output=True, timeout=10)
        t0 = time.monotonic()
        while time.monotonic() - t0 < wait_s and not any(d["connected"] for d in devices()):
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


def close() -> str:
    """'close my phone': the Wi-Fi link stops (0 RAM left)."""
    gsc_off()
    return "📱 Phone link closed: nothing of it runs now."


def _kde_conflict() -> str:
    """KDE's own kdeconnectd running next to GSConnect: both answer the phone (port 1716) and pairing goes nowhere."""
    try:
        r = subprocess.run(["pgrep", "-f", "libexec/kdeconnectd"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    if not r.stdout.strip():
        return ""
    for pid in r.stdout.split():
        subprocess.run(["kill", pid], capture_output=True, timeout=5)  # stopped now (it comes back after a login)
    return ("(I stopped KDE's own KDE Connect program: it ran next to GSConnect and caught your phone's requests. "
            "To remove it for good, with its extra menu apps: sudo apt remove kdeconnect)")


# --- actions -----------------------------------------------------------------------------------------------------
def reachable() -> bool:
    if not GSC.exists():
        return False
    gsc_on()
    p = _phone()
    return bool(p and p["connected"])


def _send(action: list[str], what: str) -> str:
    if not GSC.exists():
        return "GSConnect isn't installed on the laptop (GNOME extension 'GSConnect')."
    gsc_on()
    p = _phone()
    if p is None:
        return "Your phone isn't paired yet. " + SETUP_GSC
    if not p["connected"]:
        return f"{p['name']} is paired but not reachable now: is it on the same Wi-Fi with KDE Connect running?"
    r = _gsc("-d", p["id"], *action)
    if r is None or r.returncode != 0:
        return f"error: KDE Connect didn't send it ({(r.stderr if r else '').strip()[:120]})."
    return f"📱 {what} → {p['name']}."


def pair() -> str:
    """'pair my phone': the Wi-Fi link on, KDE's duplicate program stopped, a pair request sent (accept on the phone)."""
    if not GSC.exists():
        return "GSConnect isn't installed on the laptop (GNOME extension 'GSConnect')."
    note = _kde_conflict()
    gsc_on(wait_s=10)
    found = next((d for d in devices() if d["connected"]), None)
    if found is None:
        return ("📱 The Wi-Fi link is on, but your phone isn't visible. Check: 1) the phone is on the SAME Wi-Fi and "
                f"the KDE Connect app is open (pull down to refresh its list); 2) {FIREWALL}. Then say 'pair my phone' "
                f"again. {note}").strip()
    if found["paired"]:
        return f"📱 {found['name']} is already paired: 'share this to my phone', 'ring my phone' work. {note}".strip()
    _gsc("-d", found["id"], "--pair")
    return (f"📱 Pair request sent to {found['name']}: tap ACCEPT on the phone now (if the laptop asks instead, accept "
            f"the notification at the top of the screen). {note}").strip()


def ring() -> str:
    """Over Wi-Fi; when the phone isn't paired / reachable: Google Find My Device (it rings from anywhere)."""
    out = _send(["--ring"], "Ringing")
    if out.startswith("📱 Ringing"):
        return out
    from jarvis.tools.general.find_my_phone import find_my_phone
    return f"{out.split(':')[0]}. " + find_my_phone(phone="android", want="open")


def share_file(path: str) -> str:
    """A file (or a folder, zipped) to the phone over Wi-Fi; Telegram when the phone isn't reachable."""
    f = Path(path).expanduser()
    if not f.exists():
        return f"error: {f} doesn't exist"
    if not reachable():
        from jarvis.tools.general.send_file_telegram import send_file_telegram
        return "📱 Your phone isn't on the Wi-Fi link right now, so it went by Telegram: " + send_file_telegram(str(f))
    if f.is_dir():
        from jarvis.tools.general.send_file_telegram import folder_mb, too_broad, zip_dir
        if (why := too_broad(f)) is not None:
            return why
        if (mb := folder_mb(f)) > 4000:
            return f"{f.name} is {mb / 1024:.1f} GB: too big to zip and send. Pick the files or a smaller folder."
        f = zip_dir(f)
    out = _send(["--share-file", str(f)], f"Sent {f.name} over Wi-Fi ({f.stat().st_size / 1e6:.1f} MB)")
    if not out.startswith("📱 Sent"):  # the Wi-Fi send failed: Telegram, so it still arrives
        from jarvis.tools.general.send_file_telegram import send_file_telegram
        return f"📱 Wi-Fi didn't work ({out[:80]}), so it went by Telegram: " + send_file_telegram(path)
    return out


def share_link(url: str) -> str:
    return _send(["--share-link", url], "Opened the link on the phone")


def share_text(text: str) -> str:
    return _send(["--share-text", text], "Sent the text (it's on the phone's clipboard)")


def status() -> str:
    p = _phone() if GSC.exists() else None
    lines = [f"Wi-Fi link (KDE Connect): {'installed' if GSC.exists() else 'not installed'}; phone: "
             + (f"{p['name']} ({'connected' if p['connected'] else 'paired, not reachable now'})" if p else "not paired")]
    if not p:
        lines.append(SETUP_GSC)
    return "\n".join(lines)
