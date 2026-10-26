"""Freedom routing (P7b): request_tools meta-tool + refusal retry, with the fake chat model."""
import pytest
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from jarvis.core import agent, config, meta, router, store
from tests.test_agent import call, fake  # noqa: F401  (fixture)


def routing_rows():
    return [(r["groups"], r["method"]) for r in store.recent_routing(50)]


@pytest.fixture(autouse=True)
def no_classifier(monkeypatch):
    monkeypatch.setattr(router, "classify", lambda text, avail: ([], False))


def test_meta_schema_is_compact():
    s = meta.schema()["function"]
    assert s["name"] == "request_tools" and "web(" in s["description"] and "system(" in s["description"]
    assert meta.estimate_tokens() < 200  # chars/4 over the JSON; real prompt tokens are lower
    assert meta.pick({"groups": ["System", "nope", "web", "system"]}) == ["system", "web"]
    assert meta.pick({"groups": "web, git"}) == ["web", "git"]


def test_small_talk_skips_meta(fake):
    calls = fake(AIMessage(content="Hi! All good."))
    assert agent.Agent().run("hey jarvis, how are you?") == "Hi! All good."
    assert len(calls) == 1 and calls[0]["tools"] is None


def test_request_tools_then_real_tool(fake):
    calls = fake(call("request_tools", {"groups": ["general"], "reason": "needs the clock"}, 1),
                 call("get_time", {}, 2),
                 AIMessage(content="It is noon."))
    a = agent.Agent()
    assert a.run("I wonder how late it has gotten") == "It is noon."
    assert calls[0]["tools"] == ["request_tools"]
    assert calls[1]["tools"] == ["get_time", "get_date"]  # the chosen group's tools bound for the next round
    loaded = [m for m in calls[1]["messages"] if isinstance(m, ToolMessage)]
    assert loaded and loaded[0].content.startswith("Loaded tools for: general")
    assert a.last["route"].method == "meta" and a.last["route"].groups == ["general"]
    assert [t["name"] for t in a.last["tools"]] == ["request_tools", "get_time"]
    assert (["general"], "meta") in routing_rows()


def test_request_tools_bad_group_then_answer(fake):
    calls = fake(call("request_tools", {"groups": ["flights"], "reason": "book"}, 1),
                 AIMessage(content="I can't book flights yet."))
    assert agent.Agent().run("book me a flight to Delhi") == "I can't book flights yet."
    assert calls[1]["tools"] == ["request_tools"]  # nothing loaded
    assert "unknown groups" in [m for m in calls[1]["messages"] if isinstance(m, ToolMessage)][0].content


def test_refusal_is_retried_once_with_meta(fake, monkeypatch):
    monkeypatch.setattr(config, "META_TOOLS", True)
    calls = fake(AIMessage(content="I don't have a way to check that."),
                 call("request_tools", {"groups": ["general"], "reason": "clock"}, 1),
                 call("get_time", {}, 2),
                 AIMessage(content="It is noon."))
    a = agent.Agent()
    assert a.run("is it late already") == "It is noon."
    assert len(calls) == 4 and a.last.get("meta_retry")
    assert isinstance(calls[1]["messages"][-1], SystemMessage) and "request_tools" in calls[1]["messages"][-1].content
    assert any(r[1] == "meta" for r in routing_rows())


def test_refusal_retry_happens_only_once(fake):
    calls = fake(AIMessage(content="Sorry, I can't do that."))
    assert agent.Agent().run("teleport me to Mars") == "Sorry, I can't do that."
    assert len(calls) == 2  # original + one retry, then the honest answer


def test_no_retry_after_real_tool(fake):
    calls = fake(call("get_time", {}, 1), AIMessage(content="I can't tell the exact seconds."))
    assert agent.Agent().run("what time is it") == "I can't tell the exact seconds."
    assert len(calls) == 2


def test_stream_refusal_is_not_spoken(fake):
    calls = fake(AIMessage(content="I am unable to check that. Sorry about it."),
                 AIMessage(content="Here is the answer."))
    out = "".join(agent.Agent().stream("is my thing ok", mode="voice", lang="en"))
    assert out.strip() == "Here is the answer." and len(calls) == 2
    assert calls[1]["tools"] == ["request_tools"]


def test_meta_disabled(fake, monkeypatch):
    monkeypatch.setattr(config, "META_TOOLS", False)
    calls = fake(AIMessage(content="I can't do that."))
    assert agent.Agent().run("book me a flight") == "I can't do that."
    assert len(calls) == 1 and calls[0]["tools"] is None


def test_router_web_and_project_rules():
    assert router.route("search CarryMinati", log_it=False).groups == ["web"]
    assert router.route("who is CarryMinati", log_it=False).groups == ["web"]
    assert router.route("what is quantum computing", log_it=False).groups == ["web"]
    assert router.route("what is the time", log_it=False).groups == ["general"]
    assert router.route("Can you tell me what is this project about?", log_it=False).groups == ["knowledge"]
    assert "web" not in router.route("what is my latest commit", log_it=False).groups
    assert router.is_small_talk("thanks a lot jarvis!") and not router.is_small_talk("tell me a joke")


def test_project_overview_uses_docs(tmp_path, monkeypatch):
    from jarvis.core import memory
    (tmp_path / "CLAUDE.md").write_text("# JARVIS: voice assistant\nRuns all day on 8 GB.")
    monkeypatch.setattr(config, "ROOT", tmp_path)
    assert memory.is_overview_question("Can you tell me what is this project about?")
    assert not memory.is_overview_question("how does the fast path work")
    assert memory.overview_context().startswith("[CLAUDE.md]\n# JARVIS: voice assistant Runs all day")
