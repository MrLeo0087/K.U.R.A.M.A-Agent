"""Day-to-day tools + gesture control + day summary phrases (all mocked, no network/camera)."""
from __future__ import annotations

from jarvis.core import config, fastpath
from jarvis.tools.general import calculate as calc_mod
from jarvis.tools.general import convert_currency as cur_mod
from jarvis.tools.general import gesture_control as gest_mod
from jarvis.tools.general import news_headlines as news_mod


def test_calculate_math_and_units():
    assert calc_mod.calculate("18% of 2500") == "18% of 2500 = 450"
    assert calc_mod.calculate("10 km to miles").startswith("10 km = 6.21")
    assert "error" in calc_mod.calculate("__import__('os')")


def test_currency(monkeypatch):
    monkeypatch.setattr(cur_mod, "rates", lambda base: {"NPR": 150.0})
    assert cur_mod.convert_currency(2, "dollars", "rupees") == "2.00 USD = 300.00 NPR (rate 150)"


def test_news(monkeypatch):
    rss = ("<rss><channel><item><title>Big win - BBC</title><source>BBC</source></item>"
           "<item><title>Rain</title></item></channel></rss>")
    monkeypatch.setattr(news_mod, "fetch_rss", lambda url: rss)
    news_mod._cache.clear()
    out = news_mod.news_headlines("cricket", 2)
    assert "- Big win (BBC)" in out and "- Rain" in out


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
                       ("what is 18% of 2500", "calculate"), ("latest news about cricket", "news_headlines")]:
        it = fastpath.match(text)
        assert it is not None and it.tool == tool, text


def test_gesture_mishearings():
    for text in ("Can you enable the Media Adjector Control System?", "Enable the YouTube Media Controller.",
                 "Can you enable the hand jigsaw system?", "Can you enable the Jaxxor control system?",
                 "enabel geauster control system"):
        it = fastpath.match(text)
        assert it is not None and (it.tool, it.args) == ("gesture_control", {"action": "on"}), text
    assert fastpath.match("Wariyo").tool == "about_me"
