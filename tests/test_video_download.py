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
    assert ytdl.parse_progress("KP\t50000000\t100000000\tNA\t2000000\t25\tavc1\t/v/My_Song [1080p].f399.mp4.part\tMy Song", st)
    assert st["part"] == "video" and st["done"] == 50e6 and st["total"] == 100e6 and st["title"] == "My Song"
    assert st["tmp"].endswith(".f399.mp4.part")
    ytdl.parse_progress("KP\t100000000\t100000000\tNA\t0\t0\tavc1\tNA\tMy Song", st)
    ytdl.parse_progress("KP\t1000000\t5000000\tNA\t1000000\t4\tnone\tNA\tMy Song", st)  # the sound part starts
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
    monkeypatch.setattr(ytdl.os, "killpg", lambda *a: None)
    monkeypatch.setattr(ytdl.time, "sleep", lambda s: None)
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


def test_bot_check_retries_with_browser_cookies_and_plain_errors(monkeypatch, tmp_path):
    bot = "ERROR: [youtube] x: Sign in to confirm you're not a bot. See  https://github.com/yt-dlp/yt-dlp/wiki/FAQ"
    assert "signed-in browser" in ytdl.friendly_error(bot) and "github" not in ytdl.friendly_error(bot)
    assert ytdl.friendly_error("ERROR: Unsupported URL: https://x.y") == "That site isn't supported for video download."
    logf = tmp_path / "y.log"
    logf.write_text(bot)
    monkeypatch.setattr(ytdl.config, "VIDEO_COOKIES_BROWSER", "brave")
    assert ytdl._cookie_retry(logf, ["yt", "https://youtu.be/x"])
    assert not ytdl._cookie_retry(logf, ["yt", "--cookies-from-browser", "brave", "https://youtu.be/x"])
    monkeypatch.setattr(ytdl.config, "VIDEO_COOKIES_BROWSER", "")
    assert not ytdl._cookie_retry(logf, ["yt", "https://youtu.be/x"])


def test_pause_resume_and_delete(monkeypatch, tmp_path):
    class P:
        pid = 77
        stdout = None
    killed = []
    monkeypatch.setattr(ytdl.config, "VIDEO_DIR", str(tmp_path))
    monkeypatch.setattr(ytdl.config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ytdl.subprocess, "Popen", lambda argv, **k: P())
    monkeypatch.setattr(ytdl.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(ytdl.os, "killpg", lambda pg, sig: killed.append(pg))
    monkeypatch.setattr(ytdl.time, "sleep", lambda s: None)
    monkeypatch.setattr(ytdl.threading, "Thread", lambda **k: type("T", (), {"start": lambda self: None})())
    ytdl.start("https://youtu.be/p")
    wid = next(w["id"] for w in store.watches_list(("active",)) if w["kind"] == "ytdl")
    part = tmp_path / "Song [1080p].f399.mp4.part"
    part.write_text("x")
    keep = tmp_path / "Other.mp4"
    keep.write_text("x")
    w = store.watch_get(wid)
    w["state"]["tmp"] = str(part)
    store.watch_update(wid, state=w["state"])
    assert ytdl.control(wid, "pause") == "Paused." and killed == [77]
    assert next(d for d in automation.live_downloads() if d["id"] == wid)["status"] == "paused"
    assert ytdl.control(wid, "resume") == "Resumed." and store.watch_get(wid)["status"] == "active"
    assert "partial" in ytdl.control(wid, "delete")
    assert not part.exists() and keep.exists()  # only this download's leftovers go
    assert all(d["id"] != wid for d in automation.live_downloads())


def test_this_video_now_is_the_open_tab_not_a_search_for_now():
    for t in ("download this youtube video now", "download this video please", "download this youtube video"):
        i = fastpath.match(t)
        assert i.tool == "video_download" and i.args["source"] == "", t
    assert fastpath.match("download interstellar trailer in 4k").args["source"] == "interstellar trailer"  # still a search


def test_library_lists_finished_videos_and_trashes_only_inside_the_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(ytdl.config, "VIDEO_DIR", str(tmp_path))
    (tmp_path / "Song [1080p].mp4").write_text("x")
    (tmp_path / "Song [1080p].f399.mp4").write_text("x")  # a separate track, not a finished video
    (tmp_path / "Clip.mp4.part").write_text("x")
    items = ytdl.library()
    assert [i["name"] for i in items] == ["Song [1080p].mp4"] and items[0]["day"] == "Today"
    trashed = []
    monkeypatch.setattr(ytdl.subprocess, "run", lambda argv, **k: trashed.append(argv[-1]))
    assert ytdl.remove(["../outside.mp4", "Song [1080p].mp4"]) == "Moved 1 video to the Trash."
    assert trashed == [str(tmp_path / "Song [1080p].mp4")]
