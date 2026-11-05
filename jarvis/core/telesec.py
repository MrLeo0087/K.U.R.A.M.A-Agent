"""Telegram security: a PIN for risky actions, plus a /lock switch.

Two independent walls (PINs live in .env — config.TELEGRAM_RISKY_PIN / TELEGRAM_LOCK_PIN):
  - Risky PIN  : running a risky action (shutdown, delete, shell, send a file/folder, camera/video, screenshot,
                 location, guard, clicking/typing on the screen) needs the PIN once per config.TELEGRAM_PIN_WINDOW_S (30 min). Harmless things
                 (status, weather, reminders) never ask.
  - /lock      : a panic switch — while locked, EVERY risky action is blocked no matter what, until /unlock <pin>
                 (the lock PIN). Use it if your phone goes missing.

State is in the kv store (shared across processes). Only the owner's own chat reaches the bot in the first place;
this is the second/third wall for when someone has the unlocked phone.
"""
from __future__ import annotations

import re
import time

from jarvis.core import config, store

_LOCKED = "tg_locked"
_PIN_UNTIL = "tg_pin_ok_until"

# What counts as risky (matched against the user's message text — covers both direct /commands and agent requests)
_RISKY = re.compile(
    r"\b(?:shut\s*down|shutdown|power\s*off|turn\s*off\s+(?:the\s+)?(?:laptop|computer|pc)|restart|reboot|log\s*out|"
    r"suspend|sleep\s+(?:the\s+)?(?:laptop|computer|pc)|"
    r"delete|remove|rm\b|erase|wipe|format|uninstall|"
    r"shell|terminal|sudo|run\s+(?:this|the)\s+command|execute|"
    # sending files/folders off the laptop (data exfiltration), or a bare resend ("send it/this/that")
    r"send\b[^.\n]*\b(?:folder|file|files|document|zip|pdf|photo|picture|image|video|clip|clipboard)\b|"
    r"send\b[^.\n]*\bto\s+(?:my\s+)?(?:telegram|phone|mobile)\b|"
    r"\b(?:send|share|forward|upload)\s+(?:me\s+)?(?:it|this|that|them|the\s+\w+)\b|"
    r"camera|webcam|photo\s+(?:from|of)|selfie|/camera|/photo|/video|/vid|/rec|record\b|"
    r"screenshot|screen\s*shot|/screen|"
    r"where(?:'s| is)?\s+(?:my\s+)?laptop|/where|/locate|/here|/track|/history|location\s+of\s+(?:my\s+)?laptop|"
    r"guard|/guard|/claude\s+(?:yes|allow|say|status)\b|"
    r"kill\b|stop\s+(?:the\s+)?process|install\b|"
    r"remote\s+desktop|rust\s*desk|/control|control\s+(?:my\s+)?laptop|"
    # driving the laptop's screen (screen agent): clicking, typing, pressing keys, tasks "on screen"/"in <app>"
    r"^(?:please\s+)?(?:click|tap|double\s*click|type|press|hit)\s|on\s+(?:the\s+)?screen)\b", re.I)

# commands that are always allowed even while locked / without a PIN (safety + control of the lock itself)
_ALWAYS = {"/lock", "/unlock", "/help", "/start", "/status", "/stop"}


def is_locked() -> bool:
    return store.kv_get(_LOCKED, "0") == "1"


def lock() -> str:
    store.kv_set(_LOCKED, "1")
    store.kv_set(_PIN_UNTIL, "0")  # also drop any open PIN window
    return ("Locked. Every risky action from Telegram is blocked now. Send /unlock <pin> to unlock. "
            "(Use this if your phone is lost.)")


def unlock(pin: str) -> str:
    if (pin or "").strip() != str(config.TELEGRAM_LOCK_PIN):
        return "Wrong PIN. KURAMA stays locked."
    store.kv_set(_LOCKED, "0")
    return "Unlocked. Risky actions are available again."


def pin_ok() -> bool:
    try:
        return time.time() < float(store.kv_get(_PIN_UNTIL, "0") or 0)
    except ValueError:
        return False


def verify_pin(pin: str) -> bool:
    """Open the risky-action window if the PIN matches."""
    if (pin or "").strip() == str(config.TELEGRAM_RISKY_PIN):
        store.kv_set(_PIN_UNTIL, str(time.time() + config.TELEGRAM_PIN_WINDOW_S))
        return True
    return False


def looks_like_pin(text: str) -> bool:
    return bool(re.fullmatch(r"\s*/?\d{3,8}\s*", text or ""))


def is_risky(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    cmd = t.split()[0].split("@")[0].lower()
    if cmd in _ALWAYS:
        return False
    from jarvis.core.remotedesk import STOP_RE
    if STOP_RE.match(t):  # turning remote desktop OFF is a safety action, never gated
        return False
    if cmd.startswith("/") and _risky_command(cmd[1:]):
        return True
    return bool(_RISKY.search(t))


# the phone commands that show / reach / drive the laptop (a word boundary can't come before '/': '/screen', '/photo',
# '/where', '/control', '/clip'... were never asked for the PIN, 11-04)
_RISKY_CMDS = {"screen", "camera", "photo", "video", "vid", "rec", "record", "where", "locate", "find", "here", "track",
               "history", "guard", "control", "rustdesk", "clip", "sendfile", "send", "file", "files", "shutdown",
               "restart", "reboot", "sleep", "suspend", "logout", "run", "shell", "cmd", "type", "click", "press",
               "kill", "install", "delete", "trash", "lock_folder"}
# tools a '/<tool>' command runs that show, send or change the laptop
_RISKY_TOOLS = {"screenshot", "read_text", "scan_qr", "app_control", "dictate", "send_file_telegram", "find_and_send",
                "send_last_result", "remote_desktop", "location_history", "laptop_guard", "find_my_phone", "clipboard",
                "clipboard_history", "write_clipboard", "run_command", "run_python", "write_file", "move_path", "copy_path",
                "code_to_file", "folder_lock", "download_file", "backup", "share_wifi", "wifi_share", "gesture_control"}


def _risky_command(name: str) -> bool:
    if name in _RISKY_CMDS:
        return True
    from jarvis.core import registry
    t = registry.REGISTRY.get(name)
    return t is not None and (name in _RISKY_TOOLS or registry.safety_of(t) != "safe")


def gate(text: str) -> str | None:
    """Return None if the message may proceed, else the reply to send instead (locked / needs PIN)."""
    from jarvis.core.remotedesk import wants_password
    always = wants_password(text)  # handing out the remote desktop password asks the PIN EVERY time
    if not always and not is_risky(text):
        return None
    if is_locked():
        return "KURAMA is locked. Send /unlock <pin> first."
    if always:
        return "Send your PIN to get a new remote desktop password."
    if pin_ok():
        return None
    return ("This is a protected action. Send your PIN to run it (it stays unlocked for "
            f"{int(config.TELEGRAM_PIN_WINDOW_S // 60)} min).")
