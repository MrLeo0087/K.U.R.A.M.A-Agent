import pytest

from jarvis.core import assist, dictionary


@pytest.mark.skipif(not dictionary.available(), reason="WordNet db not downloaded")
def test_offline_meaning_0_tokens(monkeypatch):
    monkeypatch.setattr(assist, "_llm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no LLM")))
    out = assist.meaning("serendipity")
    assert out.startswith("serendipity (noun): good luck in making unexpected and fortunate discoveries")
    run = dictionary.lookup("run")
    assert run.startswith("run (verb)") and "\nrun (noun)" in run
    assert "Similar:" in dictionary.lookup("ephemeral")


def test_unknown_words_and_other_languages_use_the_ai(monkeypatch):
    calls = []
    monkeypatch.setattr(assist, "_llm", lambda *a, **k: calls.append(a) or "OAuth (noun): a login standard.")
    assert assist.meaning("OAuth").startswith("OAuth (noun)")
    assist.meaning("serendipity", "ne")  # Nepali meaning: still the AI
    assert len(calls) == 2
    assert dictionary.lookup("") is None and dictionary.lookup("a very long phrase here") is None
