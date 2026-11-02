"""11-02 trace report P1: Gemini's thought signatures survive the tool round, a used-up Gemini quota is skipped (no
retry, cooled until it resets), and a refused key is said plainly."""
import time

import pytest
from langchain_core.messages import AIMessage

from jarvis.core import agent, config, llm, router
from tests.test_llm import MSGS, FakeClient, err
from tests.test_p7c import Responder

GEM, LITE = "gemini-2.5-flash", "gemini-flash-lite-latest"
QUOTA = "Error calling model (RESOURCE_EXHAUSTED): 429 RESOURCE_EXHAUSTED. You exceeded your current quota"


@pytest.mark.parametrize("text,least", [(QUOTA + " GenerateRequestsPerDayPerProjectPerModel-FreeTier", 3600),
                                        (QUOTA + " 'retryDelay': '700s'", 700), (QUOTA, config.LLM_COOLDOWN_S)])
def test_a_used_up_gemini_quota_is_skipped_without_a_retry(monkeypatch, text, least):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "TIER_CHAIN", {**config.TIER_CHAIN, "voice": [GEM, LITE]})
    llm._cool.clear()
    asked = []

    def make(model):
        def fn(messages, kw):
            asked.append(model)
            if model == GEM:
                raise RuntimeError(text)
            return AIMessage(content="from lite")
        return Responder(model_id=model, fn=fn)
    monkeypatch.setattr(llm, "_gemini", make)
    llm._models.pop(GEM, None), llm._models.pop(LITE, None)
    assert llm.chat(MSGS, tier="voice").text == "from lite"
    assert llm.chat(MSGS, tier="voice").text == "from lite"
    assert asked == [GEM, LITE, LITE]  # one try, then skipped (was: 2 tries on every request)
    assert llm._cool[GEM] - time.time() >= least - 5
    llm._cool.clear()


def test_the_voice_chain_has_both_gemini_models(monkeypatch):
    if config.GEMINI_API_KEY:
        assert config.TIER_CHAIN["voice"][-2:] == [GEM, LITE]


def test_gemini_signatures_survive_the_tool_round(monkeypatch):
    sig = {"__gemini_function_call_thought_signatures__": {"c1": "c2lnbmF0dXJl"}}
    seen = []

    def chat(messages, stream=False, **kw):
        seen.append(messages)
        if len(seen) == 1:
            msg = AIMessage(content=[{"type": "text", "text": ""}], additional_kwargs=sig,
                            tool_calls=[{"name": "get_time", "args": {}, "id": "c1"}])
            return llm.Reply("", GEM, [{"id": "c1", "name": "get_time", "arguments": "{}"}], message=msg)
        return llm.Reply("It's noon.", GEM, [], message=AIMessage(content="It's noon."))
    monkeypatch.setattr(llm, "chat", chat)
    monkeypatch.setattr(router, "route", lambda t, log_it=True: router.Route(["general"], "semantic"))
    agent.Agent().run("what is the time in tokyo right now please")
    ai = [m for m in seen[-1] if isinstance(m, AIMessage) and m.tool_calls]
    assert ai and ai[0].additional_kwargs == sig  # was rebuilt without them: Gemini 400 on every next call


@pytest.mark.parametrize("e,want", [("Error code: 401 - {'error': {'message': 'Invalid API Key'}}", "key was refused"),
                                    ("429 RESOURCE_EXHAUSTED quota", "busy or rate-limited"),
                                    ("connection reset", "went wrong")])
def test_what_the_owner_hears_when_every_model_failed(e, want):
    assert want in llm.user_text(llm.LLMError(e))
