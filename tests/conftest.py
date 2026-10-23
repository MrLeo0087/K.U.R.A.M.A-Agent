import pytest

from jarvis.core import llm, store


@pytest.fixture(autouse=True)
def tmp_store(tmp_path):
    store.init(tmp_path / "test.db")
    yield store
    store.close()
    llm.set_client(None)
