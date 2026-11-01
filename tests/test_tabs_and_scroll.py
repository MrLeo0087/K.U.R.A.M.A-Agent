"""Browser tabs by name (extension 1.3 reports every tab), scrolling by meaning, keys to the user's window."""
import pytest

from jarvis.core import browsertab, fastpath, semantic, uiagent
from jarvis.tools.general import app_control

TABS = [{"i": 1, "title": "GitHub - MrLeo0087", "url": "https://github.com/MrLeo0087"},
        {"i": 2, "title": "(3) Facebook", "url": "https://www.facebook.com/"},
        {"i": 3, "title": "YouTube", "url": "https://www.youtube.com/watch?v=x"},
        {"i": 4, "title": "ChatGPT", "url": "https://chatgpt.com/c/1"}]


@pytest.fixture
def desk(monkeypatch):
    browsertab.put("https://github.com/MrLeo0087", "GitHub", "brave", TABS)
    pressed = []
    monkeypatch.setattr(uiagent, "_need", lambda: None)
    monkeypatch.setattr(uiagent, "to_user_window", lambda: None)
    monkeypatch.setattr(uiagent, "active_class", lambda: "brave-browser")
    monkeypatch.setattr(uiagent, "_x", lambda *a, **k: pressed.append(a) or "")
    return pressed


@pytest.mark.parametrize("name,i", [("facebook", 2), ("fb", None), ("you tube", 3), ("chat gpt", 4), ("github", 1)])
def test_find_tab_by_site_or_title(desk, name, i):
    t = browsertab.find_tab(name)
    assert (t["i"] if t else None) == i


@pytest.mark.parametrize("text,keys", [("tab:facebook", "ctrl+2"), ("tab:youtube", "ctrl+3"), ("close_tab:chatgpt", "ctrl+w")])
def test_switch_and_close_tabs_by_name(desk, text, keys):
    out = app_control.app_control("shortcut", text)
    assert out.startswith(("Switched to", "Closed")) and ("key", "--clearmodifiers", keys) in desk


def test_list_tabs_and_unknown_tab(desk):
    assert app_control.app_control("shortcut", "tabs").startswith("4 tabs open:\n1. GitHub")
    assert app_control.app_control("shortcut", "tab:instagram").startswith("No open tab matches 'instagram'")


@pytest.mark.parametrize("text,times", [("scroll_down:1", 1), ("scroll_down:3", 3), ("scroll_up:3", 3)])
def test_scroll_amounts(desk, text, times):
    app_control.app_control("shortcut", text)
    assert sum(1 for a in desk if a[0] == "key") == times


@pytest.mark.parametrize("text,label,arg", [("scroll down bro", "scroll_down", "scroll_down:1"),
                                            ("scroll down a lot", "scroll_down", "scroll_down:3"),
                                            ("scroll up more pls", "scroll_up", "scroll_up:3"),
                                            ("switch to the facebook tab", "switch_tab", "tab:facebook"),
                                            ("close the facebook tab", "close_tab", "close_tab:facebook"),
                                            ("what tabs are open", "list_tabs", "tabs")])
def test_by_meaning(monkeypatch, text, label, arg):
    monkeypatch.setattr(semantic, "ready", lambda: True)
    monkeypatch.setattr(semantic, "best_of", lambda t, name, table: (label, 0.95))
    monkeypatch.setattr(semantic, "scores", lambda t: [(semantic.CHAT, 0.5)])
    monkeypatch.setattr(fastpath, "meaning_ok", lambda t, it: True)
    assert fastpath.meaning_intent(text).args["text"] == arg


def test_keys_go_below_kuramas_own_window(monkeypatch):
    from jarvis.core import rewrite
    sent = []
    monkeypatch.setattr(rewrite, "target_window", lambda: (4242, False))  # KURAMA's chat is in front
    monkeypatch.setattr(uiagent, "_x", lambda *a, **k: sent.append(a) or "")
    uiagent.key("Page_Down")
    assert sent[0] == ("windowactivate", "--sync", "4242") and sent[-1][-1] == "Page_Down"
