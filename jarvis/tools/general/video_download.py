"""video_download: download a YouTube (or other site) video in a chosen quality with sound, or as MP3 (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="media", safety="safe",
      description="Download a YouTube/online video (link or search words) in a quality like 1080p/720p/4K with sound, "
                  "a whole playlist, or just the audio as MP3; runs in the background and says when done.")
def video_download(source: str = "", quality: str = "", audio: bool = False, playlist: bool = False) -> str:
    """Download a video.

    Args:
        source: The video/playlist link, or words to search YouTube for (empty = the video open in the browser).
        quality: 1080p, 720p, 4k ... (empty or "best" = 1080p; "extra high" / "max" = the highest there is).
        audio: True = MP3 audio only.
        playlist: True = the whole playlist.
    """
    from jarvis.core import ytdl
    if not source.strip() or source.strip().lower() in ("this", "this video", "it", "that", "now", "right now",
                                                        "please", "this one", "for me", "quickly", "fast"):
        source = this_video()
        if not source:
            return "error: open the video in your browser (or give its link), then ask again"
    return ytdl.start(source, quality, audio, playlist)


def this_video() -> str:
    """'Download this video': the tab open in the browser (extension), else a selected link / the page found by the
    browser's history, else a link on the clipboard."""
    from jarvis.core import browsertab, links, ytdl
    if tab := browsertab.get():
        return tab[0]
    found = links.find_link()
    if not isinstance(found, str) and found[0].startswith("http"):
        return found[0]
    from jarvis.tools.general import _sys
    clip = _sys.clip_get().strip()
    return clip if ytdl._URL.match(clip) else ""
