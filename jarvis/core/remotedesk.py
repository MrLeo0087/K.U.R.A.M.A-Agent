"""Remote desktop (RustDesk): start it with unattended access and report the ID + password, so you can control
the whole laptop screen from your phone's RustDesk app. 0 chat tokens.

RustDesk is a free, open-source remote-desktop app. KURAMA just launches it, sets a fixed password (kept in the
kv store so it stays the same between calls) and reads the device ID. The actual screen control is RustDesk's.
"""
from __future__ import annotations

import logging
import secrets
import shutil
import string
import subprocess
import time

from jarvis.core import store

log = logging.getLogger(__name__)
_PW_KEY = "rustdesk_password"
INSTALL_HINT = ("RustDesk isn't installed. Install it once:  sudo apt install -y ./rustdesk.deb  "
                "(download the .deb from https://github.com/rustdesk/rustdesk/releases) — then ask me again.")


def installed() -> bool:
    return shutil.which("rustdesk") is not None


def _run(args: list[str], timeout: float = 20) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["rustdesk", *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("rustdesk %s failed: %s", args, e)
        return None


def _is_running() -> bool:
    try:
        return subprocess.run(["pgrep", "-x", "rustdesk"], capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _ensure_running() -> None:
    if _is_running():
        return
    try:
        subprocess.Popen(["rustdesk"], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("couldn't launch rustdesk: %s", e)
    for _ in range(12):  # wait for it to come up and register
        if _is_running():
            break
        time.sleep(0.5)


def _password() -> str:
    pw = store.kv_get(_PW_KEY)
    if not pw:
        alphabet = string.ascii_lowercase + string.digits
        pw = "".join(secrets.choice(alphabet) for _ in range(8))
        store.kv_set(_PW_KEY, pw)
    return pw


def get_id() -> str | None:
    r = _run(["--get-id"])
    rid = (r.stdout.strip() if r and r.returncode == 0 else "")
    return rid or None


def start() -> dict:
    """Launch RustDesk with unattended access; returns {id, password} or {error}."""
    if not installed():
        return {"error": INSTALL_HINT}
    _ensure_running()
    pw = _password()
    _run(["--password", pw])  # set the permanent (unattended) password
    time.sleep(1.5)
    rid = get_id()
    for _ in range(6):  # the ID can take a moment on first launch
        if rid:
            break
        time.sleep(1)
        rid = get_id()
    if not rid:
        return {"error": "RustDesk started but I couldn't read its ID yet — open the RustDesk window on the laptop "
                         "once, then ask again. The password is " + pw + "."}
    return {"id": rid, "password": pw}


def status_text(fix: dict) -> str:
    if "error" in fix:
        return fix["error"]
    return (f"Remote desktop is on. In the RustDesk app on your phone, enter:\n"
            f"ID: {fix['id']}\nPassword: {fix['password']}\n"
            f"Then you have full control of the laptop screen. (Anyone with this ID+password can connect — keep it private.)")
