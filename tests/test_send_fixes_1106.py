"""11-06 traces: 'send the selected image' sent a 1.1 GB folder; the folder zip held KURAMA's own zips; the AI's
background note reached the owner."""
from __future__ import annotations

from jarvis.core import config, safety
from jarvis.tools.general import send_file_telegram as sft


def test_an_image_request_never_sends_a_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(safety, "context", lambda: {"user_text": "Send the selected image in my telegram."})
    assert "Select the image in Files" in sft._not_what_was_asked(tmp_path)
    pic = tmp_path / "a.png"
    pic.write_bytes(b"x")
    assert sft._not_what_was_asked(pic) == ""
    monkeypatch.setattr(safety, "context", lambda: {"user_text": "send this folder to telegram"})
    assert sft._not_what_was_asked(tmp_path) == ""


def test_folder_size_skips_kurama_outputs(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    out = proj / "data" / "outputs"
    (out / "zips").mkdir(parents=True)
    (out / "zips" / "old.zip").write_bytes(b"x" * 2_000_000)
    (proj / "main.py").write_bytes(b"x" * 1_000_000)
    monkeypatch.setattr(config, "OUTPUTS_DIR", out)
    assert 0.9 < sft.folder_mb(proj) < 1.0


def test_background_note_never_reaches_the_owner():
    note = safety.BACKGROUND_NOTE.format(s=8, id=57)
    out = safety.scrub("I'm\n" + note)
    assert "Tell the user" not in out and "job #57" in out


def test_a_named_new_file_is_created_in_the_folder_in_use(tmp_path, monkeypatch):
    from jarvis.core import context
    from jarvis.tools.general import code_to_file as ctf
    (tmp_path / "notes.txt").write_text("hi")
    monkeypatch.setattr(context, "snapshot", lambda: {"file": str(tmp_path / "notes.txt")})
    assert ctf.named_file("Create a new file in this folder name calculator.py and write code") == tmp_path / "calculator.py"
    assert ctf.named_file("Write simple calculator code in calculator.px") == tmp_path / "calculator.py"
    assert ctf.named_file("make app dot js") == tmp_path / "app.js"
    assert ctf.named_file("open google.com") is None
