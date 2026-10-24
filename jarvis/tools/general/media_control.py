"""media_control: play/pause/next/previous/stop/status of the active media player via playerctl (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import alias, tool
from jarvis.tools.general import _sys

COMMANDS = {"play": "play", "pause": "pause", "play_pause": "play-pause", "next": "next",
            "previous": "previous", "stop": "stop"}
DONE = {"play": "playing", "pause": "paused", "next": "next track", "previous": "previous track",
        "stop": "stopped"}
NO_PLAYER = "no media player is running"


def _base(player: str) -> list[str]:
    return ["playerctl", "-p", player] if player else ["playerctl"]


def status(player: str = "") -> str | None:
    """'Playing' / 'Paused' / 'Stopped', or None when no player is running."""
    out = _sys.run([*_base(player), "status"], ok_codes=(0, 1)).strip()
    return out if out and "no player" not in out.lower() else None


@tool(group="media", safety="safe",
      description="Control music/video playback (play, pause, next, previous, stop, what's playing) or play one of "
                  "the user's named playlists.")
def media_control(action: Literal["play_pause", "play", "pause", "next", "previous", "stop", "status",
                                  "playlist"] = "play_pause", player: str = "", name: str = "") -> str:
    """Media player control (Spotify, browser video, VLC...).

    Args:
        action: play_pause (toggle), play, pause, next, previous, stop, status, or playlist (play `name`).
        player: Optional player name (spotify, firefox, vlc); empty = the active one.
        name: The playlist's name (action=playlist; empty = list them).
    """
    if action == "playlist":
        from jarvis.tools.general.playlist import playlist
        return playlist(name)
    try:
        st = status(player)
        if st is None:
            return f"error: {NO_PLAYER}"
        if action == "status":
            meta = _sys.run([*_base(player), "metadata", "--format", "{{artist}} - {{title}}"],
                            ok_codes=(0, 1)).strip(" -\n")
            return f"{st.lower()}: {meta}" if meta else st.lower()
        if action not in COMMANDS:
            return f"error: unknown action {action!r}"
        _sys.run([*_base(player), COMMANDS[action]])
        if action == "play_pause":
            return "paused" if st.lower() == "playing" else "playing"
        return DONE[action]
    except _sys.SysError as e:
        return f"error: {e}"


alias("playlist", "media_control", lambda a: {"name": a.get("name", "")}, action="playlist")
