"""11-09: songs after the first come from YouTube's own radio (not a text search), the queue tops itself up near
its end (it stopped after 7), the Progress item can go back and jump on its bar."""
import json

from jarvis.core import music, progress


def test_radio_is_youtubes_mix_without_the_song_itself(monkeypatch):
    out = json.dumps({"entries": [{"id": "A", "title": "Perfect", "duration": 263},
                                  {"id": "B", "title": "Say You Won't Let Go", "duration": 211},
                                  {"id": "C", "title": "3 hour mix", "duration": 3 * 3600}]})
    seen = {}

    def run(argv, **kw):
        seen["url"] = argv[-1]
        return type("R", (), {"stdout": out})()
    monkeypatch.setattr(music.subprocess, "run", run)
    songs = music.radio("A")
    assert seen["url"].endswith("watch?v=A&list=RDA") and [s["id"] for s in songs] == ["B"]


def test_the_queue_tops_itself_up_near_its_end(monkeypatch):
    p = music.Player()
    p.queue, p.i = [{"id": "A", "url": "https://www.youtube.com/watch?v=A", "title": "a"},
                    {"id": "B", "url": "https://www.youtube.com/watch?v=B", "title": "b"}], 1
    monkeypatch.setattr(music, "radio", lambda vid, limit=40: [{"id": "C", "url": "u", "title": "c song", "duration": 200},
                                                                {"id": "A", "url": "u", "title": "a", "duration": 200}])
    started = []
    monkeypatch.setattr(music.threading, "Thread", lambda target, **kw: type("T", (), {"start": lambda self: started.append(target())})())
    p._top_up()
    assert [q["id"] for q in p.queue] == ["A", "B", "C"]  # more, never a song already queued


def test_the_progress_item_offers_previous_and_a_jump_bar(monkeypatch):
    monkeypatch.setattr(music, "state", lambda: {"title": "x", "pos": 30, "duration": 200, "paused": False,
                                                 "has_prev": True, "index": 2, "count": 9})
    it = progress._music()[0]
    assert it["dur"] == 200 and it["has_prev"] is True


def test_music_volume_can_boost_past_100_and_mpv_levels_quiet_songs(monkeypatch):
    monkeypatch.setattr(music, "running", lambda: True)
    monkeypatch.setattr(music, "_send", lambda *a, **k: True)
    monkeypatch.setattr(music.store, "kv_set", lambda *a: None)
    monkeypatch.setattr(music.PLAYER, "_volume", 70)
    assert music.volume(to=140) == "Music volume 140%." and music.volume(to=999) == "Music volume 150%."
    argv = music.PLAYER._mpv("t", ["x"])
    assert "--volume-max=150" in argv and any("dynaudnorm" in a for a in argv)


def test_finished_progress_items_can_be_removed_one_or_all(monkeypatch):
    import time
    from jarvis.core import store
    now = time.time()
    rows = [{"id": 1, "status": "done", "finished": now - 60, "title": "a"},
            {"id": 2, "status": "done", "finished": now - 30, "title": "b"}]
    monkeypatch.setattr(store, "jobs_list", lambda n, st: [r for r in rows if r["status"] in st])
    kv = {}
    monkeypatch.setattr(store, "kv_get", lambda k: kv.get(k))
    monkeypatch.setattr(store, "kv_set", lambda k, v: kv.__setitem__(k, v))
    progress.hide(1)
    assert [i["job"] for i in progress._job_items(now)] == [2]
    progress.hide()
    assert progress._job_items(time.time() + 1) == []


def test_speed_pitch_reverb_change_the_song_playing_and_stay(monkeypatch):
    sent, kv = [], {}
    monkeypatch.setattr(music, "running", lambda: True)
    monkeypatch.setattr(music, "_send", lambda *a, **k: sent.append(a) or True)
    monkeypatch.setattr(music.store, "kv_set", lambda k, v: kv.__setitem__(k, v))
    music._fx.clear()
    monkeypatch.setattr(music.store, "kv_get", lambda k: kv.get(k))
    f = music.set_fx(preset="slowed_reverb")
    assert f == {"speed": 0.85, "pitch": -2.0, "reverb": 55}
    assert ("set_property", "speed", 0.85) in sent and any("rubberband" in str(a) and "aecho" in str(a) for a in sent)
    assert music.set_fx(speed=9)["speed"] == 1.5 and "--speed=1.5" in music.PLAYER._mpv("t", ["x"])
    assert "rubberband" not in music.fx_chain(music.set_fx(preset="normal"))
    music._fx.clear()


def test_play_this_song_plays_the_youtube_tab_open_in_the_browser(monkeypatch):
    from jarvis.core import browsertab
    played = []
    monkeypatch.setattr(browsertab, "get", lambda: ("https://www.youtube.com/watch?v=abc123XYZ&list=PL1&index=3",
                                                  "(3) Perfect - Ed Sheeran - YouTube"))
    monkeypatch.setattr(music, "play_url", lambda url, shuffle=False, label="": played.append((url, label)) or "ok")
    for q in ("this song", "play this", "the song open in my browser", ""):
        music.play(q)
    assert played == [("https://www.youtube.com/watch?v=abc123XYZ", "Perfect - Ed Sheeran")] * 4
    monkeypatch.setattr(music, "_ok", lambda: "no mpv")
    assert music.play("perfect ed sheeran") == "no mpv"  # a title said: searched, not the tab
