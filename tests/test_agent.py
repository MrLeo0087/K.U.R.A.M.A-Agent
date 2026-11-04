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

from jarvis.core import agent, config, llm, registry, store


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
    assert calls[0]["tools"] == ["get_time", "get_date"] and calls[0]["model"] == config.LLM_FAST
    second = calls[1]["messages"]
    assert second[-2].tool_calls[0]["name"] == "get_time"
    assert isinstance(second[-1], ToolMessage) and second[-1].tool_call_id == "c1"
    row = store.recent_tool_calls(1)[0]
    assert (row["tool"], row["outcome"], row["ok"]) == ("get_time", "allowed", 1)
    assert store.recent_routing(1)[0]["groups"] == ["general"]
    assert a.last["tools"] == [{"name": "get_time", "ok": True}]
    assert isinstance(a.history[-1], AIMessage) and a.history[-1].content.startswith("It is 11:42.\n[tools this turn: get_time()")
    purposes = [r[0] for r in store._exec("SELECT purpose FROM llm_calls ORDER BY id")]
    assert purposes == ["agent_text", "agent_text"]


def test_time_is_said_without_a_second_llm_call(fake, monkeypatch):
    monkeypatch.setattr(config, "DIRECT_REPLY_TOOLS", {**config.DIRECT_REPLY_TOOLS, "get_time": "time"})
    calls = fake(call(), AIMessage(content="Let me know if you need anything else!"))
    out = agent.Agent().run("can you tell me what is time right now?")
    assert out.startswith("It's ") and ("AM" in out or "PM" in out) and len(calls) == 1  # the tool's sentence


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
    calls = fake(call("delete_to_trash", {"path": "/tmp/a"}), AIMessage(content="Okay, I did not delete it."))
    a = agent.Agent(confirm=lambda p: False)
    assert "not" in a.run("delete the file /tmp/a")
    assert store.recent_tool_calls(1)[0]["outcome"] == "denied"
    assert "declined" in calls[1]["messages"][-1].content


def test_unrouted_tool_is_refused(fake):
    fake(call("delete_to_trash", {"path": "/"}), AIMessage(content="Done."))
    agent.Agent(confirm=lambda p: True).run("what time is it")
    row = store.recent_tool_calls(1)[0]
    assert (row["tool"], row["outcome"]) == ("delete_to_trash", "error")


def test_round_limit_forces_answer(fake):
    calls = fake(call())  # always asks for the tool
    ans = agent.Agent().run("what time is it")
    assert ans == agent.TOO_MANY_ROUNDS
    assert len(calls) == config.AGENT_MAX_TOOL_ROUNDS + 1
    assert calls[-1].get("tools") is None  # final round sends NO tools (avoids the Groq "tool_choice none" 400)


def test_multi_group_uses_smart_tier(fake):
    calls = fake(AIMessage(content="Sure."))
    agent.Agent(use_planner=False).run("delete the file x and tell me the time")
    assert calls[0]["model"] == config.LLM_DEFAULT and len(calls[0]["tools"]) == len(registry.schemas_for(["files", "general"]))


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
    text = agent.SYSTEM_PROMPT + agent.SCREEN_SUFFIX + agent.VOICE_SUFFIX.format(lang="Nepali (Devanagari script)")
    assert len(text) / 4 < 250


def test_stale_turn_close_does_not_cut_next_turn(fake):
    fake(AIMessage(content="Once upon a time there was a fox."), AIMessage(content="I am doing well, thanks."))
    a = agent.Agent()
    old = a.stream("tell me a story", mode="voice", lang="en")
    next(old)  # the client left mid-reply; the generator is closed later (e.g. at GC)
    new = a.stream("how are you", mode="voice", lang="en")
    first = next(new)
    old.close()  # used to set the shared abort flag and cut the new reply after one word
    assert (first + "".join(new)).strip() == "I am doing well, thanks."
    assert [m.content for m in a.history if isinstance(m, AIMessage)] == ["I am doing well, thanks."]  # cut-off not kept


def test_refusal_on_a_task_offers_the_toolsmith(fake, monkeypatch):
    from jarvis.core import toolsmith
    seen = []
    monkeypatch.setattr(toolsmith, "handle", lambda task, **k: seen.append(task) or "The user said no, so no tool was made or run.")
    fake(AIMessage(content="I don't have a way to check that right now."),  # the request_tools retry first
         AIMessage(content="Sorry, I can't do that."), AIMessage(content="Okay, no problem."))
    a = agent.Agent()
    out = a.run("check my unread telegram messages")
    assert seen == ["check my unread telegram messages"] and out == "Okay, no problem."


def test_final_round_tool_choice_error_answers_from_tool_results(fake, monkeypatch):
    """gpt-oss still calls a tool on the tool-less final round -> Groq 400 'Tool choice is none'. That error reached
    the user; now the reply is what the tools already said."""
    fake(call())  # every round asks for get_time
    real = agent.Agent._chat

    def chat(self, msgs, kw, stream, hold=False):
        if kw.get("tools") is None:
            raise llm.LLMError("all models failed: Error code: 400 - Tool choice is none, but model called a tool")
        return real(self, msgs, kw, stream, hold)
    monkeypatch.setattr(agent.Agent, "_chat", chat)
    ans = agent.Agent().run("what time is it")
    assert ans and "went wrong" not in ans and "Tool choice" not in ans


@pytest.mark.parametrize("junk", [
    "Folder … has been …  …It seems…   …  … It…  … The  …",  # 7cb067220644
    "Your \u200b\u200b   ?  …...  ... ... ... ...",            # 4667e987aca6
    "Playing the \u200b\u200b  \u200b \u200b ……… We need to answer what is playing.",       # 9667c67e674a
])
def test_junk_stream_after_a_tool_is_replaced_by_the_tool_result(fake, junk):
    """gpt-oss-120b streams '… … …' / invisible spaces after a tool ran (14 of 191 replies): the junk is held back
    and the tool's own result is said instead."""
    fake(call(), AIMessage(content=junk))
    out = "".join(agent.Agent().stream("what time is it bro", mode="text"))
    assert "…" not in out and "\u200b" not in out and "We need" not in out
    assert len(out.strip()) > 5 and out.strip() == agent.last_result([]) or ":" in out


@pytest.mark.parametrize("ok", ["It is playing now... enjoy!", "Wait... it is 5 pm in Tokyo.", "Done, it's 9:15 pm."])
def test_a_normal_reply_with_one_ellipsis_streams_unchanged(fake, ok):
    fake(call(), AIMessage(content=ok))
    assert "".join(agent.Agent().stream("time in tokyo?", mode="text")).strip() == ok
