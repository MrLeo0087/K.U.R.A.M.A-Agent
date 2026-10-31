"""Hold-to-talk key logic (jarvis/core/ptt.py): no keyboard, no window, fake clock and timer."""
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
