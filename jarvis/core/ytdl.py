"""Video/audio downloader (yt-dlp): YouTube and 1000+ sites, any quality (1080p, 4K...) with sound, or MP3.

Runs yt-dlp (pip, kept current — YouTube breaks old versions) as a detached process, so the voice loop never waits;
a small thread waits for it and announces the result (desktop + Telegram). 0 tokens.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from jarvis.core import config, notify

log = logging.getLogger(__name__)
_URL = re.compile(r"https?://\S+")
_HEIGHTS = {"4k": 2160, "2160p": 2160, "1440p": 1440, "2k": 1440, "1080p": 1080, "full hd": 1080, "fullhd": 1080, "fhd": 1080,
            "hd": 720, "720p": 720, "480p": 480, "360p": 360, "240p": 240, "144p": 144}


def out_dir() -> Path:
    d = Path(config.VIDEO_DIR).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def height_of(quality: str) -> int:
    """'1080p' / '4k' / 'hd' / '720' -> pixel height (0 = best available)."""
    q = (quality or "").lower().strip()
    if q in _HEIGHTS:
        return _HEIGHTS[q]
    m = re.search(r"(\d{3,4})", q)
    return int(m.group(1)) if m else 0


def build_args(source: str, quality: str = "", audio: bool = False, playlist: bool = False) -> list[str]:
    """yt-dlp argv (without the program) for a URL or a search phrase."""
    target = source if _URL.match(source) else f"ytsearch1:{source}"
    tmpl = "%(title).150B [%(height)sp].%(ext)s" if not audio else "%(title).150B.%(ext)s"
    if playlist:
        tmpl = "%(playlist_title).80B/%(playlist_index)03d - " + tmpl
    args = ["--no-mtime", "--restrict-filenames", "-c", "--retries", "5", "--fragment-retries", "5",
            "-o", str(out_dir() / tmpl), "--yes-playlist" if playlist else "--no-playlist"]
    if audio:
        args += ["-f", "ba/b", "-x", "--audio-format", "mp3", "--audio-quality", "0"]
    else:
        h = height_of(quality)
        sel = f"bv*[height<={h}]+ba/b[height<={h}]" if h else "bv*+ba/b"
        args += ["-f", sel, "--merge-output-format", "mp4", "-S", "res,vcodec:h264,acodec:m4a"]
    return args + ["--print", "after_move:filepath", target]


def _js_runtime() -> list[str]:
    """YouTube's HD formats need a JS runtime for its signature challenge (yt-dlp-ejs scripts + deno/node)."""
    for name in ("deno", "node"):
        path = shutil.which(name) or (str(Path.home() / ".deno/bin/deno") if name == "deno" and
                                      (Path.home() / ".deno/bin/deno").exists() else None)
        if path:
            return ["--js-runtimes", f"{name}:{path}"]
    return []


def _ytdlp() -> list[str]:
    return [sys.executable, "-m", "yt_dlp", *_js_runtime()]


def _wait(p: subprocess.Popen, what: str, logf: Path) -> None:
    rc = p.wait()
    files = [ln.strip() for ln in (p.stdout.read() if p.stdout else "").splitlines() if ln.strip().startswith("/")]
    if rc == 0 and files:
        size = sum(Path(f).stat().st_size for f in files if Path(f).exists())
        names = ", ".join(Path(f).name for f in files[:3]) + (f" and {len(files) - 3} more" if len(files) > 3 else "")
        notify.notify(f"Downloaded {what}", f"{names}\n{size / 1e6:.0f} MB in {out_dir()}", level="info",
                      source="downloads", telegram=True)
    else:
        tail = logf.read_text(errors="replace").strip().splitlines()[-3:] if logf.exists() else []
        notify.notify(f"Download failed: {what}", "\n".join(tail)[-500:] or f"yt-dlp exit {rc}", level="warning",
                      source="downloads", telegram=True)


def start(source: str, quality: str = "", audio: bool = False, playlist: bool = False) -> str:
    source = (source or "").strip()
    if not source:
        return "error: give a video link or what to search for"
    if not audio and not shutil.which("ffmpeg"):
        return "error: ffmpeg is needed to join HD video and sound: sudo apt install ffmpeg"
    logf = Path(config.DATA_DIR) / "runs" / f"ytdl-{int(time.time())}.log"
    logf.parent.mkdir(parents=True, exist_ok=True)
    try:
        err = open(logf, "w")
        p = subprocess.Popen([*_ytdlp(), *build_args(source, quality, audio, playlist)], stdout=subprocess.PIPE,
                             stderr=err, stdin=subprocess.DEVNULL, text=True, start_new_session=True)
    except OSError as e:
        return f"error: couldn't start yt-dlp ({e})"
    what = "audio" if audio else (f"{height_of(quality)}p video" if height_of(quality) else "video")
    threading.Thread(target=_wait, args=(p, what, logf), daemon=True).start()
    kind = "playlist" if playlist else what
    return f"Downloading the {kind} in the background into {out_dir()}. I'll tell you when it's done."
