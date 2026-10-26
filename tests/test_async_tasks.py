import json
import os
import time

from jarvis.core import fastpath, organizer


def test_organize_runs_in_background_then_yes_no_edit(tmp_path, monkeypatch):
    monkeypatch.setattr(organizer.config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(organizer.config, "OUTPUTS_DIR", tmp_path / "out")
    d = tmp_path / "Downloads"
    d.mkdir()
    for n in ("a.pdf", "b.jpg", "c.deb"):
        (d / n).write_text(n)
        os.utime(d / n, (time.time() - 3600, time.time() - 3600))
    monkeypatch.setattr(organizer, "_snippet", lambda p: "")
    from jarvis.core import llm
    monkeypatch.setattr(llm, "structured", lambda m, schema, **k: schema())  # no names/topics
    from jarvis.core import jobs, safety
    started = []
    monkeypatch.setattr(safety, "context", lambda: {"jobs": started})
    msg = organizer.start(d)
    assert "in the background" in msg and started
    job = jobs.get_manager().get(started[0])
    job.future.result(timeout=10)
    assert job.progress.startswith("» Plan ready: 3 files") and organizer.pending_active()
    assert "## Documents  (1)" in open(job.output_path).read()
    # while a plan waits, free answers are routed to it (0 tokens)
    assert fastpath.match("yes yes good").args == {"action": "apply"}
    assert fastpath.match("no").args == {"action": "cancel"}
    assert fastpath.match("keep the pictures where they are").args["action"] == "edit"
    monkeypatch.setattr(llm, "structured", lambda m, schema, **k: organizer.Changes(
        changes=[organizer.Change(i=i, dest="KEEP") for i, r in enumerate(json.loads(m[1]["content"].split("Plan: ")[1]))
                 if r["file"] == "b.jpg"]))
    assert "Changed 1 files" in organizer.edit_pending("keep the pictures where they are")
    assert "Organized 2 files" in organizer.apply_pending()
    assert (d / "b.jpg").exists() and (d / "Installers/c.deb").exists() and not organizer.pending_active()
    assert fastpath.match("yes") is None or fastpath.match("yes").tool != "organize_files"


def test_plan_expires(tmp_path, monkeypatch):
    monkeypatch.setattr(organizer.config, "ORGANIZE_PLAN_TTL_S", -1)
    organizer._save_pending(tmp_path, [(tmp_path / "x", tmp_path / "Docs/x")])
    assert not organizer.pending_active() and "no plan waiting" in organizer.apply_pending()
