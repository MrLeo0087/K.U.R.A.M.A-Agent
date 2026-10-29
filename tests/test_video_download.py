from jarvis.core import automation, fastpath, store, ytdl


def test_quality_and_args():
    assert ytdl.height_of("1080p") == 1080 and ytdl.height_of("4k") == 2160
    assert ytdl.height_of("") == 1080 and ytdl.height_of("best quality") == 1080  # the default is 1080p
    assert ytdl.height_of("extra high") == 0 and ytdl.height_of("max") == 0  # the highest there is
    a = ytdl.build_args("https://youtu.be/x", "1080p")
    assert "bv*[height<=1080]+ba/b[height<=1080]" in a and "mp4" in a and a[-1] == "https://youtu.be/x"
    assert "--progress-template" in a
    a = ytdl.build_args("shape of you", audio=True)
    assert "mp3" in a and a[-1] == "ytsearch1:shape of you"
    assert "--yes-playlist" in ytdl.build_args("https://youtube.com/playlist?list=1", playlist=True)
    assert ytdl.split_source("https://youtu.be/x 1080p audio") == ("https://youtu.be/x", "1080p audio")


def test_fastpath_video_vs_file():
    i = fastpath.match("download this youtube video in 1080p")
    assert i.tool == "video_download" and i.args["quality"] == "1080p" and i.args["source"] == ""
    assert fastpath.match("download the song shape of you as mp3").args["audio"] is True
    assert fastpath.match("download https://example.com/data.zip").tool == "download_file"
    assert fastpath.match("download https://youtu.be/abc in 720p").args["source"] == "https://youtu.be/abc"
    i = fastpath.match("download this song in best quality")
    assert i.args["source"] == "" and i.args["quality"] == "best" and i.args["audio"] is False
    i = fastpath.match("save this video link")
    assert i is None or i.tool != "video_download"


def test_progress_parsing():
    st = {}
    assert not ytdl.parse_progress("[youtube] x: Downloading webpage", st)
    assert ytdl.parse_progress("KP 50000000 100000000 NA 2000000 25 avc1 My Song", st)
    assert st["part"] == "video" and st["done"] == 50e6 and st["total"] == 100e6 and st["title"] == "My Song"
    ytdl.parse_progress("KP 100000000 100000000 NA 0 0 avc1 My Song", st)
    ytdl.parse_progress("KP 1000000 5000000 NA 1000000 4 none My Song", st)  # the sound part starts
    assert st["part"] == "sound" and st["done"] == 101e6 and st["total"] == 105e6
    assert ytdl.progress_text(st).startswith("sound 96%")


def test_start_tracks_progress_and_skips_duplicates(monkeypatch, tmp_path):
    class P:
        pid = 4242
        stdout = None

        def wait(self):
            return 0
    started = []
    monkeypatch.setattr(ytdl.config, "VIDEO_DIR", str(tmp_path))
    monkeypatch.setattr(ytdl.config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ytdl.subprocess, "Popen", lambda argv, **k: started.append(argv) or P())
    monkeypatch.setattr(ytdl.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(ytdl.threading, "Thread", lambda **k: type("T", (), {"start": lambda self: None})())
    out = ytdl.start("https://youtu.be/x", "720p")
    assert "background" in out and "yt_dlp" in started[0]
    assert "Already downloading" in ytdl.start("https://youtu.be/x")
    assert len(started) == 1
    w = next(w for w in store.watches_list(("active",)) if w["kind"] == "ytdl")
    w["state"].update(done=30e6, total=60e6)
    store.watch_update(w["id"], state=w["state"])
    item = next(d for d in automation.live_downloads() if d["kind"] == "ytdl")
    assert item["frac"] == 0.5 and item["status"] == "active" and "50%" in item["sub"]


def test_plain_file_links_go_to_the_download_manager(monkeypatch):
    queued = []
    monkeypatch.setattr(automation, "queue", lambda url, *a: queued.append(url) or "Download #1")
    assert ytdl.start("https://example.com/cat.jpg") == "Download #1" and queued == ["https://example.com/cat.jpg"]
    assert not ytdl.is_plain_file("https://www.youtube.com/watch?v=abc")
