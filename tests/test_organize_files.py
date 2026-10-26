import json
import os

from jarvis.core import fastpath, organizer


def _old(p):
    os.utime(p, (p.stat().st_atime, p.stat().st_mtime - 3600))


def test_plan_apply_undo(tmp_path, monkeypatch):
    monkeypatch.setattr(organizer.config, "DATA_DIR", str(tmp_path / "data"))
    d = tmp_path / "Downloads"
    d.mkdir()
    content = {"IMG_20260409_213620.jpg": "img", "doc(3).txt": "ML assignment 2 questions",
               "notes ml.txt": "ML lecture 4 notes", "Resume Leo.pdf": "resume", "setup.deb": "deb",
               "Screenshot from 2026-10-01 10-00-00.png": "shot", "report.txt": "same bytes",
               "report (1).txt": "same bytes"}
    for n, c in content.items():
        (d / n).write_text(c)
        _old(d / n)
    (d / "fresh.txt").write_text("still downloading")  # changed just now: left alone
    monkeypatch.setattr(organizer, "_caption", lambda p: "a dog in a park")
    monkeypatch.setattr(organizer, "_snippet", lambda p: (d / p.name).read_text() if p.suffix == ".txt" else "")

    def fake(msgs, schema, **k):
        out = []
        for c in json.loads(msgs[1]["content"]):
            if "dog" in c["clue"]:
                out.append(organizer.Name(i=c["i"], name="Dog in park", topic=""))
            elif "ML" in c["clue"]:
                out.append(organizer.Name(i=c["i"], name="ML " + ("assignment 2" if "assign" in c["clue"] else
                                                                  "lecture 4"), topic="College"))
            else:
                out.append(organizer.Name(i=c["i"], name=c["name"].rsplit(".", 1)[0], topic=""))
        return organizer.Names(files=out)
    from jarvis.core import llm
    monkeypatch.setattr(llm, "structured", fake)
    moves = {a.name: str(b.relative_to(d)) for a, b in organizer.plan(d)}
    assert moves["IMG_20260409_213620.jpg"] == "Images/Dog in park 2026-04-09.jpg"
    assert moves["doc(3).txt"] == "Documents/College/ML assignment 2.txt"  # 2 files share College
    assert moves["notes ml.txt"] == "Documents/College/notes ml.txt"  # a fine name is kept
    assert moves["setup.deb"] == "Installers/setup.deb"
    assert moves["report (1).txt"] == "Duplicates/report (1).txt" and moves["report.txt"] == "Documents/report.txt"
    assert "fresh.txt" not in moves
    assert moves["Screenshot from 2026-10-01 10-00-00.png"].startswith("Screenshots/")
    n = len(moves)
    organizer.apply(organizer.plan(d))
    assert (d / "Installers/setup.deb").exists() and not (d / "setup.deb").exists()
    assert f"Put {n} of {n}" in organizer.undo_last()
    assert (d / "setup.deb").exists() and not (d / "Documents").exists()


def test_intents():
    assert fastpath.match("organize my downloads").args == {"action": "organize", "folder": "downloads"}
    assert fastpath.match("undo organize").args == {"action": "undo"}


def test_messy_names():
    from pathlib import Path
    assert organizer.messy(Path("Inception.2010.1080p.Dual.Audio.Hin-Eng.[Vegamovies.NL].mkv"))
    assert organizer.messy(Path("Raja (2026) New Released | Ravi Teja [zsLMsPSbHNY].jpg"))
    assert not organizer.messy(Path("Resume Leo.pdf")) and organizer._topic("ml") == "ML" and organizer._topic("ML") == "ML"
