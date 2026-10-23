import json

import pytest

from jarvis.core import agent, config, llm, store


class FakeLLM:
    """Stands in for llm.chat: pops scripted Replies, records each call."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, messages, tier="fast", stream=False, tools=None, **kw):
        self.calls.append({"messages": [dict(m) for m in messages], "tier": tier, "tools": tools,
                           "stream": stream, **kw})
        r = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if not stream:
            return r

        def gen():
            for word in r.text.split(" ") if r.text else []:
                yield word + " "
            return r
        return gen()


def call_time(i=1):
    return llm.Reply("", "m", [{"id": f"c{i}", "name": "get_time", "arguments": "{}"}])


@pytest.fixture
def fake(monkeypatch):
    def install(*replies):
        f = FakeLLM(replies)
        monkeypatch.setattr(llm, "chat", f)
        return f
    return install


def test_tool_call_then_answer(fake):
    f = fake(call_time(), llm.Reply("It is 11:42.", "m"))
    a = agent.Agent()
    assert a.run("what time is it?") == "It is 11:42."
    names = [t["function"]["name"] for t in f.calls[0]["tools"]]
    assert names == ["get_time"] and f.calls[0]["tier"] == "fast"
    second = f.calls[1]["messages"]
    assert second[-2]["tool_calls"][0]["function"]["name"] == "get_time"
    assert second[-1]["role"] == "tool" and second[-1]["tool_call_id"] == "c1"
    row = store.recent_tool_calls(1)[0]
    assert (row["tool"], row["outcome"], row["ok"]) == ("get_time", "allowed", 1)
    assert store.recent_routing(1)[0]["groups"] == ["general"]
    assert a.last["tools"] == [{"name": "get_time", "ok": True}]
    assert a.history[-1] == {"role": "assistant", "content": "It is 11:42."}


def test_stream_yields_final_answer(fake):
    f = fake(call_time(), llm.Reply("It is late.", "m"))
    a = agent.Agent()
    out = "".join(a.stream("what time is it?", mode="voice", lang="hi"))
    assert out.strip() == "It is late."
    assert "Hindi" in f.calls[0]["messages"][0]["content"]
    assert store.recent_tool_calls(1)[0]["tool"] == "get_time"


def test_chat_sends_no_tools(fake):
    f = fake(llm.Reply("I'm good, thanks!", "m"))
    assert agent.Agent().run("hi, how are you") == "I'm good, thanks!"
    assert len(f.calls) == 1 and f.calls[0]["tools"] is None
    assert store.recent_tool_calls(5) == []


def test_confirm_denied_through_agent(fake):
    delete = llm.Reply("", "m", [{"id": "d1", "name": "dummy_delete",
                                  "arguments": json.dumps({"path": "/tmp/a"})}])
    f = fake(delete, llm.Reply("Okay, I did not delete it.", "m"))
    a = agent.Agent(confirm=lambda p: False)
    assert "not" in a.run("delete the file /tmp/a")
    assert store.recent_tool_calls(1)[0]["outcome"] == "denied"
    assert "declined" in f.calls[1]["messages"][-1]["content"]


def test_unrouted_tool_is_refused(fake):
    sneaky = llm.Reply("", "m", [{"id": "x", "name": "dummy_delete", "arguments": '{"path": "/"}'}])
    fake(sneaky, llm.Reply("Done.", "m"))
    agent.Agent(confirm=lambda p: True).run("what time is it")
    row = store.recent_tool_calls(1)[0]
    assert (row["tool"], row["outcome"]) == ("dummy_delete", "error")


def test_round_limit_forces_answer(fake):
    f = fake(call_time())  # always asks for the tool
    ans = agent.Agent().run("what time is it")
    assert ans == agent.TOO_MANY_ROUNDS
    assert len(f.calls) == config.AGENT_MAX_TOOL_ROUNDS + 1
    assert f.calls[-1].get("tool_choice") == "none"


def test_multi_group_uses_smart_tier(fake):
    f = fake(llm.Reply("Sure.", "m"))
    agent.Agent().run("delete the file x and tell me the time")
    assert f.calls[0]["tier"] == "smart" and len(f.calls[0]["tools"]) == 2


def test_history_window_and_summary(fake, monkeypatch):
    monkeypatch.setattr(config, "HISTORY_TURNS", 2)
    monkeypatch.setattr(config, "AGENT_SUMMARY_BATCH_TURNS", 1)
    f = fake(llm.Reply("ok", "m"))
    a = agent.Agent(summarize_async=False)
    for i in range(4):
        a.run(f"hello {i}")
    assert len(a.history) == 4 and a.summary == "ok"
    purposes = [c.get("purpose") for c in f.calls]
    assert "summary" in purposes
    last = [c for c in f.calls if c.get("purpose", "").startswith("agent")][-1]
    assert "summary" in last["messages"][0]["content"] and len(last["messages"]) == 2 + 4


def test_system_prompt_is_short():
    text = agent.SYSTEM_PROMPT + agent.VOICE_SUFFIX.format(lang="Nepali (Devanagari script)")
    assert len(text) / 4 < 250
