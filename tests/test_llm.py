from types import SimpleNamespace as NS

import groq
import httpx
import pytest

from jarvis.core import config, llm, store

REQ = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
MSGS = [{"role": "user", "content": "hi"}]


def err(status, headers=None):
    resp = httpx.Response(status, headers=headers or {}, request=REQ)
    cls = {429: groq.RateLimitError, 500: groq.InternalServerError, 503: groq.InternalServerError,
           400: groq.BadRequestError}[status]
    return cls(f"status {status}", response=resp, body=None)


def completion(text, p=7, c=3):
    msg = NS(content=text, tool_calls=None)
    return NS(choices=[NS(message=msg)], usage=NS(prompt_tokens=p, completion_tokens=c))


def chunk(text=None, usage=None):
    ch = [NS(delta=NS(content=text, tool_calls=None))] if text is not None else []
    return NS(choices=ch, x_groq=NS(usage=usage) if usage else None, usage=None)


class FakeClient:
    """Replays a script of results (exception or value) per call; records models used."""

    def __init__(self, script):
        self.script = list(script)
        self.models = []
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kw):
        self.models.append(kw["model"])
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return iter(item) if kw["stream"] else item


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "_sleep", calls.append)
    return calls


def rows():
    return store._exec("SELECT model, ok, total_tokens, estimated FROM llm_calls ORDER BY id")


def test_non_stream_retry_honors_retry_after(sleeps):
    fc = FakeClient([err(429, {"retry-after": "2"}), err(503), completion("hello")])
    llm.set_client(fc)
    r = llm.chat(MSGS, tier="fast", purpose="t")
    assert r.text == "hello" and r.model == config.LLM_FAST
    assert sleeps[0] == 2.0 and len(sleeps) == 2
    assert [tuple(x) for x in rows()] == [(config.LLM_FAST, 0, 0, 0)] * 2 + [(config.LLM_FAST, 1, 10, 0)]


def test_smart_falls_back_to_fast_on_repeated_429(sleeps):
    fc = FakeClient([err(429), err(429), completion("from fast")])
    llm.set_client(fc)
    r = llm.chat(MSGS, tier="smart")
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


def test_non_retryable_raises_immediately(sleeps):
    fc = FakeClient([err(400)])
    llm.set_client(fc)
    with pytest.raises(llm.LLMError):
        llm.chat(MSGS, tier="smart")
    assert fc.models == [config.LLM_DEFAULT] and sleeps == []


def test_streaming_deltas_and_usage(sleeps):
    stream = [chunk("Hel"), chunk("lo"), chunk(usage=NS(prompt_tokens=11, completion_tokens=2))]
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
    llm.set_client(FakeClient([[chunk("abcdefgh")]]))
    assert "".join(llm.chat(MSGS, stream=True)) == "abcdefgh"
    model, ok, total, est = rows()[-1]
    assert ok == 1 and est == 1 and total > 0


def test_parse_duration():
    assert llm._parse_duration("2m59.5s") == pytest.approx(179.5)
    assert llm._parse_duration("120ms") == pytest.approx(0.12)
    assert llm._parse_duration("7") == 7.0
