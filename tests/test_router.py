import pytest

from jarvis.core import llm, router, store


@pytest.fixture
def no_llm(monkeypatch):
    def fail(*a, **k):
        raise AssertionError("classifier must not be called")
    monkeypatch.setattr(llm, "chat", fail)


def test_keyword_rules(no_llm):
    r = router.route("What time is it?")
    assert (r.groups, r.method) == (["general"], "rules")
    r = router.route("delete the file notes.txt and tell me the date")
    assert set(r.groups) == {"files", "general"} and r.method == "rules"
    assert router.route("kitne baje hain?").groups == ["general"]
    assert router.route("अहिले कति बज्यो").groups == ["general"]


def test_rules_drop_groups_without_tools(no_llm):
    r = router.route("look up the latest news")  # 'web' has no tools yet
    assert (r.groups, r.method) == ([], "rules")
    assert router.route("how is my system doing").groups == ["system"]  # P6: resource_status
    assert router.route("open firefox").groups == ["apps"]


def test_pure_chat_sends_no_tools(no_llm):
    for text in ("hi, how are you", "tell me a joke", "thanks!"):
        r = router.route(text)
        assert (r.groups, r.method) == ([], "chat"), text
    assert router.route("compare python and rust").reasoning


def test_classifier_fallback(monkeypatch):
    seen = {}

    def fake(messages, tier="fast", **kw):
        seen.update(tier=tier, prompt=messages[0]["content"])
        return llm.Reply("files, general, reasoning", "m")

    monkeypatch.setattr(llm, "chat", fake)
    r = router.route("check what is taking space in my downloads")
    assert r.method == "classifier" and r.groups == ["files", "general"] and r.reasoning
    assert seen["tier"] == "fast" and "- files:" in seen["prompt"]


def test_classifier_error_means_no_tools(monkeypatch):
    def fail(*a, **k):
        raise llm.LLMError("down")

    monkeypatch.setattr(llm, "chat", fail)
    r = router.route("check the status of the server")
    assert (r.groups, r.method) == ([], "classifier")


def test_routing_is_logged(no_llm):
    router.route("what's the time")
    row = store.recent_routing(1)[0]
    assert row["groups"] == ["general"] and row["method"] == "rules" and row["latency_ms"] >= 0
