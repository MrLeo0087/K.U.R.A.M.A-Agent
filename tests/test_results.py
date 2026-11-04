"""Typed tool results: a Reply is still text, and its exact paths reach the pick list (mocked, no tools run)."""
from __future__ import annotations

from jarvis.core import registry, workmem
from jarvis.core.results import Reply, data_of


def test_reply_is_text_with_data():
    r = Reply("2 folders:\n1. a\n2. b", paths=["/a", "/b"], none=None)
    assert r == "2 folders:\n1. a\n2. b" and isinstance(r, str)
    assert data_of(r) == {"paths": ["/a", "/b"]} and data_of("plain") == {}
    assert r.upper().startswith("2 FOLDERS")  # string methods give plain strings back


def test_registry_keeps_reply_data(monkeypatch):
    reg = registry.Registry()

    @reg.tool(group="files")
    def lister(q: str) -> str:
        """List things (test)."""
        return Reply(f"1. {q}", paths=["/x"])

    res = reg.call("lister", {"q": "k"})
    assert res.ok and res.output.startswith("1. k") and res.data == {"paths": ["/x"]}


def test_pick_uses_exact_paths(tmp_path, monkeypatch):
    deep = tmp_path / ("very_long_folder_name_" * 8)  # a line cut to 140 characters for display
    deep.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    offered = {}
    monkeypatch.setattr(workmem, "_offer", lambda tool, args, opts: offered.setdefault("opts", opts))
    text = f"2 folders:\n1. {str(deep)[:120]}...\n2. {other}"
    workmem.record_call("find_files", {"query": "x"}, True, text, data={"paths": [str(deep), str(other)]})
    assert offered["opts"] == [deep, other]
