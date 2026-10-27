"""music: play music without the browser (YouTube sound via mpv + yt-dlp), pause/next/volume/stop, 0 tokens (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="media", safety="safe", description="Play music without the browser (sound of YouTube results through "
      "mpv): play a song/artist/genre, pause, resume, next, previous, volume up/down, what's playing, stop.")
def music(action: Literal["play", "pause", "resume", "next", "previous", "volume_up", "volume_down", "status", "stop"] = "play",
          query: str = "") -> str:
    """Music player.

    Args:
        action: play (query = what to play), pause, resume, next, previous, volume_up, volume_down, status, stop.
        query: Song, artist, genre or mood for play ('lofi', 'arijit singh songs', 'nepali songs').
    """
    from jarvis.core import music as m

    if action == "play":
        return m.play(query)
    out = {"pause": m.pause, "resume": m.resume, "next": m.next_track, "previous": m.prev_track,
           "volume_up": lambda: m.volume(10), "volume_down": lambda: m.volume(-10), "status": m.now_playing,
           "stop": m.stop}[action]()
    return out or "No music is playing. Say 'play lofi music' to start some."
