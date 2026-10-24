"""Runs the user's YouTube/media hand-gesture module (config.GESTURE_DIR/main.py) unchanged, in its own venv.

Adaptations, applied in memory only (the original file is never edited):
- MODEL_PATH points at hand_landmarker.task next to main.py (the file has a Windows path);
- the `keyboard` package (needs root on Linux) is replaced by a tiny shim that sends media keys with xdotool.
Usage: data/vision_venv/bin/python scripts/gesture_runner.py <module_dir>
"""
import os
import re
import runpy  # noqa: F401  (kept for readers: we exec the source the same way runpy would)
import shutil
import subprocess
import sys
import types

KEYS = {"volume up": "XF86AudioRaiseVolume", "volume down": "XF86AudioLowerVolume", "volume mute": "XF86AudioMute",
        "play/pause media": "XF86AudioPlay", "next track": "XF86AudioNext", "previous track": "XF86AudioPrev"}


def _press(name: str) -> None:
    key = KEYS.get(name.lower(), name.upper() if re.fullmatch(r"f\d{1,2}", name.lower()) else name)
    exe = shutil.which("xdotool")
    if exe:
        subprocess.run([exe, "key", "--clearmodifiers", key], check=False)


def main() -> None:
    mod_dir = os.path.abspath(sys.argv[1])
    src_path = os.path.join(mod_dir, "main.py")
    src = open(src_path, encoding="utf-8").read()
    model = os.path.join(mod_dir, "hand_landmarker.task")
    src = re.sub(r"^MODEL_PATH\s*=.*$", f"MODEL_PATH = {model!r}", src, count=1, flags=re.M)
    sys.modules["keyboard"] = types.SimpleNamespace(press_and_release=_press, send=_press, press=_press)
    os.chdir(mod_dir)
    sys.path.insert(0, mod_dir)
    sys.argv = [src_path]
    exec(compile(src, src_path, "exec"), {"__name__": "__main__", "__file__": src_path})


if __name__ == "__main__":
    main()
