import pytest

from jarvis.core import config, jobs, llm, ratelimit, store


@pytest.fixture(autouse=True)
def tmp_store(tmp_path, monkeypatch):
    store.init(tmp_path / "test.db")
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(config, "JOBS_NOTIFY", False)  # never pop desktop notifications in tests
    monkeypatch.setattr(config, "FASTPATH", False)  # LLM-path tests stay on the LLM path; fastpath tests enable it
    from jarvis.tools.general import open_url
    opened: list[str] = []
    monkeypatch.setattr(open_url, "_open", opened.append)  # never open the real browser
    ratelimit.reset()
    yield store
    jobs.reset_manager()
    ratelimit.reset()
    store.close()
    llm.set_client(None)
