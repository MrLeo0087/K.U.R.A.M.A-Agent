"""Shared helpers for the P5b desktop tools (not a tool): find a CLI with shutil.which (clear install
hint when missing), run a fixed argv without a shell, pactl mute state and the xclip clipboard.

Only binaries listed in INSTALL can run here. Tests patch `_exec` and `which`, so no test ever
touches the real volume, brightness, screen lock or clipboard.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

INSTALL = {
    "pactl": "sudo apt install pulseaudio-utils", "playerctl": "sudo apt install playerctl",
    "brightnessctl": "sudo apt install brightnessctl", "wmctrl": "sudo apt install wmctrl",
    "xdotool": "sudo apt install xdotool", "gnome-screenshot": "sudo apt install gnome-screenshot",
    "scrot": "sudo apt install scrot", "xclip": "sudo apt install xclip",
    "loginctl": "it ships with systemd", "systemctl": "it ships with systemd",
    "shutdown": "it ships with systemd",  # scheduled shutdown (shutdown_timer)
    "gnome-screensaver-command": "sudo apt install gnome-screensaver",
    "xdg-screensaver": "sudo apt install xdg-utils",
    # P9a
    "gsettings": "sudo apt install libglib2.0-bin", "upower": "sudo apt install upower",
    "mpv": "sudo apt install mpv", "xdg-open": "sudo apt install xdg-utils",
    "code": "install VS Code (code.visualstudio.com) and its 'code' command",
    # laptop switches + power
    "nmcli": "sudo apt install network-manager", "rfkill": "sudo apt install rfkill",
    "powerprofilesctl": "sudo apt install power-profiles-daemon", "xset": "sudo apt install x11-xserver-utils",
    "gnome-session-quit": "it ships with GNOME",
}


class SysError(RuntimeError):
    """A desktop command is missing, failed or timed out (message is user-facing)."""


def which(binary: str) -> str | None:
    return shutil.which(binary)


def need(binary: str) -> str:
    if binary not in INSTALL:
        raise SysError(f"{binary} is not an allowed system command")
    path = which(binary)
    if not path:
        raise SysError(f"{binary} not found: {INSTALL[binary]}")
    return path


_POWER = {"poweroff", "reboot", "suspend", "hibernate", "halt", "shutdown", "terminate-session", "terminate-user",
          "kill-session", "kill-user", "lock-session", "lock-sessions"}


def power_blocked(argv: list[str]) -> bool:
    """While testing (KURAMA_TESTING, set by tests/conftest.py and never removed), no command may power off,
    reboot, suspend or end the session — a test's leftover thread once outlived its mock and REALLY did."""
    return bool(os.environ.get("KURAMA_TESTING")) and bool(
        set(map(str, argv)) & _POWER or Path(str(argv[0])).name in ("shutdown", "reboot", "poweroff", "gnome-session-quit"))


def _exec(argv: list[str], timeout: float, input_text: str | None, capture: bool) -> subprocess.CompletedProcess:
    if power_blocked(argv):
        raise SysError(f"power command blocked while testing: {' '.join(map(str, argv))}")
    out = subprocess.PIPE if capture else subprocess.DEVNULL
    kw: dict = {"input": input_text} if input_text is not None else {"stdin": subprocess.DEVNULL}
    return subprocess.run(argv, stdout=out, stderr=out, text=True, timeout=timeout, **kw)


def run(argv: list[str], timeout: float = 5.0, input_text: str | None = None, capture: bool = True,
        ok_codes: tuple[int, ...] = (0,)) -> str:
    """Run argv (argv[0] must be in INSTALL) and return stdout; raise SysError with the tool's message."""
    exe = need(argv[0])
    try:
        cp = _exec([exe, *map(str, argv[1:])], timeout, input_text, capture)
    except subprocess.TimeoutExpired:
        raise SysError(f"{argv[0]} timed out after {timeout:g}s") from None
    except OSError as e:
        raise SysError(f"{argv[0]} failed: {e}") from None
    if cp.returncode not in ok_codes:
        msg = ((cp.stderr or "") + "\n" + (cp.stdout or "")).strip()
        raise SysError(msg.splitlines()[0][:200] if msg else f"{argv[0]} exited with code {cp.returncode}")
    return (cp.stdout or "") if capture else ""


def pct(text: str) -> int | None:
    m = re.search(r"(\d{1,3})\s*%", text or "")
    return int(m.group(1)) if m else None


def clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(n)))


# --- pactl mute (speakers = sink, microphone = source) ---
def pactl_muted(kind: str) -> bool:
    out = run(["pactl", f"get-{kind}-mute", f"@DEFAULT_{kind.upper()}@"])
    return "yes" in out.lower()


def pactl_mute(kind: str, action: str) -> bool:
    """action toggle | mute | unmute | status; returns the muted state afterwards."""
    if action != "status":
        value = {"toggle": "toggle", "mute": "1", "unmute": "0"}.get(action)
        if value is None:
            raise SysError(f"unknown action {action!r}: use toggle, mute, unmute or status")
        run(["pactl", f"set-{kind}-mute", f"@DEFAULT_{kind.upper()}@", value])
    return pactl_muted(kind)


# --- clipboard (xclip, CLIPBOARD selection) ---
def clip_get() -> str:
    """Clipboard text ('' when empty or not text)."""
    return run(["xclip", "-selection", "clipboard", "-o"], ok_codes=(0, 1))


def clip_set(text: str) -> None:
    # xclip forks to serve the selection: no pipes kept open, or run() would wait for it.
    run(["xclip", "-selection", "clipboard", "-i"], input_text=text, capture=False)
