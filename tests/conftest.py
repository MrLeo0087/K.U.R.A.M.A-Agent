import pytest

from jarvis.core import config, jobs, llm, ratelimit, store


@pytest.fixture(autouse=True)
def tmp_store(tmp_path, monkeypatch):
    store.init(tmp_path / "test.db")
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(config, "JOBS_NOTIFY", False)  # never pop desktop notifications in tests
    monkeypatch.setattr(config, "FASTPATH", False)  # LLM-path tests stay on the LLM path; fastpath tests enable it
    monkeypatch.setattr(config, "STT_DUAL", False)  # single-pass STT unless a test opts in
    monkeypatch.setattr(config, "JOB_RESOURCE_GATE", False, raising=False)  # P9b: jobs never wait on real RAM
    from jarvis.tools.general import open_url
    opened: list[str] = []
    monkeypatch.setattr(open_url, "_open", opened.append)  # never open the real browser
    from jarvis.tools.general import _sys

    def no_real_system(argv, *a, **k):
        raise AssertionError(f"real system command in a test: {argv}")
    monkeypatch.setattr(_sys, "_exec", no_real_system)  # never touch volume/brightness/lock/clipboard
    monkeypatch.setattr(config, "SKILLS_DIR", tmp_path / "skills")  # P7c: never the real saved skills
    monkeypatch.setattr(config, "SANDBOX_DIR", tmp_path / "sandbox")
    from jarvis.core import toolsmith
    toolsmith._tried.clear()
    from jarvis.tools.general import _files
    trashed: list = []
    monkeypatch.setattr(_files, "trash", trashed.append)  # never move real files to the trash
    ratelimit.reset()
    yield store
    jobs.reset_manager()
    ratelimit.reset()
    store.close()
    llm.set_client(None)
