"""Study notes (subjects, showing a week) and the lecture recorder pipeline (real ffmpeg chunking, Whisper faked)."""
import subprocess
import time
from types import SimpleNamespace

import pytest

from jarvis.core import config, fastpath, lecture, llm, notes, phone, registry, stt


@pytest.fixture(autouse=True)
def notes_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "NOTES_DIR", str(tmp_path / "Notes"))
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    return tmp_path / "Notes"


def test_notes_by_subject_and_show(notes_dir, monkeypatch):
    assert registry.call("study_notes", {"text": "heap = complete binary tree", "subject": "dsa"}).output == "Noted under Dsa."
    assert notes.add("BFS uses a queue", "DSA") == "Noted under Dsa."  # same folder, any case
    assert notes.add("F = ma", "Physics") == "Noted under Physics."
    calls = []
    monkeypatch.setattr(llm, "chat", lambda msgs, **k: calls.append(msgs) or "Physics")
    assert notes.add("v = u + at") == "Noted under Physics." and len(calls) == 1  # picked from my subjects
    out = notes.show("dsa", 7)
    assert "## Dsa" in out and "heap = complete binary tree" in out and "BFS uses a queue" in out and "F = ma" not in out
    assert "Physics" in registry.call("study_notes", {"action": "subjects"}).output
    assert "No chemistry notes" in notes.show("chemistry")
    day = time.strftime("%Y-%m-%d")
    assert (notes_dir / "Dsa" / f"{day}.md").read_text().startswith("# Dsa:")


def test_note_photo_from_phone(notes_dir, monkeypatch):
    monkeypatch.setattr(phone, "download", lambda fid, max_mb=20.0: (b"jpg", "p.jpg"))
    out = phone.save_incoming({"photo": [{"file_id": "x"}], "caption": "note DSA"})
    assert str(notes_dir / "DSA" / "images") in out
    assert "(photo) DSA" in notes.show("DSA")


def test_lecture_start_stop_and_transcribe(tmp_path, monkeypatch, notes_dir):
    # a real 2.5-minute silent recording, 1-minute chunks -> 3 chunks through real ffmpeg; Whisper is faked
    monkeypatch.setattr(lecture, "CHUNK_S", 60)
    rec = tmp_path / "rec.ogg"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "150",
                    "-c:a", "libopus", "-b:a", "8k", str(rec)], check=True, timeout=120)
    started = []

    class FakeProc:
        pid = 999999

        def poll(self):
            return None
    with monkeypatch.context() as m:  # only the recorder's process is faked
        m.setattr(lecture.subprocess, "Popen", lambda args, **k: started.append(args) or FakeProc())
        m.setattr(lecture, "source", lambda where: "mon" if where == "laptop" else "default")
        m.setattr(lecture.time, "sleep", lambda s: None)
        out = registry.call("lecture", {"action": "start", "title": "DSA trees", "source": "laptop"}).output
    assert "Recording 'DSA trees' from the laptop's sound" in out and "-t" in started[0]
    assert started[0][started[0].index("-i") + 1] == "mon"
    seen = []
    monkeypatch.setattr(stt, "transcribe", lambda wav, lang=None: seen.append(len(wav)) or SimpleNamespace(text="trees are graphs"))
    ctx = SimpleNamespace(check=lambda: None, progress=lambda t: None, set_output=lambda p: None)
    path = lecture.transcribe(ctx, rec, "DSA trees")
    text = open(path).read()
    assert len(seen) == 3 and "[00:00] trees are graphs" in text and "[02:00]" in text
    assert lecture.latest_transcript().name == "rec.md"


def test_phrases(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    assert fastpath.match("note for DSA: heaps").args == {"action": "add", "text": "heaps", "subject": "DSA"}
    assert fastpath.match("show my physics notes from today").args == {"action": "show", "subject": "physics", "days": 1}
    assert fastpath.match("record this online class").args["source"] == "laptop"
    assert fastpath.match("stop the recording").args == {"action": "stop"}
    assert fastpath.match("note that my wifi password is x") is None or \
        fastpath.match("note that my wifi password is x").tool != "laptop_toggle"
