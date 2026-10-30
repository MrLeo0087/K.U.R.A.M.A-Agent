"""gesture_control: start/stop the user's hand-gesture media/YouTube control (camera + OpenCV + MediaPipe) (safe).

Runs in its own process and venv (config.VISION_PYTHON), so KURAMA itself never loads OpenCV/MediaPipe.
Only one camera feature at a time; the camera turns off when it's stopped (or 'q' in its window).
"""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
from typing import Literal

from jarvis.core import config
from jarvis.core.registry import tool

PID_FILE = config.DATA_DIR / "gesture.pid"


def _pid() -> int | None:
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def start() -> str:
    if _pid():
        return "Hand gesture control is already on."
    if not (config.GESTURE_DIR / "main.py").is_file():
        return f"error: gesture module not found in {config.GESTURE_DIR}"
    if not os.path.exists(config.VISION_PYTHON):
        return "error: the vision environment is missing (data/vision_venv: pip install mediapipe pyautogui)"
    Path(config.LOG_DIR).mkdir(parents=True, exist_ok=True)
    log = open(config.LOG_DIR / "gesture.log", "ab")
    p = subprocess.Popen([config.VISION_PYTHON, str(config.ROOT / "scripts" / "gesture_runner.py"), str(config.GESTURE_DIR)],
                         stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    PID_FILE.write_text(str(p.pid))
    return ("Hand gesture control is on. Show your left hand to the camera to control volume, play/pause, "
            "full screen and YouTube. Press Q in its window or tell me to stop it.")


def stop() -> str:
    pid = _pid()
    if not pid:
        return "Hand gesture control isn't running."
    try:
        os.killpg(pid, signal.SIGTERM)
    except OSError:
        pass
    PID_FILE.unlink(missing_ok=True)
    return "Hand gesture control is off and the camera is free."


@tool(group="media", safety="safe",
      description="Turn hand-gesture control of media/YouTube (camera) on or off, or check it.")
def gesture_control(action: Literal["on", "off", "status"] = "on") -> str:
    """Hand gesture media control.

    Args:
        action: on = start the camera gesture control, off = stop it, status = is it running.
    """
    if action == "off":
        return stop()
    if action == "status":
        return "Hand gesture control is on." if _pid() else "Hand gesture control is off."
    return start()
