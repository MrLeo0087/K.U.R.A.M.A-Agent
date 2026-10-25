import json

import pytest

from jarvis.core import fastpath, uiagent as ui


@pytest.mark.parametrize("text,action,n,app", [
    ("new tab", "new_tab", 0, ""), ("open a new tab in brave", "new_tab", 0, "brave"),
    ("close this tab", "close_tab", 0, ""), ("go to the second tab", "tab", 2, ""), ("tab 5", "tab", 5, ""),
    ("switch to 3rd tab", "tab", 3, ""), ("next tab", "next_tab", 0, ""), ("go back", "back", 0, ""),
    ("refresh the page", "reload", 0, ""), ("zoom in", "zoom_in", 0, ""), ("scroll down", "scroll_down", 0, ""),
    ("reopen closed tab", "reopen_tab", 0, ""), ("show hidden files in files", "hidden", 0, "files"),
])
def test_parse_shortcut(text, action, n, app):
    assert ui.parse_shortcut(text) == {"action": action, "n": n, "app": app}


@pytest.mark.parametrize("text", ["back up my projects", "go back to sleep mode", "close chrome", "what's new"])
def test_not_shortcuts(text):
    assert ui.parse_shortcut(text) is None


def test_keys_and_parsers():
    assert ui.keys_from_words("control shift t") == "ctrl+shift+t"
    assert ui.keys_from_words("enter") == "Return" and ui.keys_from_words("f5") == "F5"
    assert ui.keys_from_words("play") is None and ui.keys_from_words("ctrl") is None
    assert ui.parse_press("press ctrl t") == {"keys": "ctrl t", "app": ""}
    assert ui.parse_type("type hello world") == {"text": "hello world", "app": ""}
    assert ui.parse_click("click on the Wi-Fi button")["name"] == "Wi-Fi"
    assert ui.parse_click("click a photo") is None


def test_fastpath_routes_to_app_control():
    i = fastpath.match("go to the second tab")
    assert i.tool == "app_control" and i.args["text"] == "tab:2"
    assert fastpath.match("click Bluetooth").args == {"action": "click", "text": "Bluetooth", "app": ""}


ITEMS = [{"role": "push button", "name": "Wi-Fi", "x": 10, "y": 10, "w": 20, "h": 20, "state": ""},
         {"role": "toggle button", "name": "Dark Style", "x": 100, "y": 50, "w": 40, "h": 20, "state": ""},
         {"role": "push button", "name": "Delete Account", "x": 100, "y": 90, "w": 40, "h": 20, "state": ""}]


def test_find_fuzzy():
    assert ui.find(ITEMS, "wifi")["name"] == "Wi-Fi"
    assert ui.find(ITEMS, "dark style")["name"] == "Dark Style"
    assert ui.find(ITEMS, "bluetooth") is None


@pytest.fixture
def fake(monkeypatch):
    calls, kv = [], {}
    monkeypatch.setattr(ui, "_need", lambda: None)
    monkeypatch.setattr(ui, "_x", lambda *a, **k: calls.append(a) or "")
    monkeypatch.setattr(ui, "active_class", lambda: "brave-browser")
    monkeypatch.setattr(ui, "snapshot", lambda app="": {"app": "x", "window": "w", "items": ITEMS})
    monkeypatch.setattr(ui.time, "sleep", lambda s: None)
    monkeypatch.setattr(ui.store, "kv_get", lambda k, d=None: kv.get(k, d))
    monkeypatch.setattr(ui.store, "kv_set", lambda k, v: kv.__setitem__(k, v))
    monkeypatch.setattr(ui.store, "kv_delete", lambda k: kv.pop(k, None))
    return calls, kv


def test_shortcut_keys_per_app(fake):
    calls, _ = fake
    ui.shortcut("tab", 2)
    ui.shortcut("new_tab")
    assert ("key", "--clearmodifiers", "ctrl+2") in calls and ("key", "--clearmodifiers", "ctrl+t") in calls


def test_click_name_and_risky_confirm(fake, monkeypatch):
    calls, _ = fake
    assert ui.click_name("wifi") == "Clicked Wi-Fi."
    assert calls[-1][:3] == ("mousemove", "--sync", "20")
    from jarvis.core import safety
    monkeypatch.setattr(safety, "ask", lambda p: False)
    assert "didn't click" in ui.click_name("delete account")


def test_run_task_learns_then_replays_free(fake, monkeypatch):
    calls, kv = fake
    from jarvis.core import llm
    steps = iter([ui.Step(action="click", item=-2), ui.Step(action="done", say="Dark style is on.")])
    seen = []

    def plan(msgs, schema, **k):
        seen.append(msgs[1]["content"])
        s = next(steps)
        if s.action == "click":  # pick the item the listing numbered "Dark Style"
            line = next(l for l in msgs[1]["content"].splitlines() if "Dark Style" in l)
            s.item = int(line.split("|")[0])
        return s
    monkeypatch.setattr(llm, "structured", plan)
    assert ui.run_task("turn on dark style") == "Dark style is on."
    assert len(seen) == 2 and any(k.startswith("uimacro:browser:") for k in kv)
    monkeypatch.setattr(llm, "structured", lambda *a, **k: pytest.fail("replay must not call the LLM"))
    calls.clear()
    assert "0 tokens" in ui.run_task("turn on dark style")
    assert any(c[0] == "mousemove" for c in calls)


def test_tool_dispatch(fake):
    from jarvis.tools.general.app_control import app_control
    fn = getattr(app_control, "func", app_control)
    assert fn("shortcut", "tab:3") == "Switched to tab 3."
    assert fn("press", "ctrl t") == "Pressed ctrl+t."
    assert fn("type", "hello") == "Typed it."


def test_enable_phrase():
    assert fastpath.match("enable screen control").args == {"action": "enable"}
