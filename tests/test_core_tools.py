"""v2 phase 3: the AI sees ~17 general tools; each dispatches to the specialised tool through the safety gate."""
import pytest

from jarvis.core import config, registry, safety
from jarvis.tools.core._hub import duration, underlying


@pytest.fixture
def core(monkeypatch):
    monkeypatch.setattr(config, "CORE_TOOLS", True)


def test_the_ai_sees_only_general_tools(core):
    for groups in (["audio", "browser"], ["todo"], ["telegram", "filesearch"], ["schedule"], ["system"]):
        names = [t.name for t in registry.schemas_for(groups)]
        assert names and len(names) <= config.CORE_MAX_TOOLS, groups
        assert all(registry.group_of(registry.get(n)) == "core" for n in names), names
    assert "core" not in registry.groups()
    assert [t.name for t in registry.schemas_for(["toolsmith"])] == ["kurama", "run_command", "run_python"]


@pytest.mark.parametrize("call,want", [
    (("apps", {"action": "open", "target": "youtube"}), ("open_url", {"target": "youtube"})),
    (("apps", {"action": "kill", "target": "brave"}), ("kill_app", {"name": "brave", "force": True})),
    (("laptop", {"action": "volume", "value": "+30"}), ("audio", {"action": "up", "step": 30})),
    (("laptop", {"action": "brightness", "value": "40"}), ("brightness", {"action": "set", "level": 40})),
    (("laptop", {"action": "bluetooth", "value": "off"}), ("laptop_toggle", {"setting": "bluetooth", "state": "off"})),
    (("laptop", {"action": "shutdown"}), ("power_off", {"action": "shutdown"})),
    (("schedule", {"action": "timer", "when": "1 hour 20 min"}), ("set_timer", {"seconds": 4800.0})),
    (("schedule", {"action": "remind", "text": "call mom", "when": "at 5 pm"}), ("add_reminder", {"text": "call mom", "when": "at 5 pm"})),
    (("files", {"action": "delete", "path": "~/x.txt"}), ("delete_to_trash", {"path": "~/x.txt"})),
    (("telegram", {"action": "message", "text": "hi"}), ("send_message_telegram", {"text": "hi"})),
    (("create", {"action": "image", "what": "a hill", "telegram": True}), ("generate_image", {"prompt": "a hill", "send_to_telegram": True})),
    (("info", {"action": "weather", "query": "Pokhara"}), ("weather", {"place": "Pokhara", "days": 1})),
])
def test_dispatch_tables(call, want):
    assert underlying(*call) == want


def test_duration_parser():
    assert duration("5 minutes") == {"seconds": 300.0} and duration("90 sec") == {"seconds": 90.0}
    assert duration("10") == {"seconds": 600.0} and duration("") == {}


def test_confirm_still_applies_through_a_general_tool(core, monkeypatch):
    """Deleting through `files` asks exactly like delete_to_trash does; a 'no' runs nothing."""
    asked = []
    res = safety.execute("files", {"action": "delete", "path": "/tmp/kurama-nope.txt"},
                         confirm=lambda p: asked.append(p) or False)
    assert asked and "trash" in asked[0].lower() and "declined" in res.output


def test_run_command_asks_every_time_and_refuses_dangerous_ones(core, tmp_path):
    asked = []
    res = safety.execute("run_command", {"command": "echo kurama", "folder": str(tmp_path)},
                         confirm=lambda p: asked.append(p) or True)
    assert asked == [f"Should I run this command in {tmp_path}?\necho kurama"] and res.output == "kurama"
    assert "Refused" in safety.execute("run_command", {"command": "sudo rm -rf /"}, confirm=lambda p: True).output
    assert not safety.execute("run_command", {"command": "ls"}, confirm=lambda p: False).ok
    out = safety.execute("run_python", {"code": "print(6*7)"}, confirm=lambda p: True).output
    assert out == "42"
