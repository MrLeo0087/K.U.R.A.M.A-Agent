"""P5a general tools: weather, world time, open/close/focus app, remember/recall/forget, fast path.
All mocked: no network, no real app launches, no LLM."""
import pytest

from jarvis.core import agent, config, fastpath, llm, planner, registry, safety, store
from jarvis.tools.general import _apps, _geo, open_url, weather as weather_mod
from jarvis.tools.general.echo_time import get_time
from jarvis.tools.general.recall import recall
from jarvis.tools.general.remember import remember

PLACES = {
    "nepalgunj": {"name": "Nepalgunj", "country": "Nepal", "latitude": 28.05, "longitude": 81.61,
                  "timezone": "Asia/Kathmandu"},
    "tokyo": {"name": "Tokyo", "country": "Japan", "latitude": 35.69, "longitude": 139.69,
              "timezone": "Asia/Tokyo"},
    "kathmandu": {"name": "Kathmandu", "country": "Nepal", "latitude": 27.7, "longitude": 85.3,
                  "timezone": "Asia/Kathmandu"},
}
FORECAST = {
    "current": {"temperature_2m": 24.4, "apparent_temperature": 25.1, "relative_humidity_2m": 60,
                "weather_code": 2, "wind_speed_10m": 5.2},
    "daily": {"time": ["2026-10-23", "2026-10-24", "2026-10-25"], "weather_code": [2, 61, 0],
              "temperature_2m_min": [18, 17, 16], "temperature_2m_max": [30, 28, 29],
              "precipitation_probability_max": [10, 80, 0]},
}


@pytest.fixture
def http(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake(url, params):
        calls.append((url, dict(params)))
        if url == _geo.GEOCODE_URL:
            hit = PLACES.get(params["name"].lower())  # "Nepalganj" misses: tests the spelling fallback
            return {"results": [hit]} if hit else {}
        n = params["forecast_days"]
        return {"current": FORECAST["current"],
                "daily": {k: v[:n] for k, v in FORECAST["daily"].items()}}

    monkeypatch.setattr(_geo, "get_json", fake)
    _geo._geo_cache.clear()
    weather_mod._cache.clear()
    yield calls
    _geo._geo_cache.clear()
    weather_mod._cache.clear()


DESKTOP = {
    "code.desktop": "[Desktop Entry]\nType=Application\nName=Visual Studio Code\nExec=/usr/share/code/code %F\n"
                    "StartupWMClass=Code\nKeywords=vscode;\n[Desktop Action new]\nName=New Window\n",
    "org.gnome.Nautilus.desktop": "[Desktop Entry]\nType=Application\nName=Files\nKeywords=folder;manager;\n"
                                  "Exec=nautilus --new-window %U\n",
    "org.gnome.Terminal.desktop": "[Desktop Entry]\nType=Application\nName=Terminal\nExec=gnome-terminal\n",
    "hidden.desktop": "[Desktop Entry]\nType=Application\nName=Hidden Thing\nNoDisplay=true\nExec=hidden\n",
    "org.gnome.Calculator.desktop": "[Desktop Entry]\nType=Application\nName=Calculator\nExec=gnome-calculator\n",
}


@pytest.fixture
def apps(tmp_path, monkeypatch):
    d = tmp_path / "applications"
    d.mkdir()
    for name, text in DESKTOP.items():
        (d / name).write_text(text)
    monkeypatch.setattr(_apps, "DESKTOP_DIRS", [d])
    monkeypatch.setattr(_apps, "_index", [])
    launched: list[str] = []
    monkeypatch.setattr(_apps, "launch", lambda e: launched.append(e["id"]) or "gtk-launch")
    return launched


@pytest.fixture
def fast_on(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)


# --- registration ---
def test_tools_registered():
    want = {"weather": ("weather", "safe"), "get_time": ("general", "safe"), "open_app": ("apps", "safe"),
            "close_app": ("apps", "safe"), "window": ("windows", "safe"), "remember": ("memory", "safe"),
            "recall": ("memory", "safe"), "forget": ("memory", "confirm")}
    for name, (group, level) in want.items():
        t = registry.get(name)
        assert t is not None and registry.group_of(t) == group and registry.safety_of(t) == level, name


# --- weather / time ---
def test_weather_any_place_with_spelling_fallback_and_cache(http):
    out = weather_mod.weather("Nepalganj")
    # main points only: no humidity/wind, feels-like only when it differs by >= 4 degrees
    assert out == "Nepalgunj, Nepal: 24°C and partly cloudy. Today 18 to 30°C, no rain expected."
    n = len(http)
    assert weather_mod.weather("Nepalganj") == out and len(http) == n  # cached: no new HTTP
    two = weather_mod.weather("Nepalganj", days=2)
    assert "Tomorrow 17 to 28°C, light rain, rain likely (80%)." in two
    assert http[-1][1]["forecast_days"] == 2 and http[-1][1]["latitude"] == 28.05


def test_weather_home_place_and_unknown(http, monkeypatch):
    monkeypatch.setattr(config, "HOME_PLACE", "Kathmandu")
    assert weather_mod.weather().startswith("Kathmandu, Nepal:")
    assert "couldn't find" in weather_mod.weather("Atlantis")
    assert weather_mod.weather("Tokyo", days=9).count(" to ") == 3  # clamped to 3 days


def test_get_time_local_and_world(http):
    assert get_time().startswith("It's ") and not http  # local: no geocoder call
    out = get_time("Tokyo")
    assert out.startswith("It's ") and out.endswith("in Tokyo, Japan.")
    assert "couldn't find" in get_time("Atlantis")


# --- apps ---
def test_open_app_fuzzy_match(apps):
    from jarvis.tools.general.open_app import open_app
    assert open_app("vs code") == "opened Visual Studio Code"
    assert open_app("the Files app") == "opened Files"
    assert open_app("terminal") == "opened Terminal"
    assert open_app("calculater") == "opened Calculator"  # misspelt
    assert apps == ["code", "org.gnome.Nautilus", "org.gnome.Terminal", "org.gnome.Calculator"]
    assert open_app("hidden thing").startswith("error")  # NoDisplay entries are skipped
    assert open_app("youtube") == "opened https://www.youtube.com"  # a site, not an app


def test_launch_falls_back_to_gio(monkeypatch):
    runs: list[list[str]] = []

    class P:
        def __init__(self, argv, **kw):
            runs.append(argv)

        def wait(self, timeout=None):
            return 1  # gtk-launch failed

    monkeypatch.setattr(_apps.shutil, "which", lambda b: f"/usr/bin/{b}")
    monkeypatch.setattr(_apps.subprocess, "Popen", P)
    assert _apps.launch({"id": "x", "path": "/a/x.desktop"}) == "gio"
    assert runs == [["/usr/bin/gtk-launch", "x"], ["/usr/bin/gio", "launch", "/a/x.desktop"]]


def test_close_and_focus_app(apps, monkeypatch):
    wins = [{"id": "0x1", "wmclass": "code.Code", "title": "main.py - Visual Studio Code"},
            {"id": "0x2", "wmclass": "code.Code", "title": "x - Visual Studio Code"},
            {"id": "0x3", "wmclass": "org.gnome.Nautilus.Org.gnome.Nautilus", "title": "Home"}]
    monkeypatch.setattr(_apps, "list_windows", lambda: wins)
    sent: list[list[str]] = []
    monkeypatch.setattr(_apps, "wmctrl", sent.append)
    res = safety.execute("close_app", {"name": "vs code"}, confirm=lambda p: False)  # safe: never asks
    assert res.output == "closed 2 window(s) of Visual Studio Code"
    assert sent == [["-i", "-c", "0x1"], ["-i", "-c", "0x2"]]
    sent.clear()
    assert safety.execute("focus_app", {"name": "files"}).output == "focused Files"
    assert sent == [["-i", "-a", "0x3"]]
    assert "isn't open" in safety.execute("focus_app", {"name": "terminal"}).output


# --- memory ---
def test_remember_recall_forget():
    assert recall() == "You haven't asked me to remember anything yet."
    remember("1234")
    remember("  5678 ")
    assert recall() == "You asked me to remember 2 things: 1) 1234; 2) 5678."
    assert recall("last") == "The last thing you told me to remember: 5678."
    assert recall("search", query="12") == "You asked me to remember 1 thing: 1) 1234."
    assert recall("all", limit=1) == "You asked me to remember 1 thing (the last 1 of 2): 1) 5678."
    assert not safety.execute("forget", {"which": "last"}, confirm=lambda p: False).ok
    assert safety.execute("forget", {"which": "last"}, confirm=lambda p: True).output == "forgot: 5678"
    assert recall("last").endswith("1234.")
    assert safety.execute("forget", {"which": "all"}, confirm=lambda p: True).output == "forgot 1 note(s)"
    assert store.notes_count() == 0


# --- fast path ---
POSITIVE = {
    "what time is it": ("get_time", {}),
    "Hey KURAMA, what's the time?": ("get_time", {}),
    "kati bajyo": ("get_time", {}),
    "what time is it in Tokyo?": ("get_time", {"place": "Tokyo"}),
    "time in New York": ("get_time", {"place": "New York"}),
    "Tokyo ma kati bajyo": ("get_time", {"place": "Tokyo"}),
    "what's the weather in Nepalganj": ("weather", {"place": "Nepalganj", "days": 1}),
    "weather of New York": ("weather", {"place": "New York", "days": 1}),
    "weather": ("weather", {"place": "", "days": 1}),
    "will it rain tomorrow": ("weather", {"place": "", "days": 2}),
    "weather forecast for Pokhara": ("weather", {"place": "Pokhara", "days": 3}),
    "Pokhara ko mausam kasto cha": ("weather", {"place": "Pokhara", "days": 1}),
    "मौसम कस्तो छ": ("weather", {"place": "", "days": 1}),
    "remember 1234": ("remember", {"text": "1234"}),
    "Hey KURAMA, remember 5678.": ("remember", {"text": "5678"}),
    "yaad rakho 4321": ("remember", {"text": "4321"}),
    "what do you remember?": ("recall", {"which": "all"}),
    "what was the last thing I told you to remember?": ("recall", {"which": "last"}),
    "open youtube": ("open_url", {"target": "youtube"}),
    "youtube kholo": ("open_url", {"target": "youtube"}),
    "open vs code": ("open_app", {"name": "VS Code"}),  # mishearing fixes normalise the name
    "launch files": ("open_app", {"name": "files"}),
}
NEGATIVE = ["remember when we went to Pokhara?", "do you remember me", "remember me",
            "what is the weather like for running", "open the door", "open a new tab and play music",
            "time to go", "run tests", "open file report.txt", "what time is my meeting",
            "weather in my head", "tell me a joke", "open my heart", "start the timer"]


def test_fastpath_patterns(apps):
    for text, (tool, args) in POSITIVE.items():
        it = fastpath.match(text)
        assert it is not None and (it.tool, it.args) == (tool, args), text
    for text in NEGATIVE:
        assert fastpath.match(text) is None, text


def test_fastpath_disabled_by_config(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", False)
    assert fastpath.try_answer("remember 1234") is None


@pytest.fixture
def no_llm(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the fast path must not call the LLM")
    monkeypatch.setattr(llm, "model_for", boom)
    monkeypatch.setattr(llm, "chat", boom)


def test_fastpath_hit_makes_zero_llm_calls(fast_on, no_llm, http, apps):
    bot = agent.Agent()
    assert bot.run("Hey KURAMA, remember 1234") == "Okay, I'll remember: 1234."
    assert bot.last["fastpath"] == "remember" and bot.last["route"].method == "fastpath"
    bot.run("remember 5678")
    assert bot.run("what do you remember?") == "You asked me to remember 2 things: 1) 1234; 2) 5678."
    assert bot.run("what was the last thing I told you to remember?").endswith("5678.")
    assert "in Tokyo, Japan." in bot.run("what time is it in Tokyo")
    assert bot.run("weather in Nepalganj").startswith("Nepalgunj, Nepal: 24°C")
    assert bot.run("open youtube") == "Sure, opening youtube."
    assert "".join(bot.stream("open vs code", mode="voice", lang="ne")) == "हुन्छ, Visual Studio Code खोल्दैछु।"
    assert apps == ["code"]
    assert store.tokens_today() == 0
    rows = store.recent_routing(20)
    assert len(rows) == 8 and {r["method"] for r in rows} == {"fastpath"}
    assert len(bot.history) == 2 * config.HISTORY_TURNS  # fast-path turns go into the history too


def test_fastpath_skips_multi_intent(fast_on, no_llm):
    assert planner.is_multi("remember 1234 and open youtube")
    assert agent.Agent()._fast("remember 1234 and open youtube", None, "text") is None
    assert store.notes_count() == 0


def test_unknown_place_falls_through_to_llm(fast_on, http):
    # unknown place: no templated "not found"; the LLM path gets a chance to fix the spelling
    assert fastpath.try_answer("weather in Atlantis") is None
    assert fastpath.match("is it going to rain in Pokhara tomorrow?").args == {"place": "Pokhara", "days": 2}


def test_time_answer_is_short_and_date_only_when_asked():
    out = "It's 1:06 PM on Friday, 23 October 2026 in Tokyo, Japan."
    i = fastpath.Intent("time", "get_time", "general", {"place": "Tokyo"}, "Tokyo")
    assert fastpath.render(i, True, out, "en") == "It's 1:06 PM in Tokyo, Japan."
    assert fastpath.match("what's the date today").args == {"_date": True}
    local = fastpath.Intent("time", "get_time", "general", {"_date": True})
    assert fastpath.render(local, True, "It's 9:05 AM on Friday, 23 October 2026.", "en") == \
        "It's 9:05 AM, Friday, 23 October 2026."


def test_geocode_prefers_named_country(monkeypatch):
    from jarvis.tools.general import _geo
    _geo._geo_cache.clear()
    hits = [{"name": "Jumla", "country": "Elsewhere", "latitude": 1, "longitude": 1, "timezone": "UTC"},
            {"name": "Jumla", "country": "Nepal", "latitude": 29.3, "longitude": 82.2,
             "timezone": "Asia/Kathmandu"}]
    seen = []
    monkeypatch.setattr(_geo, "get_json", lambda url, params: seen.append(params) or {"results": hits})
    g = _geo.geocode("Jumla of Nepal")
    assert g["country"] == "Nepal" and seen[0]["name"] == "Jumla" and seen[0]["count"] == 5
