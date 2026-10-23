import pytest

from jarvis.core import config, hotkey


def test_parse_hotkey():
    assert hotkey.parse_hotkey("<ctrl>+<alt>+j") == "<ctrl>+<alt>+j"
    assert hotkey.parse_hotkey("Ctrl + Alt + J") == "<ctrl>+<alt>+j"
    assert hotkey.parse_hotkey("super+shift+space") == "<cmd>+<shift>+<space>"
    assert hotkey.parse_hotkey("F9") == "<f9>"
    assert hotkey.pretty(config.HOTKEY_PTT) == "Ctrl+Alt+J"
    for bad in ("", "ctrl+alt", "j", "ctrl+foo", "ctrl+ctrl+j", "ctrl+a+b", "ctrl++j"):
        with pytest.raises(hotkey.HotkeyError):
            hotkey.parse_hotkey(bad)


def test_listener_registers_callback(monkeypatch):
    import sys
    import types

    seen = {}

    class FakeGHK:
        def __init__(self, mapping):
            seen["mapping"] = mapping

        def start(self):
            seen["started"] = True

        def stop(self):
            seen["stopped"] = True

    fake = types.ModuleType("pynput")
    fake.keyboard = types.SimpleNamespace(GlobalHotKeys=FakeGHK)
    monkeypatch.setitem(sys.modules, "pynput", fake)
    monkeypatch.setenv("DISPLAY", ":0")
    hits = []
    hl = hotkey.HotkeyListener("ctrl+alt+j", lambda: hits.append(1)).start()
    seen["mapping"]["<ctrl>+<alt>+j"]()
    hl.stop()
    assert hits == [1] and seen["started"] and seen["stopped"]
    monkeypatch.delenv("DISPLAY")
    with pytest.raises(hotkey.HotkeyError):
        hotkey.HotkeyListener().start()
