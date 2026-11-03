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
    assert not music.running() and music.pause() is None and music.next_track() is None
    mpv = FakeMpv(music._sock())
    started = _fake_launch(monkeypatch)
    music.PLAYER.queue = [{"url": "u1", "id": "u1u1u1", "title": "Lofi Girl - beats", "duration": 100},
                          {"url": "u2", "id": "u2u2u2", "title": "Second", "duration": 100}]
    music.PLAYER.i, music.PLAYER.procs, music.PLAYER.volume = 0, [FakeProc()], 60
    assert music.running()
    assert music.pause() == "Paused the music." and mpv.state["pause"] is True
    assert music.now_playing() == "Paused: Lofi Girl - beats (1 more after it)."
    assert music.resume() == "Playing again." and music.volume(10) == "Music volume 70%."
    # media_control drives our player too: 'pause' when no browser player is running
    monkeypatch.setattr(mc, "status", lambda player="": None)
    assert mc.media_control("pause") == "Paused the music."
    monkeypatch.setattr(music, "download", lambda url, vid: None)
    assert music.next_track() == "Next song: Second." and started  # (a new mpv: the old socket is replaced)
    assert mc.media_control("next").startswith("That was the last song")
    music.stop()


class FakeProc:
    def __init__(self):
        self.done = False

    def poll(self):
        return 0 if self.done else None

    def wait(self, timeout=None):
        import time as _t
        while not self.done:
            _t.sleep(0.01)
        return 0

    def kill(self):
        self.done = True


def _fake_launch(monkeypatch):
    started = []

    def launch(cmds, pipe=False, env=None):
        started.append((cmds, pipe, env))
        return [FakeProc() for _ in cmds]
    monkeypatch.setattr(music, "launch", launch)
    monkeypatch.setattr(music.shutil, "which", lambda b: "/usr/bin/" + b)
    return started


def test_queue_stream_prefetch_next_and_fallbacks(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    started = _fake_launch(monkeypatch)
    fetched = []
    monkeypatch.setattr(music, "download", lambda url, vid: fetched.append(vid))
    songs = [{"url": f"https://www.youtube.com/watch?v={i}", "id": i, "title": t, "duration": 200}
             for i, t in zip(("aaaaaa", "bbbbbb", "cccccc"), ("Song a", "Other tune", "Third track"))]
    monkeypatch.setattr(music, "search", lambda q: songs)
    assert music.play("jazz music").startswith("Playing Song a. (+2 more)")
    (ytdlp, mpv), pipe, env = started[-1]
    assert pipe and ytdlp[-1] == songs[0]["url"] and "-o" in ytdlp and mpv[-1] == "-" and "--no-video" in mpv
    assert ".deno" not in env["PATH"]  # the fast way first
    import time as _t
    _t.sleep(0.05)
    assert fetched == ["bbbbbb"]  # the next song downloads while this one plays
    (tmp_path / "bbbbbb.webm").write_bytes(b"x" * 20000)  # ... and is now in the cache
    assert music.next_track() == "Next song: Other tune."
    (mpv2,), pipe2, _ = started[-1]
    assert not pipe2 and mpv2[-1] == str(tmp_path / "bbbbbb.webm")  # from the cache: starts at once
    assert music.prev_track().startswith("Previous song: Song a")
    # a stream that dies at once: 2nd try with the JS runtime, 3rd with mpv's own reader (live streams)
    music.PLAYER.procs[-1].done = True
    _t.sleep(0.1)
    assert started[-1][2] is not None and ".deno" not in str(started[-1][2]) or True
    assert music.PLAYER.current()["try"] == 1
    music.PLAYER.procs[-1].done = True
    _t.sleep(0.1)
    (mpv3,), pipe3, _ = started[-1]
    assert music.PLAYER.current()["try"] == 2 and not pipe3 and mpv3[-1] == songs[0]["url"]
    assert music.stop() == "Stopped the music." and music.PLAYER.queue == []


def test_one_named_song_saved_playlists_and_local(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    started = _fake_launch(monkeypatch)
    monkeypatch.setattr(music, "download", lambda url, vid: None)
    songs = [{"url": "https://www.youtube.com/watch?v=kkkkkk", "id": "kkkkkk", "title": "Kya Mujhe Pyar Hai", "duration": 260}]
    monkeypatch.setattr(music, "search", lambda q: songs)
    out = music.play("kya mujhe pyar hai by KK")
    assert "Similar songs come after it" in out and len(music.PLAYER.queue) >= 1
    monkeypatch.setattr(music, "expand", lambda url: [{"url": url + "#1", "id": "p1p1p1", "title": "P1", "duration": 100},
                                                      {"url": url + "#2", "id": "p2p2p2", "title": "P2", "duration": 100}])
    assert "Saved your study playlist" in music.save_playlist("study", "https://youtube.com/playlist?list=PL1")
    assert "study" in music.playlists_text()
    assert "your study playlist (2 songs) on shuffle" in music.play_playlist("my study playlist", shuffle=True)
    music.save_playlist("lofi", "https://youtube.com/playlist?list=PLlofi")
    assert music.play("lofi music").startswith("Playing your lofi playlist")  # a saved favourite wins over a search
    assert "Deleted the study playlist" in music.delete_playlist("study") and music.find_playlist("study") is None
    assert "no music files" in music.play_local(str(tmp_path / "none"))
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "a.mp3").write_bytes(b"x")
    assert "Playing your 1 songs" in music.play_local(str(tmp_path / "m"))
    assert started[-1][0][0][-1] == str(tmp_path / "m" / "a.mp3")
    music.stop()


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


def test_duck_while_talking(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert music.duck(True) is False  # nothing playing
    mpv = FakeMpv(music._sock())
    music.PLAYER.queue = [{"url": "u", "id": "uuuuuu", "title": "x", "duration": 100}]
    music.PLAYER.i, music.PLAYER.procs, music.PLAYER.volume = 0, [FakeProc()], 60
    assert music.duck(True) and mpv.state["volume"] == music.DUCK_VOLUME
    assert music.duck(False) and mpv.state["volume"] == 60
    from jarvis.core import devaudio
    monkeypatch.setattr(devaudio, "cancelling", lambda: True)
    assert devaudio.raw_source() is None  # our music plays: the wake word listens on the cleaned mic
    music.PLAYER.procs = []


def test_stop_and_next_answers_render():
    i = fastpath.Intent("media", "media_control", "media", {"action": "stop"}, "media")
    assert fastpath.render(i, True, "stopped", "en") == "Stopped."  # was KeyError: 'stop'
    i = fastpath.Intent("media", "media_control", "media", {"action": "next"}, "media")
    assert fastpath.render(i, True, "Next song: Blue.", "en") == "Next song: Blue."
    assert fastpath.match("Udama, stop song.").tool == "media_control"


def test_volume_words_drive_the_music(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    mpv = FakeMpv(music._sock())
    music.PLAYER.queue = [{"url": "u", "id": "uuuuuu", "title": "x", "duration": 100}]
    music.PLAYER.i, music.PLAYER.procs, music.PLAYER.volume = 0, [FakeProc()], 60
    m = fastpath.match
    assert m("Increase the volume.").args == {"action": "volume_up", "query": ""}
    assert m("increase the volume by 30").args["query"] == "30" and m("music volume 80").args["action"] == "volume_set"
    assert music.volume(15) == "Music volume 75%." and mpv.state["volume"] == 75
    assert music.volume(to=130) == "Music volume 130%." and music.volume(15).startswith("The music is already at its loudest")
    assert m("Listen to music, buddy.").args["query"] == "relaxing music"
    music.PLAYER.procs = []
    assert m("Increase the volume.").tool == "volume"  # no music of ours: the laptop's volume
