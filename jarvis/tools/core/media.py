"""media: music and videos: play a song/artist/playlist, pause, resume, next, previous, stop, what's playing,
YouTube, hand-gesture control, download a video (safe dispatcher)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool
from jarvis.tools.core._hub import Act, onoff, run

TABLE = {
    "play": Act("music", lambda a: {"action": "play", "query": a.get("query", "")}),
    "pause": Act("media_control", lambda a: {"action": "pause"}),
    "resume": Act("media_control", lambda a: {"action": "play"}),
    "next": Act("media_control", lambda a: {"action": "next"}),
    "previous": Act("media_control", lambda a: {"action": "previous"}),
    "stop": Act("music", lambda a: {"action": "stop"}),
    "playing": Act("music", lambda a: {"action": "status"}),
    "youtube": Act("youtube", lambda a: {"query": a.get("query", ""), "action": "play"}),
    "gesture": Act("gesture_control", lambda a: {"action": onoff(a.get("query"), "on")}),
    "download": Act("video_download", lambda a: {"source": a.get("query")}),
}


@tool(group="core", safety="safe",
      description="Music and video: play a song, artist or playlist (sound only), pause, resume, next, previous, stop, "
                  "what's playing, play on YouTube, hand-gesture media control on/off, download a video.")
def media(action: Literal["play", "pause", "resume", "next", "previous", "stop", "playing", "youtube", "gesture", "download"],
          query: str = "") -> str:
    """Music and video.

    Args:
        action: play, pause, resume, next, previous, stop, playing, youtube, gesture, download.
        query: Song / artist / playlist / video to play, a video link to download, or on/off for gesture.
    """
    return run(TABLE, {"action": action, "query": query})
