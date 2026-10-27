"""Music without the browser (0 tokens): mpv plays only the sound, ~30 MB instead of a ~300 MB browser tab.

- 'play kya mujhe pyar hai by KK' / 'play lofi music': a fast flat YouTube search (~2 s, cached 12 h) picks real
  songs (no live streams; songs 1-10 min unless a mix/lofi/hour was asked), mpv gets them as a playlist and loads
  the next one while one plays (prefetch), so 'next' is quick.
- a YouTube video/playlist link, 'play this playlist' (the tab open in the browser): played as it is.
- saved playlists: 'save this playlist as study', 'play my study playlist', 'shuffle my study playlist',
  'show my playlists', 'delete the study playlist' (+ config.PLAYLISTS as the starting set).
- 'play my music': the files in ~/Music (offline, instant, shuffled).
Controlled through mpv's IPC socket: pause / resume / next / previous / volume / what's playing / stop.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from jarvis.core import config, store

PICK = 6  # songs queued for a search: 'next' moves through them
SEARCH = 15  # results looked at
CACHE_S = 12 * 3600
LISTS_KEY = "music_playlists"
LONG_OK = re.compile(r"\b(?:mix|mixes|lofi|lo-fi|jukebox|non[\s-]?stop|hour|hours|hrs?|playlist|album|study|sleep|"
                     r"rain|ambient|meditation|white\s+noise|bgm|instrumental|radio|mashup)\b", re.I)
CLIENTS = "youtube:player_client=android_vr,web"  # android_vr reads a song in ~3 s instead of ~6 s; web if it can't
AUDIO_EXT = (".mp3", ".m4a", ".flac", ".ogg", ".opus", ".wav", ".aac", ".webm")


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


# ------------------------------------------------------------------ finding songs
def search(query: str) -> list[dict]:
    """[{url, title, duration}] good songs for the query (flat search: titles only, no stream lookups)."""
    key = "music_search:" + query.lower().strip()
    try:
        hit = json.loads(store.kv_get(key) or "{}")
        if hit and time.time() - hit.get("at", 0) < CACHE_S:
            return hit["items"]
    except ValueError:
        pass
    try:
        out = subprocess.run([_ytdlp(), "--flat-playlist", "-J", "--no-warnings", f"ytsearch{SEARCH}:{query}"],
                             capture_output=True, text=True, timeout=25).stdout
        entries = json.loads(out).get("entries") or []
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    long_ok = bool(LONG_OK.search(query))
    good = []
    for e in entries:
        dur = e.get("duration") or 0
        live = e.get("live_status") in ("is_live", "is_upcoming") or not dur
        if live or not e.get("id"):
            continue  # live streams / premieres often fail or never end
        if not long_ok and not 60 <= dur <= 12 * 60:
            continue  # a song, not a 3-hour compilation
        if long_ok and dur > 5 * 3600:
            continue
        good.append({"url": f"https://www.youtube.com/watch?v={e['id']}", "title": e.get("title") or "", "duration": dur})
    if not good:  # nothing passed the filter: take what there is (still no live)
        good = [{"url": f"https://www.youtube.com/watch?v={e['id']}", "title": e.get("title") or "", "duration": e.get("duration")}
                for e in entries if e.get("id") and e.get("duration")]
    good = good[:PICK]
    if good:
        store.kv_set(key, json.dumps({"at": time.time(), "items": good}))
    return good


# ------------------------------------------------------------------ the player
def _start(targets: list[str], shuffle: bool = False, loop: bool = False) -> bool:
    if not shutil.which("mpv"):
        return False
    stop(quiet=True)
    try:
        os.unlink(_sock())
    except OSError:
        pass
    cmd = ["mpv", "--no-video", "--idle=no", "--force-window=no", "--really-quiet", "--no-terminal",
           f"--input-ipc-server={_sock()}", f"--volume={config.MUSIC_VOLUME}", "--prefetch-playlist=yes",
           f"--script-opts=ytdl_hook-ytdl_path={_ytdlp()}", "--ytdl-format=bestaudio/best",
           f"--ytdl-raw-options=extractor-args=%{len(CLIENTS)}%{CLIENTS}", "--sid=no"]
    if shuffle:
        cmd.append("--shuffle")
    if loop:
        cmd.append("--loop-playlist=inf")
    if _spawn(cmd + ["--", *targets]):
        for _ in range(20):  # the socket appears as soon as mpv starts
            if running():
                break
            time.sleep(0.25)
    return True


def _spawn(cmd: list[str]) -> bool:
    """Start mpv (tests replace this: no real player, no sound)."""
    subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def _key_words(title: str) -> set[str]:
    t = re.sub(r"\(.*?\)|\[.*?\]|\b(?:official|video|audio|lyrics?|lyrical|full|song|hd|4k|remix|cover|live)\b", " ", title.lower())
    return set(re.findall(r"[a-z\u0900-\u097f]{3,}", t))


def _same_song(a: str, b: str) -> bool:
    ka, kb = _key_words(a), _key_words(b)
    return bool(ka and kb) and len(ka & kb) / min(len(ka), len(kb)) >= 0.6


def _distinct(songs: list[dict], skip: list[dict] = ()) -> list[dict]:
    out: list[dict] = []
    for s in songs:
        if not any(_same_song(s["title"], o["title"]) for o in [*skip, *out]):
            out.append(s)
    return out


def _queue_more(query: str, first: list[dict]) -> None:
    """A named song: after it, other songs like it (not 5 versions of the same one), added while it plays."""
    import threading

    def run():
        more = _distinct(search(f"songs like {query}") + search(f"{query} similar songs"), skip=first)[:PICK]
        for s in more:
            _send("loadfile", s["url"], "append")
    threading.Thread(target=run, name="music-more", daemon=True).start()


def play(query: str, shuffle: bool = False) -> str:
    """A song / artist / mood. A saved playlist with that name wins ('play study')."""
    q = (query or "").strip() or "relaxing music"
    if hit := find_playlist(q):
        return play_playlist(hit[0], shuffle)
    if not shutil.which("mpv"):
        return "error: mpv isn't installed (sudo apt install mpv)"
    songs = _distinct(search(q))
    if not songs:
        return f"I couldn't find {q} on YouTube (no internet?)."
    one_song = not re.search(r"\b(?:songs|music|mix|mixes|playlist|lofi|lo-fi|beats|hits|bhajans|ghazals|album|jukebox)\b", q, re.I)
    if one_song:
        songs = songs[:1]  # the song asked for; similar ones are queued after it in the background
    elif shuffle:
        import random
        random.shuffle(songs)
    _start([s["url"] for s in songs])
    if one_song and running():
        _queue_more(q, songs)
    first = songs[0]["title"][:70]
    more = " Similar songs come after it." if one_song else (f" (+{len(songs) - 1} more)" if len(songs) > 1 else "")
    return f"Playing {first}.{more} Say 'next', 'pause' or 'stop the music'."


def play_url(url: str, shuffle: bool = False, label: str = "") -> str:
    if not _start([url], shuffle=shuffle):
        return "error: mpv isn't installed (sudo apt install mpv)"
    what = label or ("this playlist" if "list=" in url else "this")
    return f"Playing {what}{' on shuffle' if shuffle else ''} (sound only). Say 'next', 'pause' or 'stop the music'."


def local_files(folder: str = "") -> list[Path]:
    root = Path(folder).expanduser() if folder else Path.home() / "Music"
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*") if p.suffix.lower() in AUDIO_EXT)[:2000]


def play_local(folder: str = "", shuffle: bool = True) -> str:
    files = local_files(folder)
    if not files:
        where = folder or "~/Music"
        return f"I found no music files in {where}. Put songs there (mp3, m4a, flac...) or say 'play lofi music'."
    _start([str(p) for p in files], shuffle=shuffle, loop=True)
    return f"Playing your {len(files)} songs from {folder or '~/Music'}{' on shuffle' if shuffle else ''}."


# ------------------------------------------------------------------ saved playlists
def playlists() -> dict[str, str]:
    try:
        saved = json.loads(store.kv_get(LISTS_KEY) or "{}")
    except ValueError:
        saved = {}
    return {**{k.lower(): v for k, v in config.PLAYLISTS.items()}, **saved}


def _norm(name: str) -> str:
    n = re.sub(r"\b(?:my|the|playlist|songs?|music)\b", " ", (name or "").lower())
    return " ".join(n.split())


def find_playlist(name: str) -> tuple[str, str] | None:
    key = _norm(name)
    if not key:
        return None
    lists = playlists()
    if key in lists:
        return key, lists[key]
    return None


def save_playlist(name: str, url: str = "") -> str:
    name = _norm(name)
    if not name:
        return "What should I call this playlist? Say 'save this playlist as study'."
    if not url:
        from jarvis.core import links
        found = links.find_link()
        if isinstance(found, str):
            return "Open the YouTube playlist (or song) in your browser, or paste its link, and say it again."
        url = found[0]
    if not re.search(r"youtube\.com|youtu\.be|music\.youtube|soundcloud\.com", url) and not Path(url).expanduser().exists():
        return "That isn't a YouTube link or a music folder."
    lists = {k: v for k, v in playlists().items() if k not in {x.lower() for x in config.PLAYLISTS}}
    lists[name] = url
    store.kv_set(LISTS_KEY, json.dumps(lists))
    return f"Saved your {name} playlist. Say 'play my {name} playlist' (or 'shuffle my {name} playlist')."


def delete_playlist(name: str) -> str:
    key = _norm(name)
    lists = json.loads(store.kv_get(LISTS_KEY) or "{}")
    if key not in lists:
        return f"There's no saved playlist called {key or name}." + (" " + playlists_text() if lists else "")
    del lists[key]
    store.kv_set(LISTS_KEY, json.dumps(lists))
    return f"Deleted the {key} playlist."


def playlists_text() -> str:
    lists = playlists()
    if not lists:
        return "No playlists yet. Open a YouTube playlist and say 'save this playlist as study'."
    return "Your playlists: " + ", ".join(sorted(lists)) + ". Say 'play my <name> playlist'."


def play_playlist(name: str, shuffle: bool = False) -> str:
    hit = find_playlist(name)
    if not hit:
        return f"There's no playlist called {name}. " + playlists_text()
    label, target = hit
    if not target.startswith(("http://", "https://")):
        return play_local(target, shuffle=True)
    return play_url(target, shuffle, f"your {label} playlist")


# ------------------------------------------------------------------ controls
def pause() -> str | None:
    return "Paused the music." if _send("set_property", "pause", True) else None


def resume() -> str | None:
    return "Playing again." if _send("set_property", "pause", False) else None


def _title_soon() -> str:
    for _ in range(12):  # the next song's name arrives once its page is read
        time.sleep(0.25)
        t = _send("get_property", "media-title", want=True)
        if t and not str(t).startswith(("http", "watch?")):
            return f": {t}"
    return ""


def next_track() -> str | None:
    if not _send("playlist-next", "force"):
        return None
    return "Next song" + _title_soon() + "."


def prev_track() -> str | None:
    if not _send("playlist-prev", "force"):
        return None
    return "Previous song" + _title_soon() + "."


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
