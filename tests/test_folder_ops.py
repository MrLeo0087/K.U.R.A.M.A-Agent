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
