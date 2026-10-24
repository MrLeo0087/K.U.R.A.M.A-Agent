"""ML disk cleaner on a fake home: categories found, cleaning asks, only true duplicates removed, newest checkpoint kept."""
import os
import time

import pytest

from jarvis.core import config, diskclean as dc, registry, safety


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(dc, "HOME", tmp_path)
    proj = tmp_path / "proj"
    monkeypatch.setattr(config, "SEARCH_ROOTS", (str(proj),))
    (tmp_path / ".cache" / "huggingface" / "hub").mkdir(parents=True)
    (tmp_path / ".cache" / "huggingface" / "hub" / "model.bin").write_bytes(b"\0" * (30 * 1048576))
    ck = proj / "runs"
    ck.mkdir(parents=True)
    old = time.time() - 60 * 86400
    for i in range(3):
        f = ck / f"epoch{i}.pt"
        f.write_bytes(b"\1" * (12 * 1048576))
        os.utime(f, (old + i, old + i))
    (proj / "pkg" / "__pycache__").mkdir(parents=True)
    big = b"\2" * (51 * 1048576)
    (proj / "a.zip").write_bytes(big)
    (proj / "b.zip").write_bytes(big)
    os.utime(proj / "a.zip", (old, old))
    c = bytearray(big)
    c[-1] = 9
    (proj / "c.zip").write_bytes(bytes(c))  # same size and first MB, different end: NOT a duplicate
    return tmp_path


def test_scan_finds_categories(home):
    out = dc.scan()
    assert "Hugging Face cache: 30 MB" in out and "old model checkpoints" in out and "duplicate big files" in out
    assert [p.name for p in dc.find("checkpoints")] == ["epoch1.pt", "epoch0.pt"]  # newest (epoch2) kept
    assert {p.name for p in dc.find("pycache")} == {"__pycache__"}


def test_clean_asks_and_keeps_originals(home, monkeypatch):
    trashed = []
    monkeypatch.setattr(dc, "trash", lambda p: trashed.append(str(p)))
    no = safety.execute("disk_cleaner", {"action": "clean", "category": "duplicates"}, confirm=lambda p: False)
    assert "said no" in no.output and not trashed
    yes = safety.execute("disk_cleaner", {"action": "clean", "category": "duplicates"}, confirm=lambda p: True)
    assert trashed == [str(home / "proj" / "b.zip")] and "Freed 51 MB" in yes.output  # c.zip differs: kept
    out = safety.execute("disk_cleaner", {"action": "clean", "category": "huggingface"}, confirm=lambda p: True).output
    assert "Freed 30 MB" in out and not (home / ".cache" / "huggingface").exists()
    assert "error: say which" in safety.execute("disk_cleaner", {"action": "clean", "category": "x"}).output
    assert registry.resolve("cleanup_scan", {"path": "~"}) == ("disk_cleaner", {"path": "", "action": "scan"})
