"""KURAMA about itself: its safe settings (set / range / undo / reset), tool cards built from the code, explaining
its last action from the real record (the AI is mocked), help and "can you" by meaning."""
from __future__ import annotations

import json

import pytest

from jarvis.core import config, registry, selfindex, usersettings


@pytest.fixture(autouse=True)
def _defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    for s in usersettings.SETTINGS:  # every test starts from config.py's values, and restores them
        monkeypatch.setattr(config, s.key, getattr(config, s.key))
    monkeypatch.setattr(config, "SETTING_DEFAULTS", {})


def test_set_checks_range_units_and_saves():
    out = usersettings.set_value("speed test seconds", "30 seconds")
    assert out.startswith("Done: speed test seconds is now 30 seconds (was 15 seconds)") and config.SPEEDTEST_SECONDS == 30
    assert json.loads((config.DATA_DIR / "user_settings.json").read_text())["values"]["SPEEDTEST_SECONDS"] == 30
    assert usersettings.set_value("speed test seconds", "1 minute").startswith("Done") and config.SPEEDTEST_SECONDS == 60
    assert usersettings.set_value("speed test seconds", "500").startswith("error: speed test seconds goes from 5 to 60")
    assert usersettings.set_value("weather cache minutes", "20 minutes") and config.WEATHER_CACHE_S == 1200
    assert usersettings.set_value("daily summary time", "9 PM") and config.DIGEST_TIME == "21:00"
    assert usersettings.set_value("speaking speed", "+30%") and config.TTS_RATE == "+30%"
    assert usersettings.set_value("the moon", "3").startswith("error: 'the moon' isn't a setting")


def test_undo_reset_and_listing():
    usersettings.set_value("ram alert percent", "80")
    assert usersettings.undo().startswith("Undone: ram alert percent is 90 % again") and config.RAM_ALERT_PCT == 90
    usersettings.set_value("reply length", "600")
    assert "reply length" in usersettings.reset("all") and config.AGENT_MAX_TOKENS == 400
    text = usersettings.listing()
    assert "speed test seconds: 15 seconds" in text and len(text.splitlines()) == len(usersettings.SETTINGS) + 1


def test_the_speed_test_reads_the_setting(monkeypatch):
    from jarvis.core import netdoctor
    import inspect
    assert "config.SPEEDTEST_SECONDS" in inspect.getsource(netdoctor.speed)


def test_every_tool_has_a_card_from_its_code():
    registry.REGISTRY.discover()
    bad = [n for n in registry.REGISTRY.tools if not ((c := selfindex.card(n)) and len(c.how) >= 15 and c.what)]
    assert not bad, bad
    c = selfindex.card("internet_doctor")
    assert "speed test seconds" in c.settings and "Cloudflare" in c.text()


def test_explain_uses_the_real_last_request(monkeypatch):
    from jarvis.core import llm
    from jarvis.tools.general import explain_self as ex
    last = {"id": "abc123", "text": "what is my internet speed", "answer": "Download 55 Mbps, upload 10 Mbps",
            "tools": json.dumps([{"name": "internet_doctor", "args": {"action": "speed"}, "result": "Download 55 Mbps"}])}
    monkeypatch.setattr(ex, "_last_request", lambda max_age_s=1800: last)
    monkeypatch.setattr(selfindex, "by_meaning", lambda text, k=3: [])
    seen = {}

    class R:
        text = "I download from Cloudflare's test server for about 8 seconds."

    def fake_chat(messages, **kw):
        seen["facts"] = messages[1]["content"]
        seen["kw"] = kw
        return R()
    monkeypatch.setattr(llm, "chat", fake_chat)
    out = ex.explain_self("how did you measure that?")
    assert out.startswith("I download from Cloudflare")
    assert 'LAST REQUEST: "what is my internet speed"' in seen["facts"] and "DID: " in seen["facts"]
    assert "internet_doctor" not in seen["facts"]  # no internal names in what the answer is built from
    assert "speed test seconds = 15 seconds" in seen["facts"] and seen["kw"]["tier"] == "smart"
    assert seen["kw"]["max_tokens"] <= 700


def test_the_hub_reaches_settings_explain_and_help():
    from jarvis.tools.core import kurama
    assert kurama._settings_args("set speed test seconds to 30") == {"action": "set", "name": "speed test seconds",
                                                                     "value": "30"}
    assert kurama._settings_args("undo") == {"action": "undo"} and kurama._settings_args("") == {"action": "list"}
    assert kurama._settings_args("reset") == {"action": "reset", "name": "all"}
    assert {"settings", "explain", "help"} <= set(kurama.TABLE)


def test_help_lists_areas_with_real_examples():
    from jarvis.tools.general import help_me
    out = help_me.help_me("")
    assert out.startswith("What I can do") and "when I say" in out and out.count("\n- ") >= 5


def test_a_length_in_the_request_is_for_that_test_only(monkeypatch):
    """'run the speed test with 30 seconds' = this test only; 'make it permanent' then keeps it."""
    from jarvis.core import netdoctor, store
    from jarvis.tools.general import internet_doctor as tool
    ran = []
    monkeypatch.setattr(netdoctor, "speed", lambda total=None: ran.append(total) or "Download 50 Mbps")
    out = tool.internet_doctor("speed", seconds=30)
    assert ran == [30] and "this time only" in out and config.SPEEDTEST_SECONDS == 15  # the setting is unchanged
    assert usersettings.keep_once().startswith("Done: speed test seconds is now 30 seconds")
    assert config.SPEEDTEST_SECONDS == 30 and usersettings.keep_once().startswith("There's no one-time setting")
    assert store.kv_get("setting_once") is None


def test_capability_answers_in_plain_words(monkeypatch):
    from jarvis.tools.general import find_capability as fc

    class C:
        def __init__(self, what, say):
            self.name, self.group, self.what, self.say = "x", "files", what, say
    monkeypatch.setattr(selfindex, "by_meaning", lambda text, k=3: [C("Convert files locally.", ["change this pdf to word"])])
    out = fc.find_capability("convert pdf to md")
    assert out.startswith("Yes, I can help with that: Convert files locally.") and "x (files)" not in out
