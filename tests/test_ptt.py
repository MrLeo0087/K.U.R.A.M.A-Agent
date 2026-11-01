"""Hold-to-talk key logic (jarvis/core/ptt.py): no keyboard, no window, fake clock and timer."""
import pytest

from jarvis.core import ptt


class FakeTimer:
    def __init__(self, fn):
        self.fn, self.cancelled = fn, False

    def cancel(self):
        self.cancelled = True


def make(combo="ctrl+space"):
    told, t, timers = [], [0.0], []

    def schedule(_delay, fn):
        timers.append(FakeTimer(fn))
        return timers[-1]
    h = ptt.Holder(combo, tell=told.append, now=lambda: t[0], min_hold=0.35, schedule=schedule)
    return h, told, t, timers


def fire(timers):
    for tm in timers:
        if not tm.cancelled:
            tm.cancelled = True
            tm.fn()


def test_ctrl_space_hold_with_autorepeat_then_release():
    h, told, t, timers = make()
    h.press("ctrl_l"); h.press("space")
    for _ in range(5):  # X11 auto-repeat: release + press pairs while held
        h.release("space"); h.press("space")
    assert told == ["down"]
    t[0] = 1.2; h.release("space"); fire(timers)
    assert told == ["down", "up"]


def test_releasing_ctrl_ends_at_once_and_either_ctrl_counts():
    h, told, t, _ = make()
    h.press("ctrl_r"); h.press("space"); t[0] = 1.0; h.release("ctrl_r")
    assert told == ["down", "up"]


def test_space_without_ctrl_short_tap_and_shortcut():
    h, told, t, timers = make()
    h.press("space"); h.release("space")
    assert told == []
    h.press("ctrl"); h.press("space"); t[0] = 0.1; h.release("ctrl")
    assert told == ["down", "cancel"]
    told.clear(); t[0] = 0
    h.press("ctrl"); h.press("space"); h.press("c"); t[0] = 2; h.release("ctrl")
    assert told == ["down", "cancel"]


def test_single_key_still_works():
    h, told, t, timers = make("ctrl_r")  # one modifier alone: listens after the start delay
    h.press("ctrl_r"); t[0] = 0.3; fire(timers); t[0] = 1; h.release("ctrl_r")
    assert told == ["down", "up"]


def test_super_z():
    h, told, t, timers = make("super+z")
    h.press("cmd"); h.press("z"); h.release("z"); h.press("z")  # auto-repeat
    t[0] = 1; h.release("cmd")
    assert told == ["down", "up"]


def test_dismiss_and_fast_repeats():
    told, t, timers = [], [0.0], []
    h = ptt.Holder("super+z", tell=told.append, now=lambda: t[0], min_hold=0.35,
                   schedule=lambda d, fn: timers.append(FakeTimer(fn)) or timers[-1], dismiss="super+x")
    h.press("cmd"); h.press("x"); h.press("x"); h.release("x"); h.release("cmd")  # repeat: one dismiss
    assert told == ["dismiss"]
    told.clear()
    for _ in range(3):  # quick taps: each down ends in a cancel, never a stuck "down"
        h.press("cmd"); h.press("z"); t[0] += 0.1; h.release("cmd")
    assert told == ["down", "cancel"] * 3


def solo():
    told, t, timers = [], [0.0], []
    h = ptt.Holder("ctrl_l", tell=told.append, now=lambda: t[0], min_hold=0.0,
                   schedule=lambda d, fn: timers.append(FakeTimer(fn)) or timers[-1], dismiss="double")
    return h, told, t, timers


def test_left_ctrl_hold_talks_after_delay():
    h, told, t, timers = solo()
    h.press("ctrl_l"); t[0] = 0.3; fire(timers)
    assert told == ["down"]
    t[0] = 2; h.release("ctrl_l")
    assert told == ["down", "up"]


def test_ctrl_shortcut_never_listens():
    h, told, t, timers = solo()
    h.press("ctrl_l"); h.press("c"); fire(timers); t[0] = 1; h.release("c"); h.release("ctrl_l")
    assert told == []


def test_double_tap_dismisses_single_tap_does_nothing():
    h, told, t, timers = solo()
    h.press("ctrl_l"); t[0] = 0.1; h.release("ctrl_l")
    assert told == []
    t[0] = 0.3; h.press("ctrl_l"); t[0] = 0.4; h.release("ctrl_l")
    assert told == ["dismiss"]
    t[0] = 5; h.press("ctrl_l"); t[0] = 5.1; h.release("ctrl_l")  # a lone tap later: nothing
    assert told == ["dismiss"]


def test_either_shift_talks_and_double_tap_dismisses():
    told, t, timers = [], [0.0], []
    h = ptt.Holder("shift", tell=told.append, now=lambda: t[0], min_hold=0.0,
                   schedule=lambda d, fn: timers.append(FakeTimer(fn)) or timers[-1], dismiss="double")
    h.press("shift_r"); t[0] = 0.3; fire(timers); t[0] = 1; h.release("shift_r")
    h.press("shift"); h.press("a"); fire(timers); h.release("a"); h.release("shift")  # typing a capital A
    t[0] = 3; h.press("shift_l"); t[0] = 3.1; h.release("shift_l"); h.press("shift_r"); t[0] = 3.2; h.release("shift_r")
    assert told == ["down", "up", "dismiss"]


def test_settings_file_wins_and_bad_combos_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(ptt, "SETTINGS_FILE", tmp_path / "ptt.json")
    monkeypatch.setattr(ptt, "start", lambda: True)
    monkeypatch.setattr(ptt, "stop", lambda: None)
    assert ptt.apply("rm -rf", "double")["ok"] is False
    r = ptt.apply("Super+Z", "super+x")
    assert r["ok"] and ptt.settings()["key"] == "super+z" and ptt.settings()["dismiss"] == "super+x"


def test_ctrl_talks_double_shift_dismisses():
    told, t, timers = [], [0.0], []
    h = ptt.Holder("ctrl", tell=told.append, now=lambda: t[0], min_hold=0.0,
                   schedule=lambda d, fn: timers.append(FakeTimer(fn)) or timers[-1], dismiss="double:shift")
    h.press("ctrl_l"); t[0] = 0.3; fire(timers); t[0] = 1; h.release("ctrl_l")
    t[0] = 2; h.press("shift"); t[0] = 2.1; h.release("shift"); h.press("shift_r"); t[0] = 2.2; h.release("shift_r")
    t[0] = 4; h.press("shift"); h.press("a"); h.release("a"); h.release("shift")  # capital letters: nothing
    h.press("shift"); t[0] = 4.1; h.release("shift")
    assert told == ["down", "up", "dismiss"]


@pytest.mark.parametrize("key", ["alt_l", "alt_r", "alt"])
def test_alt_held_alone_talks_alt_shortcuts_never_do(key):
    """Owner 11-01: talk on a long Alt (Ctrl is busy with shortcuts). Alt+Tab / Alt+F4 / a quick tap: nothing."""
    told, t, timers = [], [0.0], []
    h = ptt.Holder("alt", tell=told.append, now=lambda: t[0], min_hold=0.0,
                   schedule=lambda d, fn: timers.append(FakeTimer(fn)) or timers[-1], dismiss="double:shift")
    h.press(key); t[0] = 0.3; fire(timers); t[0] = 1.5; h.release(key)          # long Alt: talk
    t[0] = 3; h.press(key); h.press("tab"); h.release("tab"); t[0] = 3.6; fire(timers); h.release(key)  # Alt+Tab
    t[0] = 5; h.press(key); h.press("f4"); h.release("f4"); h.release(key)        # Alt+F4
    t[0] = 7; h.press(key); t[0] = 7.1; h.release(key)                            # a quick tap
    assert told == ["down", "up"]


@pytest.mark.parametrize("other", ["shift", "shift_r", "esc"])
def test_alt_then_shift_cancels_while_listening(other):
    """Owner 11-01: a mistaken long Alt is cancelled by pressing Shift (any other key) while still holding Alt;
    letting go of Alt afterwards sends nothing."""
    told, t, timers = [], [0.0], []
    h = ptt.Holder("alt", tell=told.append, now=lambda: t[0], min_hold=0.0,
                   schedule=lambda d, fn: timers.append(FakeTimer(fn)) or timers[-1], dismiss="double:shift")
    h.press("alt_l"); t[0] = 0.3; fire(timers); t[0] = 2.0
    h.press(other); h.release(other); t[0] = 2.5; h.release("alt_l")
    assert told == ["down", "cancel"]


@pytest.mark.parametrize("first", ["ctrl_l", "shift", "ctrl_r"])
def test_alt_after_another_key_never_talks(first):
    """Ctrl+Alt+L (and Shift+Alt...): Alt pressed while another key is down is a shortcut, never a hold-to-talk."""
    told, t, timers = [], [0.0], []
    h = ptt.Holder("alt", tell=told.append, now=lambda: t[0], min_hold=0.0,
                   schedule=lambda d, fn: timers.append(FakeTimer(fn)) or timers[-1], dismiss="double:shift")
    h.press(first); h.press("alt_l"); t[0] = 0.5; fire(timers); h.press("l"); h.release("l"); h.release("alt_l")
    h.release(first)
    t[0] = 20; h.press("alt_l"); t[0] = 20.4; fire(timers); t[0] = 21; h.release("alt_l")  # alone again: talks
    assert told == ["down", "up"]
