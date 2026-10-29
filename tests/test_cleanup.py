from jarvis.core import cleanup, fastpath, slash


def test_clean_commands_and_plain_requests_reach_the_cleanup():
    for t, a in (("clean my ram", "ram"), ("optimize my RAM", "ram"), ("clean my storage", "storage"),
                 ("clear the cache", "storage"), ("clean kurama", "kurama"), ("clean yourself", "kurama")):
        i = fastpath.match(t)
        assert i.tool == "cleanup" and i.args == {"action": a}, t
    assert slash.lookup("clean") is not None if hasattr(slash, "lookup") else True


def test_storage_cleans_only_caches(monkeypatch, tmp_path):
    monkeypatch.setattr(cleanup, "HOME", tmp_path)
    (tmp_path / ".cache/pip").mkdir(parents=True)
    (tmp_path / ".cache/pip/x.whl").write_bytes(b"x" * 2_000_000)
    (tmp_path / ".config/BraveSoftware").mkdir(parents=True)
    (tmp_path / ".config/BraveSoftware/Cookies").write_text("logins")
    out = cleanup.storage()
    assert "Freed 2 MB" in out and not (tmp_path / ".cache/pip").exists()
    assert (tmp_path / ".config/BraveSoftware/Cookies").exists()  # browsers are never touched


def test_ram_lists_top_apps(monkeypatch):
    monkeypatch.setattr(cleanup, "top_apps", lambda n=5: ([("brave", 2_000_000_000), ("code", 900_000_000)], [("brave", 35.0)]))
    out = cleanup.ram()
    assert "Top RAM: brave 2.0 GB, code 900 MB" in out and "Top CPU: brave 35%" in out
