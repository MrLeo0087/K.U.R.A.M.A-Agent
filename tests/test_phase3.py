"""Phase 3: Gemini after Groq's models (before qwen), a used-up model is skipped instead of failing first on every
request, and token cuts (short actions end without a second AI call, the text tool only when the request means the
open file, 'send hello to telegram' is a 0-token action)."""
import pytest
from langchain_core.messages import AIMessage, ToolMessage

from jarvis.core import agent, config, fastpath, llm, semantic
from tests.test_llm import MSGS, FakeClient, completion, err
from tests.test_p7c import Responder, human, names, respond, roots, tc, tg  # noqa: F401  (fixtures)

GEM = "gemini-2.5-flash"


def test_a_used_up_model_is_skipped_on_the_next_requests(monkeypatch):
    monkeypatch.setattr(config, "TIER_CHAIN", {**config.TIER_CHAIN, "fast": [config.LLM_FAST, config.LLM_DEFAULT]})
    fake = FakeClient([err(429, {"retry-after": "600"}), completion("from 120b"), completion("again 120b")])
    llm.set_client(fake)
    assert llm.chat(MSGS, tier="fast").text == "from 120b"
    assert llm.chat(MSGS, tier="fast").text == "again 120b"
    assert fake.models == [config.LLM_FAST, config.LLM_DEFAULT, config.LLM_DEFAULT]  # 20b not asked again
    assert llm._cool[config.LLM_FAST] > 0


def test_every_model_cooling_down_still_tries(monkeypatch):
    monkeypatch.setattr(config, "TIER_CHAIN", {**config.TIER_CHAIN, "fast": [config.LLM_FAST]})
    import time
    llm._cool[config.LLM_FAST] = time.time() + 999
    fake = FakeClient([completion("limit reset early")])
    llm.set_client(fake)
    assert llm.chat(MSGS, tier="fast").text == "limit reset early"


def test_gemini_answers_when_groq_is_used_up(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "TIER_CHAIN", {**config.TIER_CHAIN, "fast": [config.LLM_FAST, GEM, config.LLM_VISION]})
    seen = []

    def fn(messages, kw):
        seen.append(kw)
        return AIMessage(content="from gemini")
    monkeypatch.setattr(llm, "_gemini", lambda model: Responder(model_id=model, fn=fn))
    llm.set_client(FakeClient([err(429, {"retry-after": "900"})]))
    r = llm.chat(MSGS, tier="fast", max_tokens=99)
    assert (r.text, r.model) == ("from gemini", GEM)
    assert seen[0].get("max_output_tokens") == 99 and "max_tokens" not in seen[0]  # Gemini's own name


@pytest.mark.parametrize("msg,code", [("429 RESOURCE_EXHAUSTED. Quota exceeded", 429),
                                      ("504 DEADLINE_EXCEEDED. Deadline expired", 504),
                                      ("UNAVAILABLE: model overloaded", 503), ("invalid argument", None)])
def test_gemini_error_codes(msg, code):
    assert llm._status(RuntimeError(msg)) == code


def test_gemini_is_after_groq_and_before_qwen():
    import importlib
    import os
    old = os.environ.get("GEMINI_API_KEY")
    os.environ["GEMINI_API_KEY"] = "test-key"
    try:
        cfg = importlib.reload(config)
        for tier in ("fast", "smart"):
            chain = cfg.TIER_CHAIN[tier]
            assert chain.index(cfg.LLM_GEMINI) > chain.index(cfg.LLM_FAST)
            assert chain.index(cfg.LLM_GEMINI) < chain.index(cfg.LLM_VISION)
    finally:
        if old is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = old
        importlib.reload(config)


# --- token cuts ---
@pytest.mark.parametrize("text", ["create a folder reports in my projects", "make folder reports there",
                                  "new folder reports please"])
def test_a_short_action_ends_without_a_second_ai_call(respond, roots, text):  # noqa: F811
    calls = []

    def fn(messages, kw):
        calls.append(1)
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content="I created it.")
        return tc("make_folder", {"path": str(roots / "reports")})
    respond(fn)
    ans = agent.Agent(confirm=lambda p: True, use_planner=False).run(text)
    assert ans == f"Created folder {roots / 'reports'}" and len(calls) == 1


def test_a_longer_request_lets_the_ai_go_on(respond, roots):  # noqa: F811
    calls = []

    def fn(messages, kw):
        calls.append(1)
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content="Made the project folder; next I'd add the files.")
        return tc("make_folder", {"path": str(roots / "flask_app")})
    respond(fn)
    agent.Agent(confirm=lambda p: True, use_planner=False).run(
        "set up a small flask project for me in a new folder called flask_app with an app file and templates")
    assert len(calls) == 2


@pytest.mark.parametrize("best,scores,want", [
    (("use", 0.65), [("telegram", 1.0), ("clipboard", 0.75)], False),  # send hello to telegram
    (("explain", 0.95), [("codequality", 0.88), ("clipboard", 0.75)], True),  # what is this code doing
    (("use", 0.75), [("files", 0.79), ("clipboard", 0.70)], True),  # write a function in this file
    (("use", 0.78), [("reminders", 0.96), ("clipboard", 0.73)], False)])  # remind me at 5
def test_the_text_tool_comes_only_when_the_request_means_the_open_file(monkeypatch, best, scores, want):
    monkeypatch.setattr(semantic, "ready", lambda: True)
    monkeypatch.setattr(semantic, "best_of", lambda t, n, table: best)
    monkeypatch.setattr(semantic, "scores", lambda t: scores)
    assert agent._about_context("x") is want


@pytest.mark.parametrize("text,msg", [("send hello to telegram", "hello"), ("Send good morning to my Telegram.", "good morning"),
                                      ("message me on telegram saying dinner is ready", "dinner is ready"),
                                      ("bro send hi to my telegram ..", "hi"), ("telegram me buy milk", "buy milk"),
                                      ("can you send good night on telegram", "good night")])
def test_telegram_message_text(text, msg):
    assert fastpath.tg_message_text(text) == msg


@pytest.mark.parametrize("text", ["send it to telegram", "send my location to telegram", "send report.pdf to telegram",
                                  "send this link to telegram", "send the essay to telegram",
                                  "send /home/leo/a.txt to telegram", "send https://x.com to telegram"])
def test_a_thing_to_send_is_never_sent_as_words(text):
    assert fastpath.tg_message_text(text) is None


def test_a_big_photo_is_shrunk_before_the_upload(tmp_path, roots, tg):  # noqa: F811
    from PIL import Image
    from jarvis.tools.general import send_file_telegram as sft
    big = tmp_path / "dog.png"
    Image.effect_noise((2400, 1600), 60).convert("RGB").save(big)  # noisy: a real-size file (~MBs)
    small = tmp_path / "icon.jpg"
    Image.new("RGB", (64, 64), "red").save(small)
    data = sft._small_photo(big)
    with Image.open(__import__("io").BytesIO(data)) as im:
        assert max(im.size) == config.TELEGRAM_PHOTO_PX and im.format == "JPEG"
    assert len(data) < big.stat().st_size / 3
    assert sft._small_photo(small) == small.read_bytes()  # small photos go as they are
    txt = tmp_path / "notes.png"
    txt.write_bytes(b"not an image" * 30000)
    assert sft._small_photo(txt) == txt.read_bytes()  # not a real image: sent unchanged
    assert sft.deliver(big) == "Sent to your Telegram." and tg[-1][0] == "sendPhoto"
