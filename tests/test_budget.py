from jarvis.core import budget, config, store


def test_remaining_and_allow(monkeypatch):
    monkeypatch.setitem(config.DAILY_TOKEN_BUDGET, "mx", 100)
    assert budget.remaining("mx") == 100 and budget.allow("mx")
    store.log_llm("mx", "t", 60, 30, 10, True)
    assert budget.used("mx") == 90 and budget.remaining("mx") == 10
    assert budget.allow("mx") and not budget.allow("mx", needed=20)
    store.log_llm("mx", "t", 20, 0, 10, True)
    assert budget.remaining("mx") == 0 and not budget.allow("mx")
    assert budget.allow("unbudgeted-model")
    assert budget.remaining()["mx"] == 0
    assert "mx: 110/100" in budget.summary()
