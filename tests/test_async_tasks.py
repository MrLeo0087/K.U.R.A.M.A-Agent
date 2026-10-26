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


def test_any_tool_job_is_watched(monkeypatch):
    from jarvis.core import jobs, safety
    started = []
    monkeypatch.setattr(safety, "context", lambda: {"jobs": started})
    j = jobs.get_manager().submit("image: cat", "image", lambda ctx: None)
    j.future.result(timeout=5)
    assert started == [j.id]


def test_clean_workspace_moves_to_trash(tmp_path, monkeypatch):
    import asyncio
    from jarvis.api.routes import info
    monkeypatch.setattr(info.shutil if hasattr(info, "shutil") else __import__("shutil"), "which", lambda b: None)
    out = tmp_path / "outputs"
    (out / "plans").mkdir(parents=True)
    (out / "a.png").write_bytes(b"x")
    (out / "plans" / "p.md").write_text("plan")
    monkeypatch.setattr(info, "_outputs_dir", lambda: out)
    r = asyncio.run(info.outputs_clear())
    assert r["moved"] == 2 and not any(out.iterdir())
    assert len(list((tmp_path / "outputs_trash").rglob("*.png"))) == 1
