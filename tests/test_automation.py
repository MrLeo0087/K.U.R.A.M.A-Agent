"""File automations with the real tools: wget from a local server, sorting a temp Downloads, rsync backup + verify."""
import functools
import http.server
import os
import threading
import time

import pytest

from jarvis.core import automation as au, config, registry, safety, store
from jarvis.workers import process_watch as pw


@pytest.fixture
def server(tmp_path):
    (tmp_path / "srv").mkdir()
    (tmp_path / "srv" / "data.bin").write_bytes(os.urandom(300_000))
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path / "srv"))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    handler.log_message = lambda *a: None
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_download_now_tonight_and_done(server, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "DOWNLOAD_DIR", str(tmp_path / "dl"))
    out = registry.call("download_file", {"url": f"{server}/data.bin"}).output
    assert "starts now" in out
    later = registry.call("download_file", {"url": f"{server}/data.bin", "when": "tonight"}).output
    assert "data (1).bin" in later and ("starts at 01:00" in later or time.localtime().tm_hour < 6)  # never the same name
    w = pw.ProcessWatcher()
    end = time.time() + 15
    while time.time() < end:
        w.tick()
        if any(a["title"] == "Downloaded data.bin" for a in store.alerts_recent()):
            break
        time.sleep(0.2)
    assert (tmp_path / "dl" / "data.bin").stat().st_size == 300_000
    assert "#1 data.bin: done 0.3 MB" in au.downloads_text()
    assert "give a full http(s) link" in au.queue("not a url")


def test_sort_downloads_preview_run_and_duplicates(tmp_path, monkeypatch):
    d = tmp_path / "Downloads"
    d.mkdir()
    old = time.time() - 3600
    for name, data in [("paper.pdf", b"pdf"), ("paper (1).pdf", b"pdf"), ("pic.JPG", b"jpg"), ("Screenshot from 1.png", b"s"),
                       ("data.csv", b"a,b"), ("film.mkv", b"v"), ("x.part", b"half"), ("odd.xyz", b"?")]:
        (d / name).write_bytes(data)
        os.utime(d / name, (old, old))
    (d / "fresh.pdf").write_bytes(b"new")  # still being written / just arrived: left alone
    monkeypatch.setattr(au.Path, "home", lambda: tmp_path)
    trashed = []
    monkeypatch.setattr(au.subprocess, "run", lambda args, **k: trashed.append(args[-1]))
    assert "I'd move 6 files" in registry.call("tidy_downloads", {}).output
    assert "said no" in safety.execute("tidy_downloads", {"action": "run"}, confirm=lambda p: False).output
    out = safety.execute("tidy_downloads", {"action": "run"}, confirm=lambda p: True).output
    assert out == "Sorted 5 files into folders and moved 1 duplicate(s) to the Trash."
    kept = [p.name for p in (d / "Documents").iterdir()]
    assert len(kept) == 1 and kept[0] in ("paper.pdf", "paper (1).pdf")  # one copy kept, the other trashed
    assert (d / "Images" / "Screenshots" / "Screenshot from 1.png").exists()
    assert (d / "Data" / "data.csv").exists() and (d / "Videos" / "film.mkv").exists()
    assert len(trashed) == 1 and trashed[0].endswith(".pdf") and trashed[0] != str(d / "Documents" / kept[0])
    assert (d / "x.part").exists() and (d / "odd.xyz").exists() and (d / "fresh.pdf").exists()


def test_backup_copies_skips_venv_and_verifies(tmp_path):
    src = tmp_path / "proj"
    (src / "venv" / "lib").mkdir(parents=True)
    (src / "venv" / "lib" / "big.so").write_bytes(b"x" * 1000)
    (src / "train.py").write_text("print(1)")
    (src / "data").mkdir()
    (src / "data" / "d.csv").write_text("a,b")
    drive = tmp_path / "drive"
    assert "doesn't exist" in au.backup_set([str(src)], str(drive))
    drive.mkdir()
    assert "can't be inside" in au.backup_set([str(src)], str(src / "bk"))
    assert "Backup set: proj" in registry.call("backup", {"action": "setup", "folders": str(src), "target": str(drive)}).output
    out = registry.call("backup", {"action": "run"}).output
    assert out.startswith("Backup done: 2 file(s) copied") and "verified" in out
    assert (drive / "proj" / "train.py").exists() and not (drive / "proj" / "venv").exists()
    (src / "train.py").unlink()
    assert "0 file(s) copied" in au.backup_run() and (drive / "proj" / "train.py").exists()  # never deletes there
    assert au.backup_tick() is None  # not due again yet
    assert "last run" in registry.call("backup", {}).output
