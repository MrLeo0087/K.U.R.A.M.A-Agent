"""video_download: download a YouTube (or other site) video in a chosen quality with sound, or as MP3 (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="media", safety="safe",
      description="Download a YouTube/online video (link or search words) in a quality like 1080p/720p/4K with sound, "
                  "a whole playlist, or just the audio as MP3; runs in the background and says when done.")
def video_download(source: str = "", quality: str = "", audio: bool = False, playlist: bool = False) -> str:
    """Download a video.

    Args:
        source: The video/playlist link, or words to search YouTube for (empty = a link on the clipboard).
        quality: 1080p, 720p, 4k, hd ... (empty = best available).
        audio: True = MP3 audio only.
        playlist: True = the whole playlist.
    """
    from jarvis.core import ytdl
    if not source.strip() or source.strip().lower() in ("this", "this video", "it", "that"):
        from jarvis.tools.general import _sys
        clip = _sys.clip_get().strip()
        if not ytdl._URL.match(clip):
            return "error: give a link (or copy the video link first)"
        source = clip
    return ytdl.start(source, quality, audio, playlist)
