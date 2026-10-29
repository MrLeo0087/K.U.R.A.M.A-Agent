import time

from jarvis.core import config, safety
from jarvis.tools.general import _sys


def test_a_slow_yes_is_never_turned_into_a_background_decline(monkeypatch):
    """'shutdown' through the laptop tool: the user takes longer than the background threshold to click Yes.
    It must still run in this turn (not move to a background job whose yes/no then counts as declined)."""
    monkeypatch.setattr(config, "TOOL_BACKGROUND_AFTER_S", 0.5)
    ran = []
    monkeypatch.setattr(_sys, "run", lambda argv, **k: ran.append(argv) or "")

    def slow_yes(prompt):
        time.sleep(1.5)  # three times the threshold
        return True
    res = safety.execute("laptop", {"action": "shutdown"}, confirm=slow_yes, ctx={"jobs": [], "user_text": "shutdown"})
    assert res.ok and "background" not in res.output and ran == [["systemctl", "poweroff"]]
    assert not safety.asking_now()


def test_no_runs_nothing(monkeypatch):
    ran = []
    monkeypatch.setattr(_sys, "run", lambda argv, **k: ran.append(argv) or "")
    res = safety.execute("power_off", {"action": "shutdown"}, confirm=lambda p: False, ctx={"jobs": []})
    assert "declined" in res.output and ran == []


def test_power_commands_can_never_run_in_tests_even_after_a_mock_is_gone():
    for argv in (["systemctl", "poweroff"], ["systemctl", "reboot"], ["systemctl", "suspend"],
                 ["loginctl", "terminate-session", "1"], ["shutdown", "now"], ["/usr/bin/gnome-session-quit"]):
        assert _sys.power_blocked(argv), argv
    assert not _sys.power_blocked(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "50%"])


def test_everyday_laptop_commands_are_instant_even_with_typos():
    from jarvis.core import fastpath
    for t, tool in (("hutodwn", "power_off"), ("shutodwn", "power_off"), ("shutdown laptop", "power_off"),
                    ("please shut down the computer", "power_off"), ("restrat", "power_off"), ("logot", "power_off"),
                    ("sleep", "suspend_computer"), ("lock", "lock_screen"), ("wifi sped", "internet_doctor"),
                    ("ram", "cleanup"), ("laptop status", "laptop_doctor"), ("battery", "battery_status")):
        i = fastpath.match(t)
        assert i is not None and i.tool == tool, (t, i)
    for t in ("restaurant", "shut up", "slep well", "lock the door", "time to study", "ramayan"):
        i = fastpath.match(t)
        assert i is None or i.tool not in ("power_off", "suspend_computer", "lock_screen"), (t, i)
