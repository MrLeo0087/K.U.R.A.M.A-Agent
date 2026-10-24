"""Long-command alerts: the real bash hook in a throwaway shell, reading events, alerts, the on/off tool."""
import json
import shutil
import subprocess
import time

import pytest

from jarvis.core import cmdalerts, config, safety, store


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(cmdalerts, "HOOK", tmp_path / "hook.bash")
    monkeypatch.setattr(cmdalerts, "EVENTS", tmp_path / "commands.jsonl")
    monkeypatch.setattr(cmdalerts, "BASHRC", tmp_path / ".bashrc")
    monkeypatch.setattr(cmdalerts, "SOURCE_LINE", f'[ -f "{tmp_path}/hook.bash" ] && . "{tmp_path}/hook.bash"  '
                                                  f'{cmdalerts.MARK}')
    monkeypatch.setattr(cmdalerts, "screen_locked", lambda: False)
    (tmp_path / ".bashrc").write_text("alias ll='ls -l'\n")
    return tmp_path


@pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")
def test_real_bash_hook_records_long_commands(paths):
    cmdalerts.HOOK.write_text(cmdalerts.HOOK_TEXT % {"secs": 1, "dir": paths, "events": cmdalerts.EVENTS})
    rc = paths / "rc"
    rc.write_text(f'. "{cmdalerts.HOOK}"\nPS1="$ "\n')
    script = "sleep 1.2; false\necho quick\nsleep 1.1 | cat\n^C\n"
    subprocess.run(["bash", "--rcfile", str(rc), "-i"], input=script, text=True, capture_output=True, timeout=30,
                   env={"HOME": str(paths), "PATH": "/usr/bin:/bin"})
    events = [json.loads(ln) for ln in cmdalerts.EVENTS.read_text().splitlines()]
    assert [(e["cmd"], e["rc"]) for e in events] == [("sleep 1.2; false", 1), ("sleep 1.1 | cat", 0)]


def test_check_announces_new_events_once(paths):
    store.kv_set("cmdlog_offset", "0")
    now = int(time.time())
    cmdalerts.EVENTS.write_text(
        json.dumps({"cmd": "pip install torch", "rc": 0, "secs": 754, "cwd": "/home/u/proj", "t": now}) + "\n"
        + json.dumps({"cmd": "python build.py", "rc": 137, "secs": 300, "cwd": "/home/u/proj", "t": now}) + "\n"
        + json.dumps({"cmd": "old", "rc": 0, "secs": 300, "cwd": "/", "t": now - 7200}) + "\n")
    assert cmdalerts.check() == 3
    alerts = store.alerts_recent()
    assert [a["title"] for a in alerts][:2] == ["✘ Failed after 5 min", "✔ Done in 12m 34s"]
    assert "killed (often out of memory)" in alerts[0]["text"] and "pip install torch" in alerts[1]["text"]
    assert cmdalerts.check() == 0 and len(store.alerts_recent()) == 2  # not again; the 2 h old one never


def test_tool_on_off_edits_bashrc_after_asking(paths):
    assert "said no" in safety.execute("command_alerts", {"action": "on"}, confirm=lambda p: False).output
    assert not cmdalerts.installed()
    out = safety.execute("command_alerts", {"action": "on", "minutes": 5}, confirm=lambda p: True).output
    assert "longer than 5 min" in out and cmdalerts.installed() and "alias ll" in cmdalerts.BASHRC.read_text()
    assert "KURAMA_CMD_MIN_SECS:-300" in cmdalerts.HOOK.read_text()
    safety.execute("command_alerts", {"action": "on"}, confirm=lambda p: True)
    assert cmdalerts.BASHRC.read_text().count(cmdalerts.MARK) == 1  # never twice
    assert "on (commands longer than" in safety.execute("command_alerts", {}).output
    out = safety.execute("command_alerts", {"action": "off"}, confirm=lambda p: True).output
    assert "off" in out and not cmdalerts.installed() and "alias ll" in cmdalerts.BASHRC.read_text()
    assert not cmdalerts.HOOK.exists()
