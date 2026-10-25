"""Day-to-day tools + gesture control + day summary phrases (all mocked, no network/camera)."""
from __future__ import annotations

from jarvis.core import config, fastpath
from jarvis.tools.general import calculate as calc_mod
from jarvis.tools.general import convert_currency as cur_mod
from jarvis.tools.general import gesture_control as gest_mod


def test_calculate_math_and_units():
    assert calc_mod.calculate("18% of 2500") == "18% of 2500 = 450"
    assert calc_mod.calculate("10 km to miles").startswith("10 km = 6.21")
    assert "error" in calc_mod.calculate("__import__('os')")


def test_currency(monkeypatch):
    monkeypatch.setattr(cur_mod, "rates", lambda base: {"NPR": 150.0})
    assert cur_mod.convert_currency(2, "dollars", "rupees") == "2.00 USD = 300.00 NPR (rate 150)"


def test_gesture_start_stop(monkeypatch, tmp_path):
    (tmp_path / "main.py").write_text("print('hi')")
    monkeypatch.setattr(config, "GESTURE_DIR", tmp_path)
    monkeypatch.setattr(config, "VISION_PYTHON", "/bin/sh")
    monkeypatch.setattr(gest_mod, "PID_FILE", tmp_path / "g.pid")
    started = []

    class P:
        pid = 999999

    monkeypatch.setattr(gest_mod.subprocess, "Popen", lambda *a, **k: started.append(a) or P())
    assert "is on" in gest_mod.gesture_control("on") and started
    assert "isn't running" in gest_mod.gesture_control("off")  # fake pid isn't alive


def test_fastpath_phrases(monkeypatch):
    for text, tool in [("enable the media control through hand", "gesture_control"),
                       ("summarize the today day", "daily_digest"), ("what did we do today", "daily_digest"),
                       ("what is 18% of 2500", "calculate"), ("latest news about cricket", "live_search")]:
        it = fastpath.match(text)
        assert it is not None and it.tool == tool, text


def test_gesture_mishearings():
    for text in ("Can you enable the Media Adjector Control System?", "Enable the YouTube Media Controller.",
                 "Can you enable the hand jigsaw system?", "Can you enable the Jaxxor control system?",
                 "enabel geauster control system"):
        it = fastpath.match(text)
        assert it is not None and (it.tool, it.args) == ("gesture_control", {"action": "on"}), text
    assert fastpath.match("Wariyo").tool == "about_me"


def test_close_app_phrases():
    it = fastpath.match("Close the camera of my laptop.")
    assert it is not None and (it.tool, it.args) == ("close_app", {"name": "camera"})
    assert fastpath.render(it, True, "closed 1 window(s) of Cheese", "en") == "Done, I closed camera."
    assert fastpath.render(it, True, "no open window matches 'camera'", "en") == "Camera isn't open."
    assert fastpath.match("Disable the handset system.").args == {"action": "off"}
    for text in ("close the door", "close all windows"):
        assert fastpath.match(text) is None, text
    assert fastpath.match("close the tab").tool == "app_control"  # a browser-tab shortcut, not close_app("tab")


def test_fastpath_common_misses():
    cases = {"Take the screenshot of my display.": ("screenshot", {"mode": "full"}),
             "Sit the brightness at 1%.": ("brightness", {"action": "set", "level": 1}),
             "Start or stopwatch now.": ("stopwatch", {"action": "start"}),
             "open the file manager": ("open_app", {"name": "file manager"}),
             "switch off the laptop": ("power_off", {"action": "shutdown"})}
    for text, want in cases.items():
        it = fastpath.match(text)
        assert it is not None and (it.tool, it.args) == want, text
    it = fastpath.match("set remiander for 11:58 PM of today for reading book")
    assert it.tool == "add_reminder" and it.args["text"] == "reading book"
    assert fastpath.match("Also set the reminder for tomorrow 6 am for walking.").args["text"] == "walking"


def test_time_and_weather_together(monkeypatch):
    for t in ("What is the time in the weather right now?", "what is the time and weather right now",
              "What is the time and order right now in Nepal"):
        i = fastpath.match(t)
        assert (i.tool, i.args) == ("weather", {"place": "", "days": 1, "_time": True}), t
    assert fastpath.match("what is the time in tokyo").args == {"place": "tokyo"}
    from jarvis.tools.general import echo_time
    monkeypatch.setattr(echo_time, "get_time", lambda place="": "It is 8:55 PM, Sunday, 25 October 2026")
    out = fastpath.render(fastpath.match("time and weather"), True, "Kathmandu: 18°C, clear", "en")
    assert "Kathmandu: 18°C" in out and "PM" in out
