"""Remote desktop (RustDesk): start it with unattended access and report the ID + password, so you can control
the whole laptop screen from your phone's RustDesk app. 0 chat tokens.

RustDesk is a free, open-source remote-desktop app. KURAMA sets a fresh random password (via a root-owned
helper, scripts/kurama-rustdesk.sh) that expires after config.REMOTE_PW_TTL_MIN, and reads the device ID. The actual screen control is RustDesk's.
"""
from __future__ import annotations

import logging
import re
import secrets
import shutil
import string
import subprocess
import time

from jarvis.core import config, store

log = logging.getLogger(__name__)
_EXP_KEY = "rustdesk_expires_at"
KEEP_ALIVE_S = 300  # scheduler checks the RustDesk service at most every 5 min
_last_check = 0.0
INSTALL_HINT = ("RustDesk isn't installed. Install it once:  sudo apt install -y ./rustdesk.deb  "
                "(download the .deb from https://github.com/rustdesk/rustdesk/releases) — then ask me again.")
# RustDesk only lets root set the password, so a tiny root-owned helper does it (one-time setup by the owner)
SETUP_HINT = ("Remote desktop needs a one-time setup so I can set a short-lived password. Run on the laptop:\n"
              "sudo install -o root -g root -m 755 scripts/kurama-rustdesk.sh /usr/local/sbin/kurama-rustdesk && "
              "echo \"$USER ALL=(root) NOPASSWD: /usr/local/sbin/kurama-rustdesk\" | sudo tee /etc/sudoers.d/kurama-rustdesk "
              "&& sudo chmod 440 /etc/sudoers.d/kurama-rustdesk\n(from the KURAMA folder), then ask me again.")
START_RE = re.compile(
    r"^(?:please\s+)?(?:/control(?:\s+laptop)?|"
    r"(?:activate|enable|start|turn\s+on|open|give\s+me|i\s+want)\s+(?:the\s+|my\s+|a\s+)?"
    r"(?:remote(?:\s+(?:control|desktop|access))?|rust\s*desk|real[\s-]*time\s+(?:preview|view|screen))"
    r"(?:\s+(?:of\s+)?(?:my\s+|the\s+)?laptop)?|"
    r"(?:control|access|see)\s+(?:my\s+|the\s+)?(?:whole\s+)?laptop(?:\s+(?:remotely|from\s+(?:my\s+)?(?:phone|mobile|anywhere)))?|"
    r"(?:give\s+me\s+(?:a\s+)?)?real[\s-]*time\s+preview(?:\s+of\s+(?:my\s+|the\s+)?laptop)?)\s*[.!?]*$", re.I)
CHANGE_RE = re.compile(r"^(?:please\s+)?(?:/change_?pass(?:word)?|/change_?pin|/newpass|(?:change|reset|new|rotate)\s+(?:the\s+|my\s+)?"
                       r"(?:remote(?:\s+(?:desktop|control|access))?|rust\s*desk)\s+password)\s*[.!?]*$", re.I)
TELEGRAM_ONLY = ("For safety, the remote desktop password is only given on Telegram. Send /control (or /changepass) "
                 "to the KURAMA bot; it asks your PIN first, then sends a new password.")
STOP_RE = re.compile(r"^(?:please\s+)?(?:/control\s+off|(?:stop|end|close|turn\s+off|disable|kill)\s+(?:the\s+|my\s+)?"
                     r"(?:remote(?:\s+(?:control|desktop|access))?|rust\s*desk))\s*[.!?]*$", re.I)


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


def service_up() -> bool:
    """The root `rustdesk --service` is what puts the laptop online; the window alone isn't enough."""
    try:
        return subprocess.run(["systemctl", "is-active", "--quiet", "rustdesk"], timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def ensure_service() -> tuple[bool, str]:
    """Start/enable the service (also undoes a 'Stop service' click) via the helper. Returns (up, error text)."""
    if service_up():
        return True, ""
    ok, err = _helper("ensure")
    for _ in range(10):
        if service_up():
            return True, ""
        time.sleep(1)
    return False, err if not ok else "the service didn't start"


def keep_alive(now: float | None = None) -> bool:
    """Called by the scheduler worker: so remote desktop works from far away, restart the service if it stopped.
    Returns True when it had to restart it."""
    global _last_check
    now = now or time.time()
    if now - _last_check < KEEP_ALIVE_S or not installed():
        return False
    _last_check = now
    if service_up():
        return False
    up, err = ensure_service()
    log.warning("rustdesk service was down -> %s", "restarted" if up else "restart failed: " + err)
    return up


def _new_password() -> str:
    # a fresh password every time remote desktop is turned on; it expires after REMOTE_PW_TTL_MIN
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


def _helper(*args: str) -> tuple[bool, str]:
    """Run the root-owned helper via `sudo -n` (never prompts). Returns (ok, error text)."""
    try:
        r = subprocess.run(["sudo", "-n", config.REMOTE_HELPER, *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    return r.returncode == 0, (r.stderr or r.stdout).strip()


def expires_at() -> float:
    try:
        return float(store.kv_get(_EXP_KEY) or 0)
    except ValueError:
        return 0.0


def stop() -> str:
    """Kill the password now: set a random unknown one. A session already connected is not dropped by RustDesk."""
    store.kv_set(_EXP_KEY, "0")
    if not installed():
        return "Remote desktop isn't installed."
    ok, err = _helper("off")
    if not ok:
        log.warning("rustdesk off failed: %s", err)
        return "I couldn't reset the RustDesk password (" + (err or "helper failed") + ")."
    return "Remote desktop is off. The old password no longer works."


def expire_if_due(now: float | None = None) -> bool:
    """Called by the scheduler worker: rotate the password away once its time is up."""
    exp = expires_at()
    if exp and (now or time.time()) >= exp:
        stop()
        log.info("rustdesk password expired")
        return True
    return False


def get_id() -> str | None:
    r = _run(["--get-id"])
    rid = (r.stdout.strip() if r and r.returncode == 0 else "")
    return rid or None


def start() -> dict:
    """Turn on unattended access with a fresh password that works for REMOTE_PW_TTL_MIN; {id, password, minutes} or {error}."""
    if not installed():
        return {"error": INSTALL_HINT}
    up, err = ensure_service()
    if not up:
        log.warning("rustdesk service won't start: %s", err)
        return {"error": SETUP_HINT if "usage" in err or "password" in err else
                "RustDesk's background service won't start (" + err + "), so the laptop looks offline to your phone."}
    _ensure_running()
    pw = _new_password()
    ok, err = _helper("on", pw)
    if not ok:
        log.warning("rustdesk on failed: %s", err)
        return {"error": SETUP_HINT}
    store.kv_set(_EXP_KEY, str(time.time() + config.REMOTE_PW_TTL_MIN * 60))
    rid = get_id()
    for _ in range(6):  # the ID can take a moment on first launch
        if rid:
            break
        time.sleep(1)
        rid = get_id()
    if not rid:
        return {"error": "RustDesk is on but I couldn't read its ID yet. Open the RustDesk window on the laptop "
                         "once, then ask again."}
    return {"id": rid, "password": pw, "minutes": int(config.REMOTE_PW_TTL_MIN)}


def wants_password(text: str) -> bool:
    t = (text or "").strip()
    return bool(START_RE.match(t) or CHANGE_RE.match(t))


def status_text(fix: dict) -> str:
    if "error" in fix:
        return fix["error"]
    return (f"Remote desktop is on (no need to accept at the laptop). In the RustDesk app on your phone, enter:\n"
            f"ID: {fix['id']}\nPassword: {fix['password']}\n"
            f"The password works for {fix['minutes']} minutes, then stops working (a session already open stays "
            f"connected). Say 'stop remote desktop' to end it sooner.")
