"""Open a folder in the file manager, and zip-and-send a folder to Telegram."""
from __future__ import annotations

import zipfile
from unittest import mock

from jarvis.core import config


def test_open_folder_opens_file_manager(monkeypatch, tmp_path):
    (tmp_path / "College Project").mkdir()
    import jarvis.tools.general.open_url as ou
    import jarvis.tools.interactive.list_folder as lf
    opened = []
    monkeypatch.setattr(ou, "_open", opened.append)
    monkeypatch.setattr(lf, "_targets", lambda name: ([tmp_path / "College Project"], []))
    from jarvis.tools.general.open_folder import open_folder
    out = open_folder("college project")
    assert "file manager" in out and opened == [str(tmp_path / "College Project")]


def test_folder_zipped_and_sent(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(config, "SHARE_ROOTS", (tmp_path,))
    d = tmp_path / "clz_project"
    (d / "src").mkdir(parents=True)
    (d / "src" / "main.py").write_text("print(1)")
    (d / "venv").mkdir()
    (d / "venv" / "big.bin").write_bytes(b"x" * 1000)  # junk: must be skipped
    import jarvis.tools.general.send_file_telegram as S
    monkeypatch.setattr("jarvis.core.paths.all_disks", lambda: [tmp_path])
    z = S.zip_dir(d)
    names = zipfile.ZipFile(z).namelist()
    assert "clz_project/src/main.py" in names and not any("venv" in n for n in names)

    sent = []
    monkeypatch.setattr(S, "deliver", lambda p, caption="": sent.append((p.name, caption)) or f"Sent {p.name}.")
    monkeypatch.setattr("jarvis.tools.general._tg.ready", lambda: "")
    out = S.send_file_telegram(str(d))
    assert "Sent" in out and sent and sent[0][0].endswith(".zip") and "folder" in sent[0][1]


def test_big_folder_split_into_parts(monkeypatch, tmp_path):
    import os
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(config, "SHARE_ROOTS", (tmp_path,))
    monkeypatch.setattr(config, "TELEGRAM_FILE_MAX_MB", 1)  # tiny limit to force a split
    monkeypatch.setattr("jarvis.core.paths.all_disks", lambda: [tmp_path])
    monkeypatch.setattr("jarvis.tools.general._tg.ready", lambda: "")
    d = tmp_path / "bigproj"
    d.mkdir()
    for i in range(6):
        (d / f"f{i}.bin").write_bytes(os.urandom(500 * 1024))  # incompressible: the zip stays big
    import jarvis.tools.general.send_file_telegram as S
    sent = []
    monkeypatch.setattr(S, "deliver", lambda p, caption="": sent.append(p.name) or f"Sent {p.name}.")
    out = S.deliver_folder(d)
    assert "parts" in out and "cat" in out and len(sent) >= 3
    assert all(".zip.00" in n for n in sent)  # the real timestamped base, numbered
    base = sent[0].rsplit(".", 1)[0]  # <name>-<ts>.zip
    assert f"cat {base}.*" in out  # the reassembly glob matches the actual filenames
