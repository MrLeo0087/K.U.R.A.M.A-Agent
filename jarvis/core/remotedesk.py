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


def _restart() -> None:
    """Restart the rustdesk GUI/app so a config change takes effect (user-level, no sudo)."""
    try:
        subprocess.run(["pkill", "-x", "rustdesk"], capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass
    time.sleep(1)
    _ensure_running()


def _new_password() -> str:
    # a fresh password every time remote desktop is turned on, so it never stays a fixed standing risk
    alphabet = string.ascii_lowercase + string.digits
    pw = "".join(secrets.choice(alphabet) for _ in range(8))
    store.kv_set(_PW_KEY, pw)
    return pw


def _config_path():
    from pathlib import Path
    return Path.home() / ".config" / "rustdesk" / "RustDesk2.toml"


def _ensure_unattended() -> None:
    """Set RustDesk to accept a password without anyone clicking 'accept' at the laptop (unattended access)."""
    p = _config_path()
    try:
        text = p.read_text() if p.exists() else ""
    except OSError:
        return
    wanted = {"approve-mode": "'password'", "verification-method": "'use-permanent-password'"}
    lines = text.splitlines()
    if "[options]" not in text:
        lines += ["", "[options]"]
    out, done = [], set()
    for ln in lines:
        key = ln.split("=", 1)[0].strip() if "=" in ln else ""
        if key in wanted:
            out.append(f"{key} = {wanted[key]}")
            done.add(key)
        else:
            out.append(ln)
    # add any missing keys right after [options]
    idx = next((i for i, ln in enumerate(out) if ln.strip() == "[options]"), None)
    if idx is not None:
        for key, val in wanted.items():
            if key not in done:
                out.insert(idx + 1, f"{key} = {val}")
    try:
        p.write_text("\n".join(out) + "\n")
    except OSError as e:
        log.warning("couldn't write rustdesk config: %s", e)


def get_id() -> str | None:
    r = _run(["--get-id"])
    rid = (r.stdout.strip() if r and r.returncode == 0 else "")
    return rid or None


def start() -> dict:
    """Launch RustDesk with unattended access and a fresh password; returns {id, password} or {error}."""
    if not installed():
        return {"error": INSTALL_HINT}
    _ensure_unattended()  # password-only access, no "accept" prompt at the laptop
    _restart()            # pick up the config + make sure the service/app is fresh
    pw = _new_password()
    _run(["--password", pw])  # set the permanent (unattended) password to the fresh one
    time.sleep(2)
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
    return (f"Remote desktop is on (unattended — no need to accept at the laptop). In the RustDesk app on your "
            f"phone, enter:\nID: {fix['id']}\nPassword: {fix['password']}\n"
            f"This password is NEW each time you turn remote desktop on, so it's not a fixed standing risk. "
            f"The ID stays the same. Keep these private while connected.")
