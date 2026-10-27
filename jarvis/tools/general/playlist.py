"""playlist: play a named playlist from config.PLAYLISTS (URL -> browser; local folder -> mpv if
installed, else the default player via xdg-open). Safe.

No longer a tool of its own: the merged tool calls playlist() (old name kept as an alias)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from jarvis.core import config
from jarvis.tools.general import open_url


def _spawn(argv: list[str]) -> None:
    """Detached player (patched in tests)."""
    subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                     start_new_session=True)


def find(name: str) -> tuple[str, str] | None:
    q = name.lower().strip()
    q = q.removesuffix(" playlist").removeprefix("my ").strip()
    lists = {k.lower(): (k, v) for k, v in config.PLAYLISTS.items()}
    if q in lists:
        return lists[q]
    hits = [kv for k, kv in lists.items() if q and (q in k or k in q)]
    return hits[0] if hits else None


def playlist(name: str = "") -> str:
    """Named playlist.

    Args:
        name: Playlist name from the user's list (empty = list them).
    """
    names = ", ".join(config.PLAYLISTS) or "none yet (add them to PLAYLISTS in config.py)"
    if not name.strip():
        return f"Your playlists: {names}."
    hit = find(name)
    if not hit:
        return f"error: no playlist called {name!r}. Your playlists: {names}."
    label, target = hit
    if target.startswith(("http://", "https://")):
        if shutil.which("mpv"):  # sound only, no browser tab (jarvis/core/music.py)
            from jarvis.core import music
            return music.play_url(target, label=f"your {label} playlist")
        open_url._open(target)
        return f"Playing your {label} playlist."
    folder = Path(target).expanduser()
    if not folder.exists():
        return f"error: the {label} playlist folder {folder} does not exist"
    if mpv := shutil.which("mpv"):
        _spawn([mpv, "--player-operation-mode=pseudo-gui", "--shuffle", "--", str(folder)])
    elif xdg := shutil.which("xdg-open"):
        _spawn([xdg, str(folder)])
    else:
        return "error: no player found: sudo apt install mpv"
    return f"Playing your {label} playlist."
