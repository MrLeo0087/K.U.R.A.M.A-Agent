"""Video/audio downloader (yt-dlp): YouTube and 1000+ sites, any quality (1080p, 4K...) with sound, or MP3.

Runs yt-dlp (pip, kept current — YouTube breaks old versions) as a detached process, so the voice loop never waits;
a small thread reads its progress into a watch (kind "ytdl": the UI's download bars) and announces the result
(desktop + Telegram). Plain file links (images, PDFs, zips...) go to the download manager instead. 0 tokens.
Quality: nothing / "best" = 1080p (config.VIDEO_DEFAULT_HEIGHT); "extra high" / "max" = the highest there is.
"""
from __future__ import annotations

import contextlib
import logging
import os
import re
import shutil
import signal
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
# one tab-separated line per progress tick (merged with stderr in one pipe)
_TPL = ("download:KP\t%(progress.downloaded_bytes)s\t%(progress.total_bytes)s\t%(progress.total_bytes_estimate)s\t"
        "%(progress.speed)s\t%(progress.eta)s\t%(info.vcodec)s\t%(progress.tmpfilename)s\t%(info.title)s")


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
    parts = line.split("\t", 8)
    if len(parts) < 7 or parts[0] != "KP":
        return False
    done, total, est, speed, eta = (_num(x) for x in parts[1:6])
    total = total or est
    part = "sound" if parts[6] == "none" else "video"
    if part != st.get("part") or done < st.get("cur", 0) * 0.5:  # a new part started: bank the last one
        st["before"] = st.get("before", 0) + st.get("cur_total", 0)
    st.update(part=part, cur=done, cur_total=total, speed=speed, eta=eta,
              done=st.get("before", 0) + done, total=st.get("before", 0) + total)
    if len(parts) > 7 and parts[7] not in ("NA", ""):
        st["tmp"] = parts[7]
    if len(parts) > 8 and parts[8] != "NA":
        st["title"] = parts[8][:120]
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
    now = store.watch_get(wid)
    if now and now["status"] != "active":  # paused or deleted from the download bars: not a failure
        return
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


def _running(url: str, statuses: tuple[str, ...] = ("active",)) -> dict | None:
    return next((w for w in store.watches_list(statuses) if w["kind"] == "ytdl" and w["target"] == url), None)


def _launch(wid: int, st: dict, argv: list[str]) -> str:
    logf = Path(config.DATA_DIR) / "runs" / f"ytdl-{int(time.time())}.log"
    logf.parent.mkdir(parents=True, exist_ok=True)
    try:
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             text=True, start_new_session=True)
    except OSError as e:
        return f"error: couldn't start yt-dlp ({e})"
    st.update(pid=p.pid, pgid=os.getpgid(p.pid), updated=time.time(), argv=argv, before=0, cur=0, cur_total=0)
    st.pop("part", None)
    store.watch_update(wid, status="active", state=st)
    threading.Thread(target=_follow, args=(p, wid, st, st.get("what", "video"), logf, argv), daemon=True).start()
    return ""


def _stop(st: dict) -> None:
    with contextlib.suppress(OSError, ProcessLookupError):
        os.killpg(int(st.get("pgid") or st.get("pid") or 0), signal.SIGTERM)


def partial_files(st: dict) -> list[Path]:
    """yt-dlp's leftovers of one download (.part, .ytdl, fragments, the separate video / sound tracks)."""
    tmp = Path(st.get("tmp") or "")
    if not tmp.name:
        return []
    stem = re.split(r"\.f[\w-]+\.\w+(?:\.part)?$|\.\w+\.part$|\.part$", tmp.name)[0]
    return [f for f in tmp.parent.glob(glob_escape(stem) + ".*")
            if re.search(r"\.part|\.ytdl$|\.f[\w-]+\.\w+$|\.temp\.", f.name)]


def glob_escape(s: str) -> str:
    return re.sub(r"([\[\]*?])", r"[\1]", s)


def control(wid: int, action: str) -> str:
    """The download bars' buttons: pause / resume a download, or delete it — a running or paused one also loses
    its partial files; a finished one only leaves the list (the video stays)."""
    w = store.watch_get(wid)
    if not w or w["kind"] != "ytdl":
        return "error: no such download"
    st = w["state"]
    if action == "pause" and w["status"] == "active":
        store.watch_update(wid, status="paused", state=st)
        _stop(st)
        return "Paused."
    if action == "resume" and w["status"] in ("paused", "failed", "stopped"):
        return _launch(wid, st, st.get("argv") or [*_ytdlp(), *build_args(w["target"])]) or "Resumed."
    if action == "delete":
        unfinished = w["status"] in ("active", "paused", "failed", "stopped")
        store.watch_update(wid, status="removed", finished=time.time(), state=st)
        if unfinished:
            _stop(st)
            time.sleep(0.5)  # let yt-dlp let go of its files
            for f in partial_files(st):
                with contextlib.suppress(OSError):
                    f.unlink()
        return "Deleted the download and its partial files." if unfinished else "Removed from the list."
    return f"error: can't {action} a download that is {w['status']}"


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


_MEDIA = {".mp4", ".mkv", ".webm", ".mp3", ".m4a", ".opus", ".mov"}


def library() -> list[dict]:
    """Every finished video/audio in the downloads folder (playlists' subfolders too), newest first."""
    from datetime import date, datetime
    root, out = out_dir(), []
    for f in root.rglob("*"):
        if f.suffix.lower() not in _MEDIA or not f.is_file() or re.search(r"\.f[\w-]+\.\w+$", f.name):
            continue  # .part / separate video-only and sound-only tracks are not finished downloads
        st = f.stat()
        d = datetime.fromtimestamp(st.st_mtime).date()
        day = "Today" if d == date.today() else "Yesterday" if (date.today() - d).days == 1 else d.strftime("%d %b %Y")
        out.append({"name": str(f.relative_to(root)), "size": st.st_size, "mtime": st.st_mtime, "day": day})
    return sorted(out, key=lambda x: x["mtime"], reverse=True)


def remove(names: list[str] | None = None) -> str:
    """Move downloaded videos to the Trash (names relative to the downloads folder; None = all of them)."""
    root = out_dir().resolve()
    targets = [root / x["name"] for x in library()] if names is None else [(root / n).resolve() for n in names]
    done = 0
    for f in targets:
        if root not in f.parents or not f.is_file():  # never outside the downloads folder
            continue
        try:
            subprocess.run(["gio", "trash", str(f)], check=True, capture_output=True, timeout=30)
            done += 1
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("couldn't trash %s: %s", f, e)
    return f"Moved {done} video{'s' if done != 1 else ''} to the Trash."


def start(source: str, quality: str = "", audio: bool = False, playlist: bool = False) -> str:
    source, quality = split_source(source, quality)
    if not source:
        return "error: give a video link or what to search for"
    if _URL.match(source) and not playlist and is_plain_file(source):
        from jarvis.core import automation
        return automation.queue(source)
    if w := _running(source):
        return f"Already downloading that: {progress_text(w['state'])}."
    if w := _running(source, ("paused",)):
        return _launch(w["id"], w["state"], w["state"].get("argv") or [*_ytdlp(), *build_args(source)]) or \
            "Resuming that download where it stopped."
    if not audio and not shutil.which("ffmpeg"):
        return "error: ffmpeg is needed to join HD video and sound: sudo apt install ffmpeg"
    h = height_of(quality)
    what = "audio" if audio else (f"{h}p video" if h else "video (highest quality)")
    st = {"what": what, "started": time.time()}
    wid = store.watch_add("ytdl", source, source[:80], "", st)
    if err := _launch(wid, st, [*_ytdlp(), *build_args(source, quality, audio, playlist)]):
        store.watch_update(wid, status="failed", finished=time.time(), result=err)
        return err
    kind = "playlist" if playlist else what
    return f"Downloading the {kind} in the background into {out_dir()}; the progress bar shows how it's going."
