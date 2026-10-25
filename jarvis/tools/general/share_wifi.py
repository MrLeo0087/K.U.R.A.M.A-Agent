"""share_wifi: show a QR code of the current Wi-Fi so a phone/guest can scan to join (0 tokens) (safe).

The password is read locally (nmcli, the user's own saved connection) and goes ONLY into the QR image shown on the
laptop screen; it is never returned to the chat, the LLM or the logs.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from jarvis.core import config
from jarvis.core.registry import tool


def _nm(*args: str) -> str:
    return subprocess.run(["nmcli", *args], capture_output=True, text=True, timeout=10).stdout.strip()


def _esc(v: str) -> str:
    return re.sub(r'([\\;,:"])', r"\\\1", v)  # WIFI: QR escaping (\ ; , : ")


def wifi_qr_payload(ssid: str, key_mgmt: str, psk: str) -> str:
    kind = "nopass" if not psk else ("WEP" if "wep" in key_mgmt.lower() else "WPA")
    return f"WIFI:T:{kind};S:{_esc(ssid)};" + (f"P:{_esc(psk)};" if psk else "") + ";"


@tool(group="desktop", safety="safe",
      description="Share the current Wi-Fi: show a QR code on the laptop screen that a phone can scan to join "
                  "(the password stays on the laptop).")
def share_wifi() -> str:
    """Show the Wi-Fi QR code."""
    for b in ("nmcli", "qrencode"):
        if not shutil.which(b):
            return f"error: {b} is missing (sudo apt install {'network-manager' if b == 'nmcli' else 'qrencode'})"
    active = [ln.split(":") for ln in _nm("-t", "-f", "NAME,TYPE", "connection", "show", "--active").splitlines()]
    name = next((n for n, t in (a[:2] for a in active if len(a) >= 2) if t == "802-11-wireless"), None)
    if not name:
        return "You're not connected to a Wi-Fi network right now."
    info = _nm("-s", "-g", "802-11-wireless.ssid,802-11-wireless-security.key-mgmt,802-11-wireless-security.psk",
               "connection", "show", name).splitlines() + ["", "", ""]
    ssid, mgmt, psk = info[0] or name, info[1], info[2]
    out = Path(config.DATA_DIR) / "wifi_qr.png"
    subprocess.run(["qrencode", "-s", "12", "-m", "2", "-o", str(out), wifi_qr_payload(ssid, mgmt, psk)],
                   capture_output=True, timeout=10, check=False)
    if not out.exists():
        return "error: couldn't make the QR code"
    subprocess.Popen(["xdg-open", str(out)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    import threading
    threading.Timer(120, lambda: out.unlink(missing_ok=True)).start()  # the image holds the password: don't keep it
    return f"The QR code for Wi-Fi '{ssid}' is on the laptop screen. Scan it with the phone's camera to join."
