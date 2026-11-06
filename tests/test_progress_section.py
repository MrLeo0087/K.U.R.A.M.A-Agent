"""The Progress section: running jobs with an amount, steps, what just ended, music; old ends leave."""
from __future__ import annotations

import time

from jarvis.core import progress, store


def test_amounts():
    assert progress.frac_of("file 3/6", "running") == 0.5
    assert progress.frac_of("downloading 42%", "running") == 0.42
    assert progress.frac_of("thinking", "running") is None
    assert progress.frac_of("", "done") == 1.0


def test_items(monkeypatch):
    now = time.time()
    rows = {("queued", "running", "paused"): [{"id": 7, "title": "send file telegram: /media/leo/x/KURAMA",
                                               "kind": "tool", "status": "running", "progress": "zipping 2/4",
                                               "created": now}],
            ("done", "failed", "cancelled", "stopped"): [
                {"id": 6, "title": "essay", "kind": "write", "status": "done", "progress": "» done (700 words)",
                 "created": now - 90, "finished": now - 10},
                {"id": 5, "title": "old", "kind": "write", "status": "done", "progress": "", "created": now - 900,
                 "finished": now - 600}]}
    monkeypatch.setattr(store, "jobs_list", lambda n, st: rows[st])
    monkeypatch.setattr(progress, "_music", lambda: [])
    progress.set_steps(7, [("Plan", "done"), ("Write index.html", "doing"), ("Run it", "todo")])
    got = progress.items()
    assert [x["id"] for x in got] == ["job:7", "job:6", "job:5"]  # finished ones stay as a history
    assert got[0]["title"] == "Send file telegram: KURAMA" and got[0]["frac"] == 0.5
    assert [s["state"] for s in got[0]["steps"]] == ["done", "doing", "todo"]
    assert got[1]["detail"] == "done (700 words)" and got[1]["frac"] == 1.0
