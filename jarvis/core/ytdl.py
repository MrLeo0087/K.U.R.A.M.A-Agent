"""Video/audio downloader (yt-dlp): YouTube and 1000+ sites, any quality (1080p, 4K...) with sound, or MP3.

Runs yt-dlp (pip, kept current — YouTube breaks old versions) as a detached process, so the voice loop never waits;
a small thread reads its progress into a watch (kind "ytdl": the UI's download bars) and announces the result
(desktop + Telegram). Plain file links (images, PDFs, zips...) go to the download manager instead. 0 tokens.
Quality: nothing / "best" = 1080p (config.VIDEO_DEFAULT_HEIGHT); "extra high" / "max" = the highest there is.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from jarvis.core import config, notify, store

log = logging.getLogger(__name__)
_URL = re.compile(r"https?://\S+")
_HEIGHTS = {"4k": 2160, "2160p": 2160, "1440p": 1440, "2k": 1440, "1080p": 1080, "full hd": 1080, "fullhd": 1080, "fhd": 1080,
            "hd": 720, "720p": 720, "480p": 480, "360p": 360, "240p": 240, "144p": 144}
_MAX = re.compile(r"\b(extra|ultra|highest|max(imum)?|best available|original|top)\b", re.I)
_FILE_EXT = re.compile(r"\.(jpe?g|png|gif|webp|bmp|svg|pdf|zip|rar|7z|tar|gz|tgz|xz|iso|exe|deb|apk|docx?|xlsx?|"
                       r"pptx?|csv|json|txt|epub|mp3|wav|flac|m4a|mp4|mkv|webm|avi|mov)$", re.I)
_VIDEO_SITES = re.compile(r"youtube\.com|youtu\.be|vimeo\.com|facebook\.com|fb\.watch|instagram\.com|tiktok\.com|"
                          r"x\.com|twitter\.com|dailymotion\.com|reddit\.com|twitch\.tv|soundcloud\.com", re.I)
# one line per progress tick (merged with stderr in one pipe); the title is last because it has spaces
_TPL = ("download:KP %(progress.downloaded_bytes)s %(progress.total_bytes)s %(progress.total_bytes_estimate)s "
        "%(progress.speed)s %(progress.eta)s %(info.vcodec)s %(info.title)s")


def out_dir() -> Path:
    d = Path(config.VIDEO_DIR).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def height_of(quality: str) -> int:
    """'1080p' / '4k' / 'hd' / '720' -> pixel height; '' / 'best' -> 1080; 'extra high' / 'max' -> 0 (highest there is)."""
    q = (quality or "").lower().strip()
    if q in _HEIGHTS:
        return _HEIGHTS[q]
    if m := re.search(r"(\d{3,4})", q):
        return int(m.group(1))
    if _MAX.search(q):
        return 0
    return config.VIDEO_DEFAULT_HEIGHT


def split_source(source: str, quality: str = "") -> tuple[str, str]:
    """'<link> 1080p audio' (the AI sometimes packs words next to the link) -> (link, quality)."""
    m = _URL.search(source or "")
    if not m:
        return (source or "").strip(), quality
    rest = (source[:m.start()] + " " + source[m.end():]).strip()
    return m.group(0), quality or rest


def is_plain_file(url: str) -> bool:
    """A direct file (picture, PDF, zip...) rather than a video page: by its extension, else by its content type."""
    if _VIDEO_SITES.search(url):
        return False
    if _FILE_EXT.search(url.split("?")[0]):
        return True
    try:
        import httpx
        r = httpx.head(url, follow_redirects=True, timeout=5)
        ctype = r.headers.get("content-type", "").lower()
        return bool(ctype) and not ctype.startswith("text/html")
    except Exception:  # noqa: BLE001 - offline or a site that refuses HEAD: let yt-dlp try
        return False


def build_args(source: str, quality: str = "", audio: bool = False, playlist: bool = False) -> list[str]:
    """yt-dlp argv (without the program) for a URL or a search phrase."""
    target = source if _URL.match(source) else f"ytsearch1:{source}"
    tmpl = "%(title).150B [%(height)sp].%(ext)s" if not audio else "%(title).150B.%(ext)s"
    if playlist:
        tmpl = "%(playlist_title).80B/%(playlist_index)03d - " + tmpl
    args = ["--no-mtime", "--restrict-filenames", "-c", "--retries", "5", "--fragment-retries", "5",
            "-o", str(out_dir() / tmpl), "--yes-playlist" if playlist else "--no-playlist",
            "--progress", "--newline", "--progress-template", _TPL,
            # YouTube slows each connection to ~0.3 MB/s: fetch it as pieces over several connections at once
            "-N", str(config.VIDEO_CONNECTIONS), "--extractor-args", "youtube:formats=dashy"]
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


def _num(s: str) -> float:
    try:
        return float(s)
    except ValueError:  # "NA"
        return 0.0


def parse_progress(line: str, st: dict) -> bool:
    """Fold one 'KP ...' line into the watch state (parts: video, then sound). False = not a progress line."""
    parts = line.split(" ", 7)
    if len(parts) < 7 or parts[0] != "KP":
        return False
    done, total, est, speed, eta = (_num(x) for x in parts[1:6])
    total = total or est
    part = "sound" if parts[6] == "none" else "video"
    if part != st.get("part") or done < st.get("cur", 0) * 0.5:  # a new part started: bank the last one
        st["before"] = st.get("before", 0) + st.get("cur_total", 0)
    st.update(part=part, cur=done, cur_total=total, speed=speed, eta=eta,
              done=st.get("before", 0) + done, total=st.get("before", 0) + total)
    if len(parts) > 7 and parts[7] != "NA":
        st["title"] = parts[7][:120]
    return True


def friendly_error(log_text: str) -> str:
    """The last yt-dlp ERROR line in plain words (no FAQ links)."""
    errs = [ln for ln in log_text.splitlines() if ln.startswith("ERROR")] or log_text.strip().splitlines()[-1:] or [""]
    e = errs[-1]
    if "not a bot" in e or "Sign in to confirm" in e:
        return ("YouTube wants a signed-in browser: open youtube.com in "
                f"{config.VIDEO_COOKIES_BROWSER or 'your browser'} once (signed in), then ask again.")
    if "Private video" in e or "members-only" in e.lower():
        return "That video is private or members-only."
    if "Unsupported URL" in e:
        return "That site isn't supported for video download."
    e = re.sub(r"https?://\S+", "", e.replace("ERROR:", "")).strip()
    return re.sub(r"\s+", " ", e)[:200] or "yt-dlp stopped"


def _cookie_retry(logf: Path, argv: list[str]) -> bool:
    """YouTube's 'confirm you're not a bot': try once more with the owner's browser cookies (read locally by yt-dlp)."""
    text = logf.read_text(errors="replace") if logf.exists() else ""
    return bool(config.VIDEO_COOKIES_BROWSER) and "--cookies-from-browser" not in argv and \
        ("not a bot" in text or "Sign in to confirm" in text)


def _follow(p: subprocess.Popen, wid: int, st: dict, what: str, logf: Path, argv: list[str] | None = None) -> None:
    files, last = [], 0.0
    with open(logf, "w") as lf:
        for line in p.stdout or ():
            line = line.strip()
            if parse_progress(line, st):
                if time.time() - last >= 1.5:  # the UI polls every 2 s; no need to write more often
                    last = time.time()
                    st["updated"] = last
                    store.watch_update(wid, state=st)
                continue
            if line.startswith("/"):
                files.append(line)
            elif line:
                lf.write(line + "\n")
    rc = p.wait()
    if rc != 0 and argv and _cookie_retry(logf, argv):
        argv = [*argv[:-1], "--cookies-from-browser", config.VIDEO_COOKIES_BROWSER, argv[-1]]
        try:
            p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                 text=True, start_new_session=True)
        except OSError:
            pass
        else:
            st.update(pid=p.pid, updated=time.time())
            store.watch_update(wid, state=st)
            return _follow(p, wid, st, what, logf, argv)
    if rc == 0 and files:
        size = sum(Path(f).stat().st_size for f in files if Path(f).exists())
        names = ", ".join(Path(f).name for f in files[:3]) + (f" and {len(files) - 3} more" if len(files) > 3 else "")
        st.update(file=files[0], done=size, total=size, eta=0, speed=0, updated=time.time())
        store.watch_update(wid, status="done", finished=time.time(), result=f"{size / 1e6:.0f} MB", state=st)
        notify.notify(f"Downloaded {what}", f"{names}\n{size / 1e6:.0f} MB in {out_dir()}", level="info",
                      source="downloads", telegram=True)
    else:
        err = friendly_error(logf.read_text(errors="replace")) if logf.exists() else f"yt-dlp exit {rc}"
        st["updated"] = time.time()
        store.watch_update(wid, status="failed", finished=time.time(), result=err[-200:], state=st)
        notify.notify(f"Download failed: {what}", err, level="warning", source="downloads", telegram=True)


def _running(url: str) -> dict | None:
    return next((w for w in store.watches_list(("active",)) if w["kind"] == "ytdl" and w["target"] == url), None)


def progress_text(st: dict) -> str:
    """'video 45% · 120/260 MB · 3.2 MB/s · 40 s left' (what the bars and 'download status' say)."""
    total, done = st.get("total") or 0, st.get("done") or 0
    bits = [f"{st.get('part', 'video')} {done / total:.0%}" if total else "starting"]
    if total:
        bits.append(f"{done / 1e6:.0f}/{total / 1e6:.0f} MB")
    if st.get("speed"):
        bits.append(f"{st['speed'] / 1e6:.1f} MB/s")
    if st.get("eta"):
        bits.append(f"{int(st['eta'])} s left" if st["eta"] < 120 else f"{int(st['eta'] / 60)} min left")
    return " · ".join(bits)


def start(source: str, quality: str = "", audio: bool = False, playlist: bool = False) -> str:
    source, quality = split_source(source, quality)
    if not source:
        return "error: give a video link or what to search for"
    if _URL.match(source) and not playlist and is_plain_file(source):
        from jarvis.core import automation
        return automation.queue(source)
    if w := _running(source):
        return f"Already downloading that: {progress_text(w['state'])}."
    if not audio and not shutil.which("ffmpeg"):
        return "error: ffmpeg is needed to join HD video and sound: sudo apt install ffmpeg"
    logf = Path(config.DATA_DIR) / "runs" / f"ytdl-{int(time.time())}.log"
    logf.parent.mkdir(parents=True, exist_ok=True)
    argv = [*_ytdlp(), *build_args(source, quality, audio, playlist)]
    try:
        p = subprocess.Popen(argv, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, start_new_session=True)
    except OSError as e:
        return f"error: couldn't start yt-dlp ({e})"
    h = height_of(quality)
    what = "audio" if audio else (f"{h}p video" if h else "video (highest quality)")
    st = {"pid": p.pid, "what": what, "part": "audio" if audio else "video", "started": time.time(),
          "updated": time.time(), "pgid": os.getpgid(p.pid)}
    wid = store.watch_add("ytdl", source, source[:80], "", st)
    threading.Thread(target=_follow, args=(p, wid, st, what, logf, argv), daemon=True).start()
    kind = "playlist" if playlist else what
    return f"Downloading the {kind} in the background into {out_dir()}; the progress bar shows how it's going."
