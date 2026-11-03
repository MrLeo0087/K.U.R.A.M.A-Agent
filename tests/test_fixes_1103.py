"""11-03 owner session: 'open browser' opened Firefox (Brave is the default, and the owner said so); a song's title
alone went to the AI / web search; music started quiet and could stay ducked; Alt sometimes did nothing."""
import json

import pytest

from jarvis.core import config, fastpath, music, ptt, safety
from jarvis.tools.core import apps as apps_tool
from jarvis.tools.core._hub import resolve
from jarvis.tools.general import _apps
from jarvis.tools.general.app_name import app_name

APPS = [{"id": "firefox_firefox", "path": "", "name": "Firefox Web Browser", "generic": "Web Browser", "keywords": [],
         "wmclass": "", "exe": "firefox"},
        {"id": "brave-browser", "path": "", "name": "Brave Web Browser", "generic": "Web Browser", "keywords": [],
         "wmclass": "", "exe": "brave-browser-stable"},
        {"id": "code", "path": "", "name": "Visual Studio Code", "generic": "Text Editor", "keywords": [],
         "wmclass": "", "exe": "code"}]


@pytest.fixture
def apps_env(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(_apps, "index", lambda refresh=False: APPS)
    monkeypatch.setattr(_apps, "_default", {"id": "", "at": 0.0})
    return monkeypatch


@pytest.mark.parametrize("said", ["browser", "Browser", "the browser", "web browser"])
def test_browser_is_the_system_default(apps_env, said):
    apps_env.setattr(_apps, "default_browser", lambda: "brave-browser")
    assert _apps.find_app(said)[0]["id"] == "brave-browser"


def test_no_default_known_keeps_the_old_alias(apps_env):
    apps_env.setattr(_apps, "default_browser", lambda: "")
    assert _apps.find_app("browser")[0]["id"] == "firefox_firefox"


@pytest.mark.parametrize("word,app,want", [("browser", "brave", "brave-browser"), ("my editor", "vs code", "code"),
                                           ("internet", "firefox", "firefox_firefox")])
def test_taught_name_wins_and_can_be_forgotten(apps_env, word, app, want):
    apps_env.setattr(_apps, "default_browser", lambda: "")
    assert app_name(word, app).startswith("Got it")
    assert json.loads((config.DATA_DIR / "app_names.json").read_text())[_apps.clean_query(word)] == want
    entry, score = _apps.find_app(word.title())
    assert entry["id"] == want and score >= _apps.FASTPATH_MIN_SCORE  # the 0-token "Open X" uses it too
    assert app_name(word, "").startswith("Forgot") and _apps.clean_query(word) not in _apps.taught()


def test_unknown_app_is_not_saved(apps_env):
    assert app_name("browser", "netscape navigator").startswith("error")
    assert _apps.taught() == {}


def test_apps_tool_name_action():
    assert resolve(apps_tool.TABLE, {"action": "name", "target": "browser", "text": "brave"}) == \
        ("app_name", {"name": "browser", "app": "brave"})


@pytest.mark.parametrize("said,query", [("play us mod se suru kare", "us mod se suru kare"),
                                        ("Play tu hai kaha.", "tu hai kaha"), ("play kesariya", "kesariya"),
                                        ("play channa mereya bro", "channa mereya")])
def test_a_title_alone_plays_music(said, query):
    it = fastpath.music_intent(said)
    assert it and it.tool == "music" and it.args == {"action": "play", "query": query}


@pytest.mark.parametrize("said", ["play it", "play the video", "play this", "play chess with me", "play next video",
                                  "play a game", "play it again"])
def test_not_a_song_title(said):
    it = fastpath.music_intent(said)
    assert it is None or it.args.get("action") != "play"


def test_music_waits_for_the_song_not_a_background_job(monkeypatch):
    monkeypatch.setattr(safety, "_waits", {})
    assert safety._wait_for("music") >= 12 and safety._wait_for("media") >= 12


def test_music_volume_full_by_default_and_kept(monkeypatch):
    from jarvis.core import store
    store.kv_set(music.VOLUME_KEY, "")
    p = music.Player()
    assert p.volume == config.MUSIC_VOLUME == 100
    monkeypatch.setattr(music, "_send", lambda *a, **k: True)
    monkeypatch.setattr(music, "running", lambda: True)
    music.PLAYER._volume = 100
    assert music.volume(-30) == "Music volume 70%."
    assert music.Player().volume == 70  # a new song / a restart starts where the user left it
    store.kv_set(music.VOLUME_KEY, "")


def test_song_started_while_ducked_gets_the_volume_once_mpv_answers(monkeypatch):
    sent, answers = [], iter([None, None, True])
    monkeypatch.setattr(music, "_send", lambda *a, **k: sent.append(a) or next(answers))
    monkeypatch.setattr(music.time, "sleep", lambda s: None)
    monkeypatch.setitem(music._duck, "on", False)  # the un-duck already came (before the socket existed)
    p = music.Player()
    p.volume, p.gen = 90, 5
    p._settle_volume(5)
    assert sent == [("set_property", "volume", 90)] * 3
    sent.clear()
    p._settle_volume(4)  # an older song: nothing
    assert sent == []


def _holder():
    told, t, timers = [], [0.0], []
    h = ptt.Holder("alt", tell=told.append, now=lambda: t[0], min_hold=0.0,
                   schedule=lambda d, fn: timers.append(fn) or type("T", (), {"cancel": lambda self: None})())
    return h, told, t, timers


@pytest.mark.parametrize("press,release", [("!", "1"), ("@", "2"), ("A", "a")])
def test_alt_works_after_a_key_whose_release_has_another_name(press, release):
    h, told, t, timers = _holder()
    h.press("shift"); h.press(press); h.release("shift"); h.release(release)  # Shift+1: '!' down, '1' up
    t[0] = 1.0; h.press("alt_l"); t[0] = 1.4; timers[-1](); t[0] = 2.0; h.release("alt_l")
    assert told == ["down", "up"]


def test_ctrl_alt_shortcut_still_never_talks():
    h, told, t, timers = _holder()
    h.press("ctrl_l"); h.press("alt_l"); t[0] = 0.5; timers[-1](); h.release("alt_l"); h.release("ctrl_l")
    assert told == []
