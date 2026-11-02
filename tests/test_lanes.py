"""Master plan phase 1: lanes by meaning. A confident general request (chat, knowledge, feelings) is one small-model
call with no tools; small talk in several parts is still a 0-token template; garbled speech is asked again at 0
tokens. Real phrasings from the 11-01 traces."""
import time

import pytest

from jarvis.core import agent, config, lanes, llm, router, semantic, stt, templates


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setattr(config, "SEMANTIC_ROUTER", True)  # conftest turns it off for every test
    if not semantic.ensure_ready(30):
        pytest.skip("meaning model not available")
    yield
    templates._st = lanes._mat = None  # other tests use a fake embedder (other size)


@pytest.mark.parametrize("text", ["Hello, bro. How are you?", "kya hora hai ?", "hello k xa khabaar", "i am sad today",
                                  "suggest one short name for a black cat", "do you know how can i happy ?",
                                  "Okay, go on."])
def test_chat_knowledge_and_feelings_are_general(model, text):
    assert lanes.is_general(text)


@pytest.mark.parametrize("text", ["open youtube", "What is my name?", "Make the volume 130.", "send hello to telegram",
                                  "who won today match ?", "write an essay about nepal", "done 2",
                                  "Tell me about yourself something.", "Can you tell me what do you know about me?",
                                  "Create new folder in here. Name new folder.", "Set the balloon in 100 maximum."])
def test_actions_data_and_memory_are_never_general(model, text):
    assert not lanes.is_general(text)


@pytest.mark.parametrize("text,want", [("Hello, bro. How are you?", "doing great"), ("Thanks. Thanks.", "Happy"),
                                       ("Hi.", "Hello"), ("Hello bro, how are you?", "doing great")])
def test_small_talk_in_several_parts_is_a_template(model, text, want):
    assert want in templates.small_talk(text)["en"]


@pytest.mark.parametrize("text", ["hello, open youtube", "thanks, now close it", "hello, what are you doing, and tell "
                                  "me the time"])
def test_small_talk_with_a_request_is_not_a_template(model, text):
    assert templates.small_talk(text) is None


def test_the_general_lane_is_one_call_without_tools_on_the_fast_model(monkeypatch):
    seen = []

    def chat(messages, stream=False, **kw):
        seen.append(kw)
        return llm.Reply("Gravity pulls things together.", "", [])
    monkeypatch.setattr(llm, "chat", chat)
    monkeypatch.setattr(router, "route", lambda t, log_it=True: router.Route([], "general"))
    assert agent.Agent().run("what is gravity, explain simply") == "Gravity pulls things together."
    assert len(seen) == 1 and not seen[0].get("tools") and seen[0]["tier"] == "voice"


@pytest.mark.parametrize("text", ["Islam Nizib", "Maximal Zabolom", "Please, there is still more to eat."])
def test_garbled_speech_is_asked_again_without_the_ai(monkeypatch, text):
    monkeypatch.setattr(stt, "_unsure", {"text": text.lower(), "at": time.time(), "unsure": True})
    monkeypatch.setattr(lanes, "scores", lambda t: {"general": 0.59, "auto": 0.6, "search": 0.5, "create": 0.5})
    monkeypatch.setattr(llm, "chat", lambda *a, **k: pytest.fail("no AI call for garbled speech"))
    assert agent.Agent().run(text, mode="voice") == agent.Agent.UNHEARD


def test_unsure_speech_that_means_an_action_still_runs(monkeypatch):
    text = "Upon SofaScore"
    monkeypatch.setattr(stt, "_unsure", {"text": text.lower(), "at": time.time(), "unsure": True})
    monkeypatch.setattr(lanes, "scores", lambda t: {"auto": config.STT_UNSURE_LANE_MIN + 0.02, "general": 0.6})
    assert agent.Agent()._unheard(text, "voice") is None
    assert agent.Agent()._unheard("Islam Nizib", "text") is None  # typed text is never "unheard"
