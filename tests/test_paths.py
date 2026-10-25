from jarvis.core import config, paths, planner, fastpath


def _tree(tmp_path):
    for d in ("Drive/Tara/OCR_CODE", "Drive/Tara/Tara_source_code", "Drive/New_project/KURAMA",
              "Drive/Test_project/KURAMA", "Home/Downloads"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "Drive/New_project/KURAMA/README.md").write_text("x")
    return tmp_path


def test_spoken_paths_resolve(tmp_path, monkeypatch):
    t = _tree(tmp_path)
    monkeypatch.setattr(config, "SEARCH_ROOTS", (str(t / "Drive"), str(t / "Home")))
    monkeypatch.setattr(config, "PATH_ALIASES", {"project1": str(t / "Drive"), "downloads": str(t / "Home/Downloads")})
    assert paths.smart_path("project1 then tara folder") == t / "Drive/Tara"
    assert paths.smart_path("tara folder in project1") == t / "Drive/Tara"
    assert paths.smart_path("project1/tara/ocr code") == t / "Drive/Tara/OCR_CODE"
    # two KURAMA folders: backtracks to the one that has the file
    assert paths.smart_path("project1/kurama/README.md") == t / "Drive/New_project/KURAMA/README.md"
    assert paths.smart_path("downloads") == t / "Home/Downloads"
    assert paths.smart_path("nothing like this anywhere") is None


def test_file_requests_stay_local_and_unsplit():
    assert planner.split_clauses("search for main.py in project1 then tara folder") == [
        "search for main.py in project1 then tara folder"]
    i = fastpath.match("search for main.py in project1")  # laptop search (scoped), not Google
    assert i is None or (i.tool, i.args["path"]) == ("find_files", "project1")
    assert not planner.is_long_job("create a new python project called demo_cli in project1")
    assert planner.is_long_job("write a 500 word essay about Nepal")
