"""Music without the browser (0 tokens): 'play lofi music' -> mpv plays only the sound of the YouTube results
(yt-dlp), ~30 MB instead of a ~300 MB browser tab. Controlled through mpv's IPC socket: pause / resume / next /
previous / volume / what's playing / stop. mpv quits by itself when the list ends, so nothing stays in memory.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from jarvis.core import config

RESULTS = 8  # 'play lofi' queues the first 8 search results: 'next' moves through them


def _sock() -> str:
    return str(Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "kurama-music.sock")


def _ytdlp() -> str:
    exe = Path(sys.executable).with_name("yt-dlp")
    return str(exe) if exe.exists() else (shutil.which("yt-dlp") or "yt-dlp")


def _send(*command, want: bool = False):
    """One IPC command; the reply's data when want=True. None when mpv isn't running."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect(_sock())
            s.sendall((json.dumps({"command": list(command)}) + "\n").encode())
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
            for line in buf.decode(errors="replace").splitlines():
                d = json.loads(line)
                if "error" in d:
                    return d.get("data") if want else d["error"] == "success"
    except (OSError, ValueError):
        return None
    return None


def running() -> bool:
    return _send("get_property", "pid", want=True) is not None


def play(query: str) -> str:
    """Search YouTube and play the sound of the results (stops what KURAMA played before)."""
    q = (query or "").strip() or "lofi music"
    if not shutil.which("mpv"):
        return "error: mpv isn't installed (sudo apt install mpv)"
    stop(quiet=True)
    try:
        os.unlink(_sock())
    except OSError:
        pass
    subprocess.Popen(["mpv", "--no-video", "--idle=no", "--force-window=no", "--really-quiet", "--no-terminal",
                      f"--input-ipc-server={_sock()}", f"--volume={config.MUSIC_VOLUME}",
                      f"--script-opts=ytdl_hook-ytdl_path={_ytdlp()}", "--ytdl-format=bestaudio/best",
                      f"ytdl://ytsearch{RESULTS}:{q}"],
                     start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(20):  # the socket appears as soon as mpv starts (the search keeps going in mpv)
        if running():
            break
        time.sleep(0.25)
    return f"Playing {q} (sound only, no browser). Say 'next', 'pause' or 'stop the music'."


def pause() -> str | None:
    return "Paused the music." if _send("set_property", "pause", True) else None


def resume() -> str | None:
    return "Playing again." if _send("set_property", "pause", False) else None


def next_track() -> str | None:
    return "Next song." if _send("playlist-next", "force") else None


def prev_track() -> str | None:
    return "Previous song." if _send("playlist-prev", "force") else None


def volume(step: int) -> str | None:
    if _send("add", "volume", step) is None:
        return None
    v = _send("get_property", "volume", want=True)
    return f"Music volume {int(v)}%." if v is not None else "Changed the music volume."


def now_playing() -> str | None:
    title = _send("get_property", "media-title", want=True)
    if title is None:
        return None
    paused = _send("get_property", "pause", want=True)
    return f"{'Paused' if paused else 'Playing'}: {title}."


def stop(quiet: bool = False) -> str | None:
    ok = _send("quit")
    return None if quiet or not ok else "Stopped the music."
