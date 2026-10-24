"""Code time machine + where was I: real shadow git repos in a temp project (no real projects touched)."""
import json
import os
import subprocess
import time

import pytest

from jarvis.core import config, llm, registry, safety, store, timemachine as tm
from jarvis.workers import timemachine as tmw


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    p = tmp_path / "myproj"
    p.mkdir()
    subprocess.run(["git", "init", "-q", str(p)], check=True)
    (p / ".gitignore").write_text("secret.txt\n")
    (p / "train.py").write_text("lr = 0.1\nprint('train')\n")
    (p / "secret.txt").write_text("pw")
    (p / "venv").mkdir()
    (p / "venv" / "big.py").write_text("x")
    (p / "model.pt").write_bytes(b"\0" * 10)
    store.kv_set("tm_found", json.dumps([str(p)]))
    store.kv_set("tm_found_at", str(time.time()))
    return p


def committed_files(p):
    return tm._git(p, "ls-tree", "-r", "--name-only", "HEAD").stdout.split()


def test_snapshots_respect_ignores_and_only_when_changed(proj, monkeypatch):
    monkeypatch.setattr(config, "TIMEMACHINE_MAX_MB", 0.0001)  # ~100 bytes
    (proj / "notes.md").write_text("x" * 500)
    assert "snapshot saved" in tm.snapshot(proj)
    files = committed_files(proj)
    assert "secret.txt" not in files and "venv/big.py" not in files and "model.pt" not in files
    assert "notes.md" not in files  # over the size limit
    assert not (proj / ".git" / "refs" / "heads" / "master").exists()  # the real repo is untouched
    assert tm.snapshot(proj) == "no changes since the last snapshot"


def test_worker_diff_history_restore_undo(proj):
    monkey_time = time.time()
    assert tmw.TimeMachine().tick() is None and committed_files(proj)  # dirty repo -> first snapshot
    old = tm._git(proj, "rev-parse", "HEAD").stdout.strip()
    time.sleep(1.1)
    (proj / "train.py").write_text("lr = 0.001\nprint('train')\n")
    os.utime(proj / "train.py", (time.time(), time.time()))
    assert tm.changed_since(proj, monkey_time)
    out = registry.call("time_machine", {"action": "changes", "when": old}).output
    assert "-lr = 0.1" in out and "+lr = 0.001" in out
    assert "train.py" in registry.call("time_machine", {"action": "history", "file": "train.py"}).output
    no = safety.execute("time_machine", {"action": "restore", "file": "train.py", "when": old}, confirm=lambda p: False)
    assert "said no" in no.output and "0.001" in (proj / "train.py").read_text()
    yes = safety.execute("time_machine", {"action": "restore", "file": "train.py", "when": old}, confirm=lambda p: True)
    assert "Restored train.py" in yes.output and (proj / "train.py").read_text().startswith("lr = 0.1\n")
    assert "Put back train.py" in registry.call("time_machine", {"action": "undo"}).output
    assert "0.001" in (proj / "train.py").read_text()
    assert "myproj" in registry.call("time_machine", {"action": "list"}).output
    assert "only go back to the first one" in registry.call("time_machine", {"action": "changes", "when": "10 years ago"}).output


def test_where_was_i_facts_and_summary(proj, monkeypatch):
    (proj / "train.py").write_text("lr = 0.1\n# TODO: add early stopping\n")
    store._exec("INSERT INTO errors(sig, error, kind, explanation, fix, where_, count, first_seen, last_seen) "
                "VALUES ('s1','ValueError: bad shape','ValueError','x','', 'train.py:2',1,?,?)", (time.time(), time.time()))
    tm.snapshot(proj)
    calls = []
    monkeypatch.setattr(llm, "chat", lambda msgs, **k: calls.append(msgs) or "You were tuning the learning rate.")
    out = registry.call("where_was_i", {"project": str(proj)}).output
    assert out.startswith("You were tuning the learning rate.")
    facts = calls[0][1]["content"]
    assert "uncommitted" in facts and "train.py" in facts and "TODO: add early stopping" in facts
    assert "Last error" in facts and "ValueError: bad shape" in facts
    monkeypatch.setattr(config, "WHERE_WAS_I_LLM", False)
    assert registry.call("where_was_i", {}).output.startswith("Project: myproj")  # the most recent project
