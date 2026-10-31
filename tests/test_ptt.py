"""Hold-to-talk key logic (jarvis/core/ptt.py): no keyboard, no window, fake clock."""
from jarvis.core import ptt


def make():
    told, t = [], [0.0]
    h = ptt.Holder("ctrl_r", tell=told.append, now=lambda: t[0], min_hold=0.35)
    return h, told, t


def test_hold_and_release_sends():
    h, told, t = make()
    h.press("ctrl_r"); t[0] = 0.2; h.press("ctrl_r")  # X11 key repeat: still one "down"
    t[0] = 1.5; h.release("ctrl_r")
    assert told == ["down", "up"]


def test_short_tap_and_shortcut_cancel():
    h, told, t = make()
    h.press("ctrl_r"); t[0] = 0.1; h.release("ctrl_r")
    assert told == ["down", "cancel"]
    told.clear()
    h.press("ctrl_r"); h.press("c"); t[0] = 2; h.release("ctrl_r")  # Right Ctrl + C = copy, not talking
    assert told == ["down", "cancel"]


def test_other_keys_alone_do_nothing():
    h, told, _ = make()
    h.press("a"); h.release("a"); h.release("ctrl_r")
    assert told == []
