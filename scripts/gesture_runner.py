"""Runs the user's YouTube/media hand-gesture module (config.GESTURE_DIR/main.py) unchanged, in its own venv.

Adaptations, applied in memory only (the original file is never edited):
- MODEL_PATH points at hand_landmarker.task next to main.py (the file has a Windows path);
- the `keyboard` package (needs root on Linux) is replaced by a tiny shim that sends media keys with xdotool;
- the camera is SHARED: while a video call is open (a call page in the browser - Facebook / Messenger / Instagram,
  Meet, Zoom, Teams, Jitsi, Discord - or a call app's window), the camera is closed and the module gets blank
  frames, so the call can use it; after the call it opens again. A laptop camera serves one program at a time:
  11-03 a Facebook call said "Couldn't connect to your camera" while gesture control held it.
Usage: data/vision_venv/bin/python scripts/gesture_runner.py <module_dir>
"""
import json
import os
import re
import runpy  # noqa: F401  (kept for readers: we exec the source the same way runpy would)
import shutil
import sqlite3
import subprocess
import sys
import time
import types

KEYS = {"volume up": "XF86AudioRaiseVolume", "volume down": "XF86AudioLowerVolume", "volume mute": "XF86AudioMute",
        "play/pause media": "XF86AudioPlay", "next track": "XF86AudioNext", "previous track": "XF86AudioPrev"}
DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "jarvis.db")
CALL_URL = re.compile(r"(?:facebook|messenger)\.com/(?:groupcall|videocall|call)|instagram\.com/(?:call|direct/call)|"
                      r"meet\.google\.com/[a-z]|zoom\.us/(?:wc|j)/|teams\.(?:microsoft|live)\.com/.*(?:meetup|call)|"
                      r"meet\.jit\.si/|discord\.com/channels/.*call|web\.whatsapp\.com/.*call", re.I)
CALL_WINDOW = re.compile(r"\b(?:zoom meeting|zoom workplace|google meet|microsoft teams|messenger call|facebook call|"
                         r"instagram call|whatsapp call|skype|jitsi|discord.*(?:call|voice connected))\b|^meet - ", re.I)
CHECK_S = 1.0


def _press(name: str) -> None:
    key = KEYS.get(name.lower(), name.upper() if re.fullmatch(r"f\d{1,2}", name.lower()) else name)
    exe = shutil.which("xdotool")
    if exe:
        subprocess.run([exe, "key", "--clearmodifiers", key], check=False)


def call_open() -> bool:
    """A video call is open: a browser tab on a call page (what KURAMA's tab extension last reported) or a call
    app's window title."""
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=1)
        row = con.execute("SELECT value FROM kv WHERE key = 'browser_tab'").fetchone()
        con.close()
        if row:
            tab = json.loads(row[0])
            urls = [tab.get("url") or ""] + [t.get("url") or "" for t in tab.get("tabs") or []]
            if any(CALL_URL.search(u) for u in urls):
                return True
    except (sqlite3.Error, ValueError, OSError):
        pass
    if shutil.which("wmctrl"):
        try:
            out = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=2).stdout
            titles = [ln.split(None, 3)[3] for ln in out.splitlines() if len(ln.split(None, 3)) == 4]
            if any(CALL_WINDOW.search(t) or CALL_URL.search(t) for t in titles):
                return True
        except (OSError, subprocess.SubprocessError):
            pass
    return False


def shared_capture(real_cls, is_call=call_open, now=time.monotonic, sleep=time.sleep):
    """cv2.VideoCapture that lets go of the camera during a call (blank frames meanwhile) and takes it back after."""

    class SharedCapture:
        def __init__(self, *args, **kw):
            self._args, self._kw, self._props = args, kw, {}
            self._cap = real_cls(*args, **kw)
            self._checked, self._paused, self._size = 0.0, False, (720, 1280)

        def set(self, prop, value):
            self._props[prop] = value
            return self._cap.set(prop, value) if self._cap is not None else True

        def get(self, prop):
            return self._cap.get(prop) if self._cap is not None else self._props.get(prop, 0)

        def isOpened(self):  # noqa: N802 - OpenCV's name
            return True

        def release(self):
            if self._cap is not None:
                self._cap.release()
                self._cap = None

        def _blank(self):
            import numpy as np
            sleep(0.2)  # ~5 blank frames a second: almost no CPU while paused
            return True, np.zeros((self._size[0], self._size[1], 3), dtype=np.uint8)

        def read(self):
            t = now()
            if t - self._checked >= CHECK_S:
                self._checked = t
                call = is_call()
                if call and not self._paused:
                    self.release()
                    self._paused = True
                    print("camera released: a video call is open", flush=True)
                elif not call and self._paused:
                    self._cap = real_cls(*self._args, **self._kw)
                    for p, v in self._props.items():
                        self._cap.set(p, v)
                    self._paused = False
                    print("camera back: the call ended", flush=True)
            if self._paused:
                return self._blank()
            ok, frame = self._cap.read()
            if ok and frame is not None:
                self._size = frame.shape[:2]
            return ok, frame

    return SharedCapture


def main() -> None:
    mod_dir = os.path.abspath(sys.argv[1])
    src_path = os.path.join(mod_dir, "main.py")
    src = open(src_path, encoding="utf-8").read()
    model = os.path.join(mod_dir, "hand_landmarker.task")
    src = re.sub(r"^MODEL_PATH\s*=.*$", f"MODEL_PATH = {model!r}", src, count=1, flags=re.M)
    sys.modules["keyboard"] = types.SimpleNamespace(press_and_release=_press, send=_press, press=_press)
    import cv2
    cv2.VideoCapture = shared_capture(cv2.VideoCapture)  # the module's own `cv2.VideoCapture(0)` gets this one
    os.chdir(mod_dir)
    sys.path.insert(0, mod_dir)
    sys.argv = [src_path]
    exec(compile(src, src_path, "exec"), {"__name__": "__main__", "__file__": src_path})


if __name__ == "__main__":
    main()
