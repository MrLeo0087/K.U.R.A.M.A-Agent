"""Short system sounds for alarms, timers and reminders (freedesktop sound theme via paplay; no Python audio)."""
from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

from jarvis.core import config

THEME = Path("/usr/share/sounds/freedesktop/stereo")
SOUNDS = {"alarm": "alarm-clock-elapsed.oga", "timer": "complete.oga", "reminder": "message-new-instant.oga",
          "bell": "bell.oga"}


def play(kind: str = "bell", times: int = 1, gap_s: float = 0.4) -> bool:
    """Play a sound `times` times in the background. False when sounds are off or nothing can play them."""
    exe = shutil.which("paplay")
    path = THEME / SOUNDS.get(kind, SOUNDS["bell"])
    if not config.SOUNDS or not exe or not path.is_file():
        return False

    def run() -> None:
        for _ in range(max(1, times)):
            try:
                subprocess.run([exe, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            except (OSError, subprocess.SubprocessError):
                return
            threading.Event().wait(gap_s)
    threading.Thread(target=run, name="sound", daemon=True).start()
    return True
