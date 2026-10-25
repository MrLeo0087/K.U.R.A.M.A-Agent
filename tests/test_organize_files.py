from jarvis.core import fastpath, organizer


def test_plan_apply_undo(tmp_path, monkeypatch):
    monkeypatch.setattr(organizer.config, "DATA_DIR", str(tmp_path / "data"))
    d = tmp_path / "Downloads"
    d.mkdir()
    for n in ("IMG_20260409_213620.jpg", "doc(3).txt", "Resume Leo.pdf", "setup.deb", "x.crdownload",
              "Screenshot from 2026-10-01 10-00-00.png"):
        (d / n).write_text("ML assignment 2 questions" if n.startswith("doc") else "x")
    monkeypatch.setattr(organizer, "_caption", lambda p: "a dog in a park")

    def fake(msgs, schema, **k):
        import json
        clues = json.loads(msgs[1]["content"])
        return organizer.Names(files=[organizer.Name(i=c["i"], name="Dog in park" if "dog" in c["clue"] else
                                                     "ML assignment 2", topic="College" if "ML" in c["clue"] else "")
                                      for c in clues])
    from jarvis.core import llm
    monkeypatch.setattr(llm, "structured", fake)
    moves = dict((a.name, str(b.relative_to(d))) for a, b in organizer.plan(d))
    assert moves["IMG_20260409_213620.jpg"] == "Images/Dog in park 2026-04-09.jpg"
    assert moves["doc(3).txt"] == "Documents/College/ML assignment 2.txt"
    assert moves["Resume Leo.pdf"] == "Documents/Resume Leo.pdf" and moves["setup.deb"] == "Installers/setup.deb"
    assert "x.crdownload" not in moves and moves["Screenshot from 2026-10-01 10-00-00.png"].startswith("Screenshots/")
    organizer.apply(organizer.plan(d))
    assert (d / "Documents/Resume Leo.pdf").exists() and not (d / "Resume Leo.pdf").exists()
    assert "Put 5 of 5" in organizer.undo_last()
    assert (d / "Resume Leo.pdf").exists() and not (d / "Documents").exists()


def test_intents():
    assert fastpath.match("organize my downloads").args == {"action": "organize", "folder": "downloads"}
    assert fastpath.match("undo organize").args == {"action": "undo"}
