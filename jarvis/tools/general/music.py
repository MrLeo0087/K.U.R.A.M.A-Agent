"""music: play music without the browser (YouTube sound via mpv + yt-dlp), playlists, local files, controls, 0 tokens (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="media", safety="safe", description="Music without the browser (sound only): play a song/artist/mood, a "
      "YouTube link or playlist, a saved playlist, or the songs in ~/Music; save/list/delete playlists; pause, resume, "
      "next, previous, volume, what's playing, stop.")
def music(action: Literal["play", "url", "playlist", "local", "save", "playlists", "delete", "pause", "resume", "next",
                          "previous", "volume_up", "volume_down", "volume_set", "status", "stop"] = "play",
          query: str = "", shuffle: bool = False) -> str:
    """Music player.

    Args:
        action: play (query = song/artist/mood), url (query = YouTube link; empty = the tab open in the browser),
            playlist (query = saved playlist name), local (query = folder, empty = ~/Music), save (query = name for
            the open/linked playlist), playlists (list them), delete (query = name), pause, resume, next, previous,
            volume_up / volume_down (query = step, default 15), volume_set (query = 0-130), status, stop.
        query: See action.
        shuffle: Play in random order.
    """
    from jarvis.core import music as m

    if action == "play":
        return m.play(query, shuffle)
    if action == "url":
        url = query
        if not url:
            from jarvis.core import links
            found = links.find_link()
            if isinstance(found, str):
                return "Open the YouTube playlist or song in your browser (or paste its link) and say it again."
            url = found[0]
        return m.play_url(url, shuffle)
    if action == "playlist":
        return m.play_playlist(query, shuffle) if query else m.playlists_text()
    if action == "local":
        return m.play_local(query, shuffle=True)
    if action == "save":
        name, _, url = query.partition("|")
        return m.save_playlist(name, url)
    if action == "playlists":
        return m.playlists_text()
    if action == "delete":
        return m.delete_playlist(query)
    out = {"pause": m.pause, "resume": m.resume, "next": m.next_track, "previous": m.prev_track,
           "volume_up": lambda: m.volume(int(query or 15)), "volume_down": lambda: m.volume(-int(query or 15)),
           "volume_set": lambda: m.volume(to=int(query or 60)), "status": m.now_playing,
           "stop": m.stop}[action]()
    return out or "No music is playing. Say 'play lofi music' to start some."
