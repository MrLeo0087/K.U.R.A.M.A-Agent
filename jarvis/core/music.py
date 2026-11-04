"""Music without the browser (0 tokens): only the sound, ~30-60 MB instead of a ~300 MB browser tab.

YouTube refuses (403) when a player fetches a song's stream itself, so yt-dlp's own downloader feeds mpv:
`yt-dlp -o - <song> | mpv -` for the song now, while the NEXT song is downloaded to a small cache in the background,
so 'next' starts at once. KURAMA keeps the queue: a song ends -> the next one starts; next / previous / stop.

- 'play kya mujhe pyar hai by KK': that song, then similar songs (found in the background).
- 'play lofi music': a flat YouTube search (~2.5 s, cached 12 h): real songs, no live streams, no duplicates.
- a YouTube video/playlist link, 'play this playlist' (the open tab), saved playlists ('save this playlist as study',
  'play / shuffle my study playlist', 'show my playlists', 'delete ...'), 'play my music' (~/Music, offline).
- Local files and non-YouTube streams go straight to mpv.
Controls: pause / resume / volume / what's playing go to the running mpv over its IPC socket.
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from jarvis.core import config, store

log = logging.getLogger(__name__)
PICK = 6  # songs queued for a search
SEARCH = 15  # results looked at
CACHE_S = 12 * 3600
LISTS_KEY = "music_playlists"
PREFETCH_MAX_S = 15 * 60  # longer items (mixes) are streamed, never downloaded ahead
CACHE_KEEP = 12  # downloaded songs kept in ~/.cache/kurama-music
LONG_OK = re.compile(r"\b(?:mix|mixes|lofi|lo-fi|jukebox|non[\s-]?stop|hour|hours|hrs?|playlist|album|study|sleep|"
                     r"rain|ambient|meditation|white\s+noise|bgm|instrumental|radio|mashup)\b", re.I)
AUDIO_EXT = (".mp3", ".m4a", ".flac", ".ogg", ".opus", ".wav", ".aac", ".webm")


def _sock() -> str:
    return str(Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "kurama-music.sock")


def _cache_dir() -> Path:
    d = Path(os.environ.get("KURAMA_MUSIC_CACHE") or Path.home() / ".cache" / "kurama-music")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _env(js: bool = False) -> dict:
    """yt-dlp without its JavaScript runtime starts a song in ~2.5 s instead of ~8.5 s (YouTube still serves the
    audio); js=True is the fallback for the few songs that need it."""
    env = dict(os.environ)
    if not js:
        env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep) if ".deno" not in p)
    return env


def _ytdlp() -> str:
    exe = Path(sys.executable).with_name("yt-dlp")
    return str(exe) if exe.exists() else (shutil.which("yt-dlp") or "yt-dlp")


def _send(*command, want: bool = False):
    """One IPC command to the playing mpv; the reply's data when want=True. None when nothing plays."""
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


# ------------------------------------------------------------------ finding songs
def search(query: str) -> list[dict]:
    """[{url, id, title, duration}] good songs for the query (flat search: titles only, no stream lookups)."""
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
    def pick(long_ok: bool) -> list[dict]:
        good = []
        for e in entries:
            dur = e.get("duration") or 0
            if e.get("live_status") in ("is_live", "is_upcoming") or not dur or not e.get("id"):
                continue  # live streams / premieres
            if not long_ok and not 60 <= dur <= 12 * 60:
                continue  # a song, not a 3-hour compilation
            if long_ok and dur > 5 * 3600:
                continue
            good.append({"url": f"https://www.youtube.com/watch?v={e['id']}", "id": e["id"],
                         "title": e.get("title") or "", "duration": dur})
        return good
    # a mood ("relaxing music", "lofi for study") finds only long mixes: then a mix it is, not "couldn't find" (11-01)
    good = pick(bool(LONG_OK.search(query))) or pick(True)
    good = _distinct(good)[:PICK]
    if good:
        store.kv_set(key, json.dumps({"at": time.time(), "items": good}))
    return good


def expand(url: str) -> list[dict]:
    """The songs of a YouTube playlist link (a single video -> itself)."""
    if "list=" not in url:
        return [{"url": url, "id": _vid(url), "title": "", "duration": 0}]
    try:
        out = subprocess.run([_ytdlp(), "--flat-playlist", "-J", "--no-warnings", url], capture_output=True, text=True,
                             timeout=40).stdout
        entries = json.loads(out).get("entries") or []
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    return [{"url": f"https://www.youtube.com/watch?v={e['id']}", "id": e["id"], "title": e.get("title") or "",
             "duration": e.get("duration") or 0} for e in entries if e.get("id")][:200]


def _vid(url: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{6,})", url)
    return m.group(1) if m else re.sub(r"\W+", "", url)[-16:]


def _key_words(title: str) -> set[str]:
    t = re.sub(r"\(.*?\)|\[.*?\]|\b(?:official|video|audio|lyrics?|lyrical|full|song|hd|4k|remix|cover|live)\b", " ", title.lower())
    return set(re.findall(r"[a-zऀ-ॿ]{3,}", t))


def _same_song(a: str, b: str) -> bool:
    ka, kb = _key_words(a), _key_words(b)
    return bool(ka and kb) and len(ka & kb) / min(len(ka), len(kb)) >= 0.6


def _distinct(songs: list[dict], skip: list[dict] = ()) -> list[dict]:
    out: list[dict] = []
    for s in songs:
        if not any(_same_song(s["title"], o["title"]) for o in [*skip, *out]):
            out.append(s)
    return out


# ------------------------------------------------------------------ the player
class Player:
    """One song at a time: mpv fed by yt-dlp (or a downloaded file / a direct source); KURAMA keeps the queue."""

    def __init__(self) -> None:
        self.queue: list[dict] = []
        self.i = 0
        self.procs: list[subprocess.Popen] = []
        self.gen = 0  # bumps on every start/stop: an old watcher thread then does nothing
        self.lock = threading.RLock()
        self._volume: int | None = None  # the user's music volume, read from kv on first use (not at import)
        self.fetching: set[str] = set()

    @property
    def volume(self) -> int:
        if self._volume is None:
            try:
                self._volume = int(store.kv_get(VOLUME_KEY) or config.MUSIC_VOLUME)
            except (ValueError, TypeError):
                self._volume = config.MUSIC_VOLUME
        return self._volume

    @volume.setter
    def volume(self, v: int) -> None:
        self._volume = int(v)

    def alive(self) -> bool:
        return bool(self.procs) and self.procs[-1].poll() is None

    def _kill(self) -> None:
        for p in self.procs:
            try:
                p.kill()
            except OSError:
                pass
        for p in self.procs:
            try:
                p.wait(timeout=2)
            except (OSError, subprocess.SubprocessError):
                pass
        self.procs = []

    def start(self, items: list[dict], at: int = 0) -> bool:
        with self.lock:
            self.gen += 1
            self._kill()
            self.queue, self.i = list(items), at
            return self._play()

    def _mpv(self, title: str, src: list[str], extra: tuple = ()) -> list[str]:
        return ["mpv", "--no-video", "--idle=no", "--force-window=no", "--really-quiet", "--no-terminal", "--cache=yes",
                "--cache-secs=30", "--audio-buffer=0.4",
                f"--input-ipc-server={_sock()}", f"--volume={min(DUCK_VOLUME, self.volume) if _duck['on'] else self.volume}", f"--force-media-title={title or 'music'}",
                *([f"--ao={os.environ['KURAMA_MUSIC_AO']}"] if os.environ.get("KURAMA_MUSIC_AO") else []),  # null = silent check
                *extra, "--", *src]

    def _play(self) -> bool:
        if not 0 <= self.i < len(self.queue):
            self.queue = []
            return False
        self.gen += 1
        gen, item = self.gen, self.queue[self.i]
        try:
            os.unlink(_sock())
        except OSError:
            pass
        cached = _cached(item)
        tries = item.get("try", 0)
        if item.get("direct") or cached:  # local files, other streams, a song already downloaded
            src = [str(cached)] if cached else item["src"]
            procs = launch([self._mpv(item.get("title", ""), src, tuple(item.get("mpv", ())))])
        elif tries < 2:  # stream it now through yt-dlp (1st try fast without its JS runtime, 2nd with it)
            procs = launch([[_ytdlp(), "-q", "--no-warnings", "-f", "bestaudio/best", "-o", "-", item["url"]],
                            self._mpv(item.get("title", ""), ["-"])], pipe=True, env=_env(tries == 1))
        else:  # live streams: mpv's own YouTube reader (HLS) plays those
            procs = launch([self._mpv(item.get("title", ""), [item["url"]],
                                      (f"--script-opts=ytdl_hook-ytdl_path={_ytdlp()}", "--ytdl-format=bestaudio/best"))])
        self.procs = procs
        if procs:
            threading.Thread(target=self._watch, args=(gen, procs[-1], time.time()), name="music-watch", daemon=True).start()
            threading.Thread(target=self._settle_volume, args=(gen,), name="music-vol", daemon=True).start()
            self._prefetch()
        return bool(procs)

    def _settle_volume(self, gen: int) -> None:
        """Once this mpv answers, give it the volume of NOW: it may have started while ducked and the un-duck came
        before its socket existed (that song then stayed at DUCK_VOLUME to the end)."""
        for _ in range(VOLUME_SETTLE_TRIES):
            if gen != self.gen:
                return
            if _send("set_property", "volume", min(DUCK_VOLUME, self.volume) if _duck["on"] else self.volume):
                return
            time.sleep(0.5)

    def _watch(self, gen: int, p: subprocess.Popen, started: float) -> None:
        """The song ended by itself -> the next one (not after next / stop: the generation changed).
        A streamed song that died at once gets one more try with yt-dlp's JavaScript runtime."""
        p.wait()
        with self.lock:
            if gen != self.gen:
                return
            self._kill()
            item = self.current() or {}
            if time.time() - started < 8 and item.get("try", 0) < 2 and not item.get("direct") and not _cached(item):
                item["try"] = item.get("try", 0) + 1  # it died at once: try the next way to play it
                self._play()
                return
            if self.i + 1 < len(self.queue):
                self.i += 1
                self._play()
            else:
                self.queue = []

    def _prefetch(self) -> None:
        """Download the next song while this one plays, so 'next' starts at once."""
        nxt = self.queue[self.i + 1] if self.i + 1 < len(self.queue) else None
        if not nxt or nxt.get("direct") or _cached(nxt) or (nxt.get("duration") or 0) > PREFETCH_MAX_S:
            return
        vid = nxt.get("id") or _vid(nxt["url"])
        if vid in self.fetching:
            return
        self.fetching.add(vid)

        def run():
            try:
                download(nxt["url"], vid)
            finally:
                self.fetching.discard(vid)
        threading.Thread(target=run, name="music-prefetch", daemon=True).start()

    def skip(self, step: int) -> bool:
        with self.lock:
            j = self.i + step
            if not self.queue or not 0 <= j < len(self.queue):
                return False
            self.gen += 1
            self._kill()
            self.i = j
            return self._play()

    def stop(self) -> bool:
        with self.lock:
            was = self.alive()
            self.gen += 1
            self._kill()
            self.queue = []
            return was

    def current(self) -> dict | None:
        return self.queue[self.i] if self.queue and 0 <= self.i < len(self.queue) else None


def launch(cmds: list[list[str]], pipe: bool = False, env: dict | None = None) -> list[subprocess.Popen]:
    """Start the player process(es); with pipe=True the first one's output feeds the second (tests replace this)."""
    if not shutil.which("mpv"):
        return []
    if not pipe:
        return [subprocess.Popen(cmds[0], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
    feed = subprocess.Popen(cmds[0], start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
    player = subprocess.Popen(cmds[1], start_new_session=True, stdin=feed.stdout, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
    feed.stdout.close()  # mpv owns the pipe now: when it quits, yt-dlp stops too
    return [feed, player]


def _cached(item: dict) -> Path | None:
    vid = item.get("id") or (_vid(item["url"]) if item.get("url") else "")
    if not vid:
        return None
    hits = [p for p in _cache_dir().glob(f"{vid}.*") if p.suffix in AUDIO_EXT and p.stat().st_size > 10_000]
    return hits[0] if hits else None


def download(url: str, vid: str) -> Path | None:
    """yt-dlp -> ~/.cache/kurama-music/<id>.<ext> (yt-dlp writes .part until the file is complete)."""
    for js in (False, True):  # fast way first, the JavaScript runtime only if needed
        try:
            subprocess.run([_ytdlp(), "-q", "--no-warnings", "-f", "bestaudio/best", "-o",
                            str(_cache_dir() / f"{vid}.%(ext)s"), url], capture_output=True, timeout=300, env=_env(js))
        except (OSError, subprocess.SubprocessError):
            return None
        if _cached({"id": vid}):
            break
    files = sorted((p for p in _cache_dir().iterdir() if p.suffix in AUDIO_EXT), key=lambda p: p.stat().st_mtime)
    for old in files[:-CACHE_KEEP]:  # keep the cache small
        try:
            old.unlink()
        except OSError:
            pass
    return _cached({"id": vid})


PLAYER = Player()


def running() -> bool:
    return PLAYER.alive()


# ------------------------------------------------------------------ what to play
def _queue_more(query: str, first: list[dict]) -> None:
    """A named song: after it, other songs like it (not 5 versions of the same one), added while it plays."""
    def run():
        asked = _key_words(query)
        found = [s for s in search(f"songs like {query}") + search(f"{query} similar songs")
                 if not asked or len(_key_words(s["title"]) & asked) / len(asked) < 0.7]  # not the same song again
        more = _distinct(found, skip=first)[:PICK]
        with PLAYER.lock:
            if PLAYER.queue and PLAYER.queue[0].get("url") == first[0].get("url"):  # still the same request
                PLAYER.queue.extend(more)
                PLAYER._prefetch()
    threading.Thread(target=run, name="music-more", daemon=True).start()


def _ok() -> str | None:
    return None if shutil.which("mpv") else "error: mpv isn't installed (sudo apt install mpv)"


def play(query: str, shuffle: bool = False) -> str:
    """A song / artist / mood. A saved playlist with that name wins ('play study')."""
    q = (query or "").strip() or "relaxing music"
    if re.match(r"https?://", q):  # a link: play it (searching YouTube for a link's text finds nothing)
        return play_url(q, shuffle)
    if hit := find_playlist(q):
        return play_playlist(hit[0], shuffle)
    if err := _ok():
        return err
    songs = search(q)
    if not songs:
        return f"I couldn't find {q} on YouTube (no internet?)."
    one_song = not re.search(r"\b(?:songs|music|mix|mixes|playlist|lofi|lo-fi|beats|hits|bhajans|ghazals|album|jukebox)\b", q, re.I)
    if one_song:
        songs = songs[:1]  # the song asked for; similar ones are queued after it in the background
    elif shuffle:
        random.shuffle(songs)
    PLAYER.start(songs)
    if one_song:
        _queue_more(q, songs)
    first = songs[0]["title"][:70]
    wait = "" if _cached(songs[0]) else " It starts in a few seconds."
    more = " Similar songs come after it." if one_song else (f" (+{len(songs) - 1} more)" if len(songs) > 1 else "")
    return f"Playing {first}.{more}{wait} Say 'next', 'pause' or 'stop the music'."


def play_url(url: str, shuffle: bool = False, label: str = "") -> str:
    if err := _ok():
        return err
    what = label or ("this playlist" if "list=" in url else "this")
    if re.search(r"youtube\.com|youtu\.be", url):
        if re.search(r"[?&]list=RD", url) and (v := re.search(r"[?&]v=([\w-]{6,})", url)):
            url = f"https://www.youtube.com/watch?v={v.group(1)}"  # a "radio" mix: the song itself, similar ones follow
            what = label or "this song"
        items = expand(url)
        if not items:
            return "I couldn't read that playlist (private, or no internet?)."
        if shuffle:
            random.shuffle(items)
        PLAYER.start(items)
        n = f" ({len(items)} songs)" if len(items) > 1 else ""
        return f"Playing {what}{n}{' on shuffle' if shuffle else ''}. It starts in a few seconds. Say 'next', 'pause' or 'stop the music'."
    PLAYER.start([{"direct": True, "src": [url], "title": label or url}])  # a radio stream or other link: mpv itself
    return f"Playing {what}. Say 'pause' or 'stop the music'."


def local_files(folder: str = "") -> list[Path]:
    root = Path(folder).expanduser() if folder else Path.home() / "Music"
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*") if p.suffix.lower() in AUDIO_EXT)[:2000]


def play_local(folder: str = "", shuffle: bool = True) -> str:
    if err := _ok():
        return err
    files = local_files(folder)
    if not files:
        where = folder or "~/Music"
        return f"I found no music files in {where}. Put songs there (mp3, m4a, flac...) or say 'play lofi music'."
    if shuffle:
        random.shuffle(files)
    PLAYER.start([{"direct": True, "src": [str(p)], "title": p.stem} for p in files])
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
    return (key, lists[key]) if key in lists else None


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
    try:
        lists = json.loads(store.kv_get(LISTS_KEY) or "{}")
    except ValueError:
        lists = {}
    lists[name] = url
    store.kv_set(LISTS_KEY, json.dumps(lists))
    return f"Saved your {name} playlist. Say 'play my {name} playlist' (or 'shuffle my {name} playlist')."


def delete_playlist(name: str) -> str:
    key = _norm(name)
    try:
        lists = json.loads(store.kv_get(LISTS_KEY) or "{}")
    except ValueError:
        lists = {}
    if key not in lists:
        return f"There's no saved playlist called {key or name}. " + playlists_text()
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
    return "Paused the music." if running() and _send("set_property", "pause", True) else None


def resume() -> str | None:
    return "Playing again." if running() and _send("set_property", "pause", False) else None


def next_track() -> str | None:
    if not PLAYER.queue:
        return None
    if not PLAYER.skip(1):
        return "That was the last song. Say 'play <something>' for more."
    cur = PLAYER.current() or {}
    return f"Next song: {cur.get('title') or 'loading'}."


def prev_track() -> str | None:
    if not PLAYER.queue:
        return None
    if not PLAYER.skip(-1):
        return "This is the first song."
    cur = PLAYER.current() or {}
    return f"Previous song: {cur.get('title') or 'loading'}."


def volume(step: int = 0, to: int | None = None) -> str | None:
    """Music volume (mpv, 0-130): up / down by step or to a level. The laptop's own volume is not touched."""
    if not running():
        return None
    new = to if to is not None else PLAYER.volume + step
    new = max(0, min(130, int(new)))
    if new == PLAYER.volume and step:
        return f"The music is already at {'its loudest' if step > 0 else 'its quietest'} ({new}%)."
    PLAYER.volume = new
    store.kv_set(VOLUME_KEY, str(new))  # the next song (and the next day) starts at it
    if not _duck["on"]:
        _send("set_property", "volume", new)
    return f"Music volume {new}%."


def now_playing() -> str | None:
    cur = PLAYER.current()
    if not cur or not running():
        return None
    paused = _send("get_property", "pause", want=True)
    left = len(PLAYER.queue) - PLAYER.i - 1
    return f"{'Paused' if paused else 'Playing'}: {cur.get('title') or 'music'}" + (f" ({left} more after it)." if left else ".")


def state() -> dict | None:
    """What the music card shows: title, position, length, paused, volume, previous / next available. None = nothing
    plays (the card hides)."""
    cur = PLAYER.current()
    if not cur or not running():
        return None
    pos = _send("get_property", "time-pos", want=True)
    dur = _send("get_property", "duration", want=True) or cur.get("duration") or 0
    return {"title": cur.get("title") or "music", "pos": float(pos or 0), "duration": float(dur or 0),
            "paused": bool(_send("get_property", "pause", want=True)), "volume": PLAYER.volume,
            "has_next": PLAYER.i + 1 < len(PLAYER.queue), "has_prev": PLAYER.i > 0,
            "index": PLAYER.i + 1, "count": len(PLAYER.queue)}


def parse_time(spec: str) -> tuple[float, bool] | None:
    """'+30' / '30 seconds' (forward), '-10' / 'back 10 seconds', '1:30' / '2 minutes' / '90' as a position.
    Returns (seconds, relative) or None."""
    t = (spec or "").strip().lower()
    rel = t.startswith(("+", "-")) or bool(re.match(r"(?:skip|forward|ahead|back|rewind|behind)\b", t))
    back = t.startswith("-") or bool(re.match(r"(?:back|rewind|behind)\b", t))
    t = re.sub(r"^[+-]|^(?:skip|forward|ahead|back|rewind|behind)\s*(?:by\s+)?", "", t).strip()
    if m := re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", t):
        a, b, c = int(m.group(1)), int(m.group(2)), m.group(3)
        secs = a * 3600 + b * 60 + int(c) if c else a * 60 + b
    else:
        total, found = 0.0, False
        for n, u in re.findall(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)?\b", t):
            found = True
            unit = (u or "s")[0]
            total += float(n) * {"h": 3600, "m": 60, "s": 1}[unit]
        if not found:
            return None
        secs = total
    return (-secs if back else secs), rel


def seek(spec: str) -> str | None:
    """Jump in the song playing: forward / back by some time, or to a time ('skip 30 seconds', 'go to 1:30')."""
    if not running():
        return None
    got = parse_time(spec)
    if got is None:
        return "Say how far, e.g. 'skip 30 seconds', 'back 10 seconds' or 'go to 1:30'."
    secs, rel = got
    _send("seek", secs, "relative" if rel else "absolute")
    pos = _send("get_property", "time-pos", want=True)
    at = f" (now at {int(pos) // 60}:{int(pos) % 60:02d})" if isinstance(pos, (int, float)) else ""
    if rel:
        return f"{'Back' if secs < 0 else 'Forward'} {_dur(abs(secs))}{at}."
    return f"Playing from {int(secs) // 60}:{int(secs) % 60:02d}."


def _dur(secs: float) -> str:
    m, s_ = divmod(int(secs), 60)
    return f"{m} min {s_} s" if m and s_ else f"{m} min" if m else f"{s_} seconds"


VOLUME_KEY = "music_volume"
VOLUME_SETTLE_TRIES = 60  # x 0.5 s: a streamed song's mpv can take ~10 s to open its socket
DUCK_VOLUME = 25  # % while you speak to KURAMA or it answers, so it hears you over the music
_duck = {"on": False, "timer": None}


def duck(on: bool, max_s: float = 45.0) -> bool:
    """Lower the music while KURAMA listens / answers, back to normal after (and by itself after max_s)."""
    if not running():
        _duck["on"] = False
        return False
    t = _duck.get("timer")
    if t:
        t.cancel()
    if on:
        _send("set_property", "volume", min(DUCK_VOLUME, PLAYER.volume))
        _duck["on"] = True
        _duck["timer"] = threading.Timer(max_s, lambda: duck(False))  # never stay quiet if the 'off' never comes
        _duck["timer"].daemon = True
        _duck["timer"].start()
    elif _duck["on"]:
        _send("set_property", "volume", PLAYER.volume)
        _duck["on"] = False
    return True


def stop(quiet: bool = False) -> str | None:
    ok = PLAYER.stop()
    return None if quiet or not ok else "Stopped the music."
