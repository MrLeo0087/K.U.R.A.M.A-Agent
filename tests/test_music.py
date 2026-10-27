import json
import socket
import threading

from jarvis.core import fastpath, music
from jarvis.tools.general import media_control as mc


class FakeMpv:
    """A tiny mpv IPC server on the real socket path (tmp XDG_RUNTIME_DIR)."""

    def __init__(self, path):
        self.state = {"pause": False, "volume": 60, "media-title": "Lofi Girl - beats", "pid": 1}
        self.cmds = []
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(path)
        self.srv.listen()
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            cmd = json.loads(c.recv(4096).decode())["command"]
            self.cmds.append(cmd)
            data = None
            if cmd[0] == "get_property":
                data = self.state.get(cmd[1])
            elif cmd[0] == "set_property":
                self.state[cmd[1]] = cmd[2]
            elif cmd[0] == "add":
                self.state[cmd[1]] += cmd[2]
            c.sendall((json.dumps({"data": data, "error": "success"}) + "\n").encode())
            c.close()


def test_controls_through_ipc(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert not music.running() and music.pause() is None
    mpv = FakeMpv(music._sock())
    assert music.running()
    assert music.pause() == "Paused the music." and mpv.state["pause"] is True
    assert music.now_playing() == "Paused: Lofi Girl - beats."
    assert music.resume() == "Playing again." and music.volume(10) == "Music volume 70%."
    assert music.next_track() == "Next song: Lofi Girl - beats." and ["playlist-next", "force"] in mpv.cmds
    # media_control drives our player too: 'pause' when no browser player is running
    monkeypatch.setattr(mc, "status", lambda player="": None)
    assert mc.media_control("pause") == "Paused the music."
    assert mc.media_control("next").startswith("Next song")


def test_play_search_playlists_and_local(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    started = []
    monkeypatch.setattr(music, "_spawn", lambda cmd: started.append(cmd) or False)
    monkeypatch.setattr(music.shutil, "which", lambda b: "/usr/bin/" + b)
    songs = [{"url": f"https://www.youtube.com/watch?v={i}", "title": t, "duration": 200}
             for i, t in zip("abc", ("Song a", "Other tune", "Third track"))]
    monkeypatch.setattr(music, "search", lambda q: songs)
    assert music.play("jazz music").startswith("Playing Song a. (+2 more)")  # distinct titles: all three
    cmd = started[-1]
    assert cmd[0] == "mpv" and "--no-video" in cmd and "--prefetch-playlist=yes" in cmd and cmd[-3:] == [s["url"] for s in songs]
    assert music.play("lofi music").startswith("Playing your lofi playlist")  # a saved favourite starts at once
    out = music.play("kya mujhe pyar hai by KK")  # one named song: just it, similar songs follow in the background
    assert "Similar songs come after it" in out and started[-1][-2:] == ["--", songs[0]["url"]]
    assert "Saved your study playlist" in music.save_playlist("study", "https://youtube.com/playlist?list=PL1")
    assert "study" in music.playlists_text() and "lofi" in music.playlists_text()
    assert "your study playlist on shuffle" in music.play_playlist("my study playlist", shuffle=True)
    assert "--shuffle" in started[-1] and started[-1][-1] == "https://youtube.com/playlist?list=PL1"
    assert music.play("study").startswith("Playing your study playlist")  # a saved name wins over a search
    assert "Deleted the study playlist" in music.delete_playlist("study") and music.find_playlist("study") is None
    assert "no music files" in music.play_local(str(tmp_path / "none"))
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "a.mp3").write_bytes(b"x")
    assert "Playing your 1 songs" in music.play_local(str(tmp_path / "m")) and "--loop-playlist=inf" in started[-1]


def test_search_filters_live_and_long(monkeypatch, tmp_path):
    import json as _json
    real = music
    entries = [{"id": "live", "duration": None, "live_status": "is_live", "title": "radio"},
               {"id": "long", "duration": 9000, "title": "3 hours"}, {"id": "song", "duration": 240, "title": "Song"}]
    monkeypatch.setattr(real.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": _json.dumps({"entries": entries})})())
    assert [s["url"][-4:] for s in real.search("kya mujhe pyar hai")] == ["song"]
    assert [s["url"][-4:] for s in real.search("lofi mix")] == ["long", "song"]  # a mix may be long, never live


def test_routes():
    m = fastpath.match
    assert m("play lofi music").args == {"action": "play", "query": "lofi music"}
    assert m("listen to nepali songs").args["query"] == "nepali songs"
    assert m("play some music").args["query"] == "relaxing music"
    assert m("play despacito on youtube").tool == "youtube" and m("play the video").tool == "media_control"
    assert m("stop the music").tool == "media_control"  # none of ours running: pause the browser


def test_more_routes(monkeypatch):
    m = fastpath.match
    assert m("play kya mujhe pyar hai by KK").args == {"action": "play", "query": "kya mujhe pyar hai KK"}
    assert m("play https://www.youtube.com/playlist?list=PLz").args == {"action": "url", "query": "https://www.youtube.com/playlist?list=PLz"}
    assert m("save this playlist as gym https://youtube.com/playlist?list=PLz").args["query"] == "gym|https://youtube.com/playlist?list=PLz"
    assert m("shuffle my study playlist").args == {"action": "playlist", "query": "study", "shuffle": True}
    assert m("show my playlists").args["action"] == "playlists" and m("play my music").args["action"] == "local"
    assert m("next") is None  # nothing of ours playing: plain 'next' isn't a command
    monkeypatch.setattr(music, "running", lambda: True)
    assert m("next").args == {"action": "next"} and m("skip").tool == "media_control" and m("previous").args == {"action": "previous"}
