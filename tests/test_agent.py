"""Agent graph with a fake LangChain chat model in place of ChatGroq (via llm.model_for), so the
real llm.chat path (bind_tools, streaming, logging callback) and LangChain messages are used."""
import json
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool

from jarvis.core import agent, config, llm, store


class FakeChat(BaseChatModel):
    """Pops scripted AIMessages (repeats the last one); records each request in `calls`."""

    model_id: str = "fake"
    shared: Any = None  # SimpleNamespace(script, calls), shared by every tier's instance

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, tool_choice=None, **kw):
        return self.bind(tools=[convert_to_openai_tool(t) for t in tools], tool_choice=tool_choice)

    def _next(self, messages, run_manager, stream, kw) -> AIMessage:
        self.shared.calls.append({"messages": list(messages), "model": self.model_id, "stream": stream,
                           "tools": [t["function"]["name"] for t in kw.get("tools") or []] or None,
                           "tool_choice": kw.get("tool_choice"),
                           "purpose": (run_manager.metadata or {}).get("purpose") if run_manager else None})
        sc = self.shared.script
        return sc.pop(0) if len(sc) > 1 else sc[0]

    def _generate(self, messages, stop=None, run_manager=None, **kw: Any) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next(messages, run_manager, False, kw))])

    def _stream(self, messages, stop=None, run_manager=None, **kw: Any):
        msg = self._next(messages, run_manager, True, kw)
        for word in msg.content.split(" ") if msg.content else []:
            yield ChatGenerationChunk(message=AIMessageChunk(content=word + " "))
        chunks = [{"name": tc["name"], "args": json.dumps(tc["args"]), "id": tc["id"], "index": i}
                  for i, tc in enumerate(msg.tool_calls)]
        if chunks:
            yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=chunks))


def call(name="get_time", args=None, i=1):
    return AIMessage(content="", tool_calls=[{"id": f"c{i}", "name": name, "args": args or {}}])


@pytest.fixture
def fake(monkeypatch):
    def install(*replies):
        shared = SimpleNamespace(script=list(replies), calls=[])
        monkeypatch.setattr(llm, "model_for", lambda m: FakeChat(model_id=m, shared=shared))
        return shared.calls
    return install


def test_tool_call_then_answer(fake):
    calls = fake(call(), AIMessage(content="It is 11:42."))
    a = agent.Agent()
    assert a.run("what time is it?") == "It is 11:42."
    assert calls[0]["tools"] == ["get_time"] and calls[0]["model"] == config.LLM_FAST
    second = calls[1]["messages"]
    assert second[-2].tool_calls[0]["name"] == "get_time"
    assert isinstance(second[-1], ToolMessage) and second[-1].tool_call_id == "c1"
    row = store.recent_tool_calls(1)[0]
    assert (row["tool"], row["outcome"], row["ok"]) == ("get_time", "allowed", 1)
    assert store.recent_routing(1)[0]["groups"] == ["general"]
    assert a.last["tools"] == [{"name": "get_time", "ok": True}]
    assert isinstance(a.history[-1], AIMessage) and a.history[-1].content == "It is 11:42."
    purposes = [r[0] for r in store._exec("SELECT purpose FROM llm_calls ORDER BY id")]
    assert purposes == ["agent_text", "agent_text"]


def test_stream_yields_final_answer(fake):
    calls = fake(call(), AIMessage(content="It is late."))
    a = agent.Agent()
    out = "".join(a.stream("what time is it?", mode="voice", lang="hi"))
    assert out.strip() == "It is late."
    assert "Hindi" in calls[0]["messages"][0].content and calls[0]["stream"]
    assert store.recent_tool_calls(1)[0]["tool"] == "get_time"


def test_voice_chat_uses_voice_tier_without_tools(fake):
    calls = fake(AIMessage(content="Hello there."))
    out = "".join(agent.Agent().stream("hi, how are you", mode="voice", lang="en"))
    assert out.strip() == "Hello there."
    assert calls[0]["model"] == config.LLM_VOICE and calls[0]["tools"] is None


def test_chat_sends_no_tools(fake):
    calls = fake(AIMessage(content="I'm good, thanks!"))
    assert agent.Agent().run("hi, how are you") == "I'm good, thanks!"
    assert len(calls) == 1 and calls[0]["tools"] is None
    assert store.recent_tool_calls(5) == []


def test_confirm_denied_through_agent(fake):
    calls = fake(call("dummy_delete", {"path": "/tmp/a"}), AIMessage(content="Okay, I did not delete it."))
    a = agent.Agent(confirm=lambda p: False)
    assert "not" in a.run("delete the file /tmp/a")
    assert store.recent_tool_calls(1)[0]["outcome"] == "denied"
    assert "declined" in calls[1]["messages"][-1].content


def test_unrouted_tool_is_refused(fake):
    fake(call("dummy_delete", {"path": "/"}), AIMessage(content="Done."))
    agent.Agent(confirm=lambda p: True).run("what time is it")
    row = store.recent_tool_calls(1)[0]
    assert (row["tool"], row["outcome"]) == ("dummy_delete", "error")


def test_round_limit_forces_answer(fake):
    calls = fake(call())  # always asks for the tool
    ans = agent.Agent().run("what time is it")
    assert ans == agent.TOO_MANY_ROUNDS
    assert len(calls) == config.AGENT_MAX_TOOL_ROUNDS + 1
    assert calls[-1]["tool_choice"] == "none"


def test_multi_group_uses_smart_tier(fake):
    calls = fake(AIMessage(content="Sure."))
    agent.Agent(use_planner=False).run("delete the file x and tell me the time")
    assert calls[0]["model"] == config.LLM_DEFAULT and len(calls[0]["tools"]) == 2


def test_history_window_and_summary(fake, monkeypatch):
    monkeypatch.setattr(config, "HISTORY_TURNS", 2)
    monkeypatch.setattr(config, "AGENT_SUMMARY_BATCH_TURNS", 1)
    calls = fake(AIMessage(content="ok"))
    a = agent.Agent(summarize_async=False)
    for i in range(4):
        a.run(f"hello {i}")
    assert len(a.history) == 4 and a.summary == "ok"
    assert "summary" in [c["purpose"] for c in calls]
    last = [c for c in calls if (c["purpose"] or "").startswith("agent")][-1]
    assert "summary" in last["messages"][0].content and len(last["messages"]) == 2 + 4
    assert isinstance(last["messages"][-1], HumanMessage)


def test_warm_builds_graph(fake):
    a = agent.Agent()
    a.warm()
    assert a._graph is not None


def test_system_prompt_is_short():
    text = agent.SYSTEM_PROMPT + agent.VOICE_SUFFIX.format(lang="Nepali (Devanagari script)")
    assert len(text) / 4 < 250
