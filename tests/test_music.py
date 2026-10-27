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
    assert music.next_track() == "Next song." and ["playlist-next", "force"] in mpv.cmds
    # media_control drives our player too: 'pause' when no browser player is running
    monkeypatch.setattr(mc, "status", lambda player="": None)
    assert mc.media_control("pause") == "Paused the music."
    assert mc.media_control("next") == "Next song."


def test_play_starts_mpv_sound_only(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    started = []
    monkeypatch.setattr(music.subprocess, "Popen", lambda cmd, **k: started.append(cmd))
    monkeypatch.setattr(music.shutil, "which", lambda b: "/usr/bin/" + b)
    monkeypatch.setattr(music.time, "sleep", lambda s: None)
    assert music.play("lofi music").startswith("Playing lofi music")
    cmd = started[0]
    assert cmd[0] == "mpv" and "--no-video" in cmd and cmd[-1] == "ytdl://ytsearch8:lofi music"


def test_routes():
    m = fastpath.match
    assert m("play lofi music").args == {"action": "play", "query": "lofi music"}
    assert m("listen to nepali songs").args["query"] == "nepali songs"
    assert m("play some music").args["query"] == "relaxing music"
    assert m("play despacito on youtube").tool == "youtube" and m("play the video").tool == "media_control"
    assert m("stop the music").tool == "media_control"  # none of ours running: pause the browser
