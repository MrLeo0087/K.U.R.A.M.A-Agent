from jarvis.core import fastpath, ytdl


def test_quality_and_args():
    assert ytdl.height_of("1080p") == 1080 and ytdl.height_of("4k") == 2160 and ytdl.height_of("") == 0
    a = ytdl.build_args("https://youtu.be/x", "1080p")
    assert "bv*[height<=1080]+ba/b[height<=1080]" in a and "mp4" in a and a[-1] == "https://youtu.be/x"
    a = ytdl.build_args("shape of you", audio=True)
    assert "mp3" in a and a[-1] == "ytsearch1:shape of you"
    assert "--yes-playlist" in ytdl.build_args("https://youtube.com/playlist?list=1", playlist=True)


def test_fastpath_video_vs_file():
    i = fastpath.match("download this youtube video in 1080p")
    assert i.tool == "video_download" and i.args["quality"] == "1080p" and i.args["source"] == ""
    assert fastpath.match("download the song shape of you as mp3").args["audio"] is True
    assert fastpath.match("download https://example.com/data.zip").tool == "download_file"
    assert fastpath.match("download https://youtu.be/abc in 720p").args["source"] == "https://youtu.be/abc"


def test_start_runs_in_background(monkeypatch, tmp_path):
    started = {}

    class P:
        stdout = None

        def wait(self):
            return 0
    monkeypatch.setattr(ytdl.config, "VIDEO_DIR", str(tmp_path))
    monkeypatch.setattr(ytdl.config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ytdl.subprocess, "Popen", lambda argv, **k: started.setdefault("argv", argv) and P())
    monkeypatch.setattr(ytdl, "_wait", lambda *a: None)
    out = ytdl.start("https://youtu.be/x", "720p")
    assert "background" in out and "yt_dlp" in started["argv"]
