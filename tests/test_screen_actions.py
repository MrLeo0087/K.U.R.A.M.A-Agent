"""Traces 11-01 09:35: 'Close or open app and go to home screen' was answered 'you're now on the home screen' with no
tool (there was no such action); 'Open setting.' took the AI (1.7 s) because the meaning gate judged the WORD
'settings' (window settings) instead of the action 'open <an installed app>'."""
import pytest

from jarvis.core import fastpath, meta, semantic
from jarvis.tools.general import _sys, window


def test_desktop_minimizes_everything_and_undesktop_brings_back(monkeypatch):
    ran = []
    monkeypatch.setattr(_sys, "run", lambda argv, **k: ran.append(argv) or "")
    assert window.window("desktop").startswith("Showing the desktop") and ran[-1] == ["wmctrl", "-k", "on"]
    assert window.window("undesktop") == "Windows are back." and ran[-1] == ["wmctrl", "-k", "off"]


@pytest.mark.parametrize("answer", ["All apps are closed and you’re now on the home screen.",
                                    "Opening https://nepalgon.com.", "The second tab is now active.",
                                    "The window was minimized."])
def test_claims_of_screen_actions_need_a_tool(answer):
    assert meta.needs_tool(answer)


@pytest.mark.parametrize("text", ["go to home screen", "take me to home screen bro", "show desktop"])
def test_home_screen_by_meaning(monkeypatch, text):
    monkeypatch.setattr(semantic, "ready", lambda: True)
    monkeypatch.setattr(semantic, "best_of", lambda t, name, table: ("show_desktop", 0.95))
    monkeypatch.setattr(semantic, "scores", lambda t: [(semantic.CHAT, 0.5)])
    monkeypatch.setattr(fastpath, "meaning_ok", lambda t, it: True)
    assert fastpath.meaning_intent(text).args == {"action": "desktop"}


def test_home_screen_needs_more_certainty(monkeypatch):
    monkeypatch.setattr(semantic, "ready", lambda: True)
    monkeypatch.setattr(semantic, "best_of", lambda t, name, table: ("show_desktop", 0.86))  # 'show my screen'
    monkeypatch.setattr(semantic, "scores", lambda t: [(semantic.CHAT, 0.5)])
    assert fastpath.meaning_intent("show my screen") is None


@pytest.mark.parametrize("text,known", [("Open setting.", "setting"), ("launch telegram", "telegram"),
                                        ("open settings bro", "settings")])
def test_gate_judges_the_action_not_the_checked_name(monkeypatch, text, known):
    seen = []
    monkeypatch.setattr(semantic, "ready", lambda: True)
    monkeypatch.setattr(semantic, "scores", lambda t: seen.append(t) or [("apps", 0.9), ("windows", 0.8)])
    it = fastpath.Intent("open", "open_app", "apps", {"name": known}, known, known=known)
    assert fastpath.meaning_ok(text, it) and known not in seen[-1].lower() and "X" in seen[-1]
