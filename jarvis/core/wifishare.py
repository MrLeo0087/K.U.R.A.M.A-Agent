"""Send to phone over Wi-Fi: serve one file/folder on the LAN with a secret link + QR code. 0 tokens.

No internet and no Telegram 50 MB limit: the phone (same Wi-Fi) opens the link or scans the QR and downloads at full
Wi-Fi speed. The server (scripts/wifi_share_server.py) is its own small process, only answers under a random token,
and exits after config.WIFI_SHARE_IDLE_MIN idle minutes. One share at a time.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
from pathlib import Path

from jarvis.core import config, store

log = logging.getLogger(__name__)
_SERVER = Path(__file__).resolve().parents[2] / "scripts" / "wifi_share_server.py"
_KEY = "wifi_share"


def lan_ip() -> str | None:
    try:
        out = subprocess.run(["ip", "-4", "route", "get", "1.1.1.1"], capture_output=True, text=True,
                             timeout=5).stdout
        if m := re.search(r"\bsrc\s+(\d+\.\d+\.\d+\.\d+)", out):
            return m.group(1)
    except (OSError, subprocess.SubprocessError):
        pass
    try:  # offline: any non-loopback address on an interface
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return None if ip.startswith("127.") else ip
    except OSError:
        return None


def _free_port(start: int = 8765) -> int:
    for port in range(start, start + 40):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return 0


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return Path(f"/proc/{pid}/cmdline").read_bytes().find(b"wifi_share_server") >= 0
    except (OSError, ValueError):
        return False


def stop() -> str:
    try:
        st = eval_state()
    except ValueError:
        st = {}
    pid = int(st.get("pid") or 0)
    store.kv_set(_KEY, "")
    if pid and _alive(pid):
        os.kill(pid, signal.SIGTERM)
        return "Stopped the Wi-Fi share. The link no longer works."
    return "No Wi-Fi share is running."


def eval_state() -> dict:
    import json
    raw = store.kv_get(_KEY) or ""
    return json.loads(raw) if raw else {}


def qr_png(url: str) -> Path | None:
    if not shutil.which("qrencode"):
        return None
    out = Path(config.DATA_DIR) / "wifi_share_qr.png"
    try:
        subprocess.run(["qrencode", "-s", "10", "-m", "2", "-o", str(out), url], capture_output=True, timeout=10,
                       check=True)
        return out
    except (OSError, subprocess.SubprocessError):
        return None


def start(target: Path, show_qr: bool = True) -> dict:
    """Share `target`; returns {url, qr, name} or {error}."""
    import json
    if not target.exists():
        return {"error": f"{target} doesn't exist"}
    ip = lan_ip()
    if not ip:
        return {"error": "the laptop isn't on a Wi-Fi/LAN network right now"}
    stop()
    port, token = _free_port(), secrets.token_urlsafe(6)
    if not port:
        return {"error": "no free port for the share"}
    p = subprocess.Popen([sys.executable, "-I", str(_SERVER), str(target), str(port), token,
                          str(config.WIFI_SHARE_IDLE_MIN)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    url = f"http://{ip}:{port}/{token}/"
    store.kv_set(_KEY, json.dumps({"pid": p.pid, "url": url, "path": str(target)}))
    qr = qr_png(url)
    if qr and show_qr and shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", str(qr)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    return {"url": url, "qr": str(qr) if qr else "", "name": target.name, "dir": target.is_dir()}


def status_text(r: dict) -> str:
    if "error" in r:
        return f"error: {r['error']}"
    what = "folder" if r["dir"] else "file"
    qr = " Scan the QR code on the laptop screen, or open" if r["qr"] else " Open"
    return (f"Sharing the {what} {r['name']} over Wi-Fi.{qr} this on your phone (same Wi-Fi):\n{r['url']}\n"
            f"It stops after {config.WIFI_SHARE_IDLE_MIN} idle minutes, or say 'stop wifi share'.")
