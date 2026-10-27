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


def _own_music(action: str, music) -> str:
    """The same action on KURAMA's music player, if it is running ('' otherwise)."""
    if not music.running():
        return ""
    fn = {"pause": music.pause, "play": music.resume, "play_pause": music.pause, "next": music.next_track,
          "previous": music.prev_track, "status": music.now_playing, "stop": music.pause}.get(action)
    return (fn() or "") if fn else ""


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
    from jarvis.core import music
    own = "" if player else _own_music(action, music)  # KURAMA's mpv music has no MPRIS: drive it directly
    try:
        st = status(player)
        if st is None:
            return own or f"error: {NO_PLAYER}"
        if own and action in ("next", "previous", "status"):
            return own
        if action == "status":
            meta = _sys.run([*_base(player), "metadata", "--format", "{{artist}} - {{title}}"],
                            ok_codes=(0, 1)).strip(" -\n")
            return f"{st.lower()}: {meta}" if meta else st.lower()
        if action not in COMMANDS:
            return f"error: unknown action {action!r}"
        # pause = every player (the default one may be an idle Spotify while the browser video plays)
        if own and action == "play" and st.lower() != "paused":  # the music was paused, the browser wasn't
            return own
        _sys.run([*(_base(player) if player or action != "pause" else ["playerctl", "-a"]), COMMANDS[action]])
        if action == "play_pause":
            return "paused" if st.lower() == "playing" else "playing"
        return DONE[action]
    except _sys.SysError as e:
        return f"error: {e}"


alias("playlist", "media_control", lambda a: {"name": a.get("name", "")}, action="playlist")
