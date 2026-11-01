"""llm.py on ChatGroq: a fake raw Groq client replays dict responses, so the real LangChain
path (message conversion, bind_tools, streaming, usage_metadata, callbacks) is exercised."""
from types import SimpleNamespace as NS

import groq
import httpx
import pytest
from langchain_core.messages import HumanMessage

from jarvis.core import config, llm, registry, store

REQ = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
MSGS = [{"role": "user", "content": "hi"}]


def err(status, headers=None):
    resp = httpx.Response(status, headers=headers or {}, request=REQ)
    cls = {429: groq.RateLimitError, 500: groq.InternalServerError, 503: groq.InternalServerError,
           400: groq.BadRequestError}[status]
    return cls(f"status {status}", response=resp, body=None)


def completion(text, p=7, c=3, tool_calls=None):
    msg = {"role": "assistant", "content": text}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"id": "x", "model": "m", "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": p, "completion_tokens": c, "total_tokens": p + c}}


def chunk(text=None, usage=None):
    delta = {"role": "assistant", "content": text} if text is not None else {}
    out = {"id": "x", "model": "m",
           "choices": [{"index": 0, "delta": delta, "finish_reason": None if text else "stop"}]}
    if usage:
        out["x_groq"] = {"usage": usage}
    return out


class FakeClient:
    """Replays a script of results (exception or value) per call; records requests."""

    def __init__(self, script):
        self.script = list(script)
        self.models, self.requests = [], []
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kw):
        self.models.append(kw["model"])
        self.requests.append(kw)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return iter(item) if kw.get("stream") else item


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "_sleep", calls.append)
    return calls


def rows():
    return store._exec("SELECT model, ok, total_tokens, estimated FROM llm_calls ORDER BY id")


def test_model_settings_from_config():
    llm.set_client(FakeClient([]))
    m = llm.model_for(config.LLM_FAST)
    assert m.max_retries == 0 and m.reasoning_effort == "low" and m.reasoning_format == "hidden"
    assert llm.model_for(config.LLM_FAST) is m  # cached
    assert llm.model_for(config.LLM_VOICE).reasoning_effort == "none"
    assert llm.model_settings("x") == {}


def test_non_stream_retry_honors_retry_after(sleeps):
    fc = FakeClient([err(429, {"retry-after": "2"}), completion("hello")])
    llm.set_client(fc)
    r = llm.chat(MSGS, tier="fast", purpose="t")
    assert r.text == "hello" and r.model == config.LLM_FAST and r.message.content == "hello"
    assert sleeps[0] == 2.0 and len(sleeps) == 1
    assert [tuple(x) for x in rows()] == [(config.LLM_FAST, 0, 0, 0), (config.LLM_FAST, 1, 10, 0)]
    req = fc.requests[-1]
    assert req["reasoning_format"] == "hidden" and req["max_tokens"] == config.LLM_MAX_TOKENS
    assert store._exec("SELECT purpose FROM llm_calls ORDER BY id DESC LIMIT 1")[0][0] == "t"


def test_smart_falls_back_to_fast_on_repeated_429(sleeps):
    fc = FakeClient([err(429), err(429), completion("from fast")])
    llm.set_client(fc)
    r = llm.chat([HumanMessage(content="hi")], tier="smart")
    assert fc.models == [config.LLM_DEFAULT, config.LLM_DEFAULT, config.LLM_FAST]
    assert r.model == config.LLM_FAST and r.text == "from fast"


def test_long_retry_after_skips_straight_to_fallback(sleeps):
    fc = FakeClient([err(429, {"retry-after": "120"}), completion("ok")])
    llm.set_client(fc)
    assert llm.chat(MSGS, tier="smart").model == config.LLM_FAST and sleeps == []


def test_budget_exhausted_skips_smart(monkeypatch):
    monkeypatch.setitem(config.DAILY_TOKEN_BUDGET, config.LLM_DEFAULT, 10)
    store.log_llm(config.LLM_DEFAULT, "t", 10, 0, 1, True)
    fc = FakeClient([completion("ok")])
    llm.set_client(fc)
    llm.chat(MSGS, tier="smart")
    assert fc.models == [config.LLM_FAST]


def test_non_retryable_falls_back_to_next_model(sleeps):
    # a non-retryable error (e.g. a 400) on one model now falls back to the next model instead of giving up
    fc = FakeClient([err(400), completion("recovered")])
    llm.set_client(fc)
    r = llm.chat(MSGS, tier="smart")
    assert r.text == "recovered" and r.model == config.LLM_FAST
    assert fc.models == [config.LLM_DEFAULT, config.LLM_FAST] and sleeps == []


def test_raises_only_when_all_models_fail(sleeps):
    fc = FakeClient([err(400), err(400), err(400)])  # all three models in the smart chain fail
    llm.set_client(fc)
    with pytest.raises(llm.LLMError):
        llm.chat(MSGS, tier="smart")
    assert fc.models == [config.LLM_DEFAULT, config.LLM_FAST, config.LLM_VISION]


def test_bind_tools_and_tool_call_parsing():
    tc = [{"id": "c1", "type": "function", "function": {"name": "get_time", "arguments": "{}"}}]
    fc = FakeClient([completion("", tool_calls=tc)])
    llm.set_client(fc)
    tools = registry.schemas_for(["general"])
    r = llm.chat(MSGS, tools=tools, tool_choice="none")
    assert r.message.tool_calls[0]["name"] == "get_time" and r.tool_calls[0]["arguments"] == "{}"
    req = fc.requests[0]
    assert [t["function"]["name"] for t in req["tools"]] == [t.name for t in tools]
    assert req["tool_choice"] == "none"


def test_streaming_deltas_and_usage(sleeps):
    stream = [chunk("Hel"), chunk("lo"), chunk(usage={"prompt_tokens": 11, "completion_tokens": 2,
                                                      "total_tokens": 13})]
    fc = FakeClient([err(500), stream])
    llm.set_client(fc)
    gen = llm.chat(MSGS, stream=True, purpose="s")
    out = []
    try:
        while True:
            out.append(next(gen))
    except StopIteration as stop:
        reply = stop.value
    assert out == ["Hel", "lo"] and reply.text == "Hello" and not reply.estimated
    assert tuple(rows()[-1]) == (config.LLM_FAST, 1, 13, 0)


def test_streaming_estimates_without_usage():
    llm.set_client(FakeClient([[chunk("abcdefgh"), chunk()]]))
    assert "".join(llm.chat(MSGS, stream=True)) == "abcdefgh"
    model, ok, total, est = rows()[-1]
    assert ok == 1 and est == 1 and total > 0


def test_stream_abort_is_logged():
    llm.set_client(FakeClient([[chunk("one "), chunk("two"), chunk()]]))
    gen = llm.chat(MSGS, stream=True, purpose="a")
    assert next(gen) == "one "
    gen.close()
    assert tuple(store._exec("SELECT ok, error, estimated FROM llm_calls ORDER BY id DESC LIMIT 1")[0]) \
        == (1, "aborted", 1)


def test_get_chat_model_has_fallbacks():
    llm.set_client(FakeClient([completion("hey")]))
    r = llm.get_chat_model("smart", purpose="g").invoke("hi")
    assert r.content == "hey" and rows()[-1][1] == 1


def test_parse_duration():
    assert llm._parse_duration("2m59.5s") == pytest.approx(179.5)
    assert llm._parse_duration("120ms") == pytest.approx(0.12)
    assert llm._parse_duration("7") == 7.0
