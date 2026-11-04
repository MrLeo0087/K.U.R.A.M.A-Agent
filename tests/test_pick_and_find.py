"""11-04: a pick from search results acts on that result; a folder search lists real folders only."""
from jarvis.core import config, fastpath, workmem
from jarvis.tools.interactive import find_files as ff


def test_pick_from_a_search_opens_or_sends_it(tmp_path):
    a, b = tmp_path / "a" / "x", tmp_path / "b" / "x"
    a.mkdir(parents=True), b.mkdir(parents=True)
    res = f"2 folders named like 'x':\n1. {a}/\n2. {b}/"
    for said, want in [("open first one in vs code", ("open_path", {"path": str(a), "app": "vscode"})),
                       ("send the second one", ("send_file_telegram", {"path": str(b)}))]:
        workmem.record_call("find_files", {"query": "x", "path": "/tmp", "kind": "folder"}, True, res)
        it = fastpath.match(said)
        assert (it.tool, it.args) == want, said


def test_nested_and_kurama_data_matches_are_dropped():
    d = str(config.DATA_DIR)
    got = ff._tops(["/p/KURAMA/", "/p/KURAMA/kurama/", f"{d}/outputs/kurama/", "/q/Kurama_Main/"])
    assert got == ["/p/KURAMA/", "/q/Kurama_Main/"]


def test_folder_word_means_folders():
    assert fastpath.match("find kurma folder in project1").args["kind"] == "folder"
    assert fastpath.match("send image to telegram as well").tool == "send_last_result"
