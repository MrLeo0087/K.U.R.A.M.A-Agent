"""set_wallpaper: set the desktop wallpaper from a path, a name, or the next/random image in
config.WALLPAPER_DIRS; sets both picture-uri and picture-uri-dark (light and dark mode). Safe."""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse

from jarvis.core import config
from jarvis.core.registry import tool
from jarvis.tools.general import _desk, _sys

EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".svg"}
MAX_FILES = 2000


def images() -> list[Path]:
    """Sorted wallpaper candidates (screenshots and hidden folders skipped, capped)."""
    seen: dict[str, Path] = {}
    skip = Path(config.SCREENSHOT_DIR).expanduser()
    for d in config.WALLPAPER_DIRS:
        d = Path(d).expanduser()
        if not d.is_dir():
            continue
        try:
            for p in d.rglob("*"):
                if len(seen) >= MAX_FILES:
                    break
                rel = p.relative_to(d).parts
                if p.suffix.lower() in EXTS and not any(x.startswith(".") for x in rel) \
                        and skip not in p.parents and p.is_file():
                    seen.setdefault(str(p.resolve()), p.resolve())
        except OSError:
            continue
    return sorted(seen.values(), key=lambda p: str(p).lower())


# The live wallpaper (scripts/kurama_wallpaper.py) puts a dashboard snapshot on the GNOME desktop for an instant
# login and keeps the real wallpaper here.
SNAP_DIR = Path.home() / ".local/share/kurama"
SNAP_URI = (SNAP_DIR / "desktop.png").as_uri()
REAL_WALLPAPER = SNAP_DIR / "real-wallpaper.json"


def current() -> Path | None:
    uri = _desk.gs_get(_desk.BG, "picture-uri") or ""
    if uri == SNAP_URI:
        try:
            uri = json.loads(REAL_WALLPAPER.read_text()).get("picture-uri", "")
        except (OSError, ValueError):
            return None
    if not uri.startswith("file://"):
        return None
    return Path(unquote(urlparse(uri).path))


def apply(path: Path) -> None:
    uri = path.resolve().as_uri()
    _desk.gs_set(_desk.BG, "picture-uri", uri)
    _desk.gs_set(_desk.BG, "picture-uri-dark", uri)
    _desk.gs_set(_desk.BG, "picture-options", "zoom")


def _pick(image: str, mode: str) -> Path | str:
    if image:
        p = Path(image).expanduser()
        if p.is_file():
            return p if p.suffix.lower() in EXTS else f"error: {p.name} is not an image ({', '.join(sorted(EXTS))})"
        if "/" in image:
            return f"error: no such file: {image}"
        hits = [x for x in images() if image.lower() in x.stem.lower()]
        return hits[0] if hits else f"error: no wallpaper named {image!r} in {', '.join(map(str, config.WALLPAPER_DIRS))}"
    pics = images()
    if not pics:
        return "error: no images found in " + ", ".join(map(str, config.WALLPAPER_DIRS))
    cur = current()
    if mode == "random":
        others = [p for p in pics if p != cur] or pics
        return random.choice(others)
    i = pics.index(cur) if cur in pics else -1
    return pics[(i + 1) % len(pics)]


@tool(group="desktop", safety="safe", description="Change the desktop wallpaper (an image path or name, next, random) or tell the current one.")
def set_wallpaper(image: str = "", mode: Literal["set", "next", "random", "current"] = "set") -> str:
    """Desktop wallpaper.

    Args:
        image: Image path (~ allowed) or part of a file name in the wallpaper folders.
        mode: set (use image), next, random, or current (just report it).
    """
    if err := _desk.need_gsettings():
        return err
    if mode == "current":
        cur = current()
        return f"The wallpaper is {cur.name} ({cur})." if cur else "The wallpaper is not an image file."
    if mode == "set" and not image:
        mode = "next"
    pick = _pick(image if mode == "set" else "", mode)
    if isinstance(pick, str):
        return pick
    try:
        apply(pick)
    except _sys.SysError as e:
        return f"error: could not set the wallpaper ({e})"
    return f"Wallpaper set to {pick.name}."
