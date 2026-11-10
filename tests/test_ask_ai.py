"""Plan 11-09 phase 5: 'ask Gemini / ChatGPT <question>' builds one prompt (question + selection + where it is),
opens the site in the browser for the extension to paste and send (0 KURAMA tokens); a follow-up goes to the same
chat; a question ABOUT ChatGPT is not sent to it."""
import json
from pathlib import Path

import pytest

from jarvis.agents.coding import bridge
from jarvis.core import askai, config, fastpath, semantic, store
from jarvis.tools.general import open_url


@pytest.fixture
def env(monkeypatch):
    kv, opened = {}, []
    monkeypatch.setattr(store, "kv_get", lambda k: kv.get(k))
    monkeypatch.setattr(store, "kv_set", lambda k, v: kv.__setitem__(k, v))
    monkeypatch.setattr(open_url, "_open", lambda url: opened.append(url))
    from jarvis.core import rewrite
    monkeypatch.setattr(rewrite, "_xclip", lambda *a, **k: "")
    return kv, opened


def _ctx(monkeypatch, **c):
    base = {"selection": "", "where": "", "around": "", "lang": ""}
    monkeypatch.setattr(askai, "context", lambda: {**base, **c})


def test_the_prompt_has_the_question_the_selection_and_where_it_is(env, monkeypatch):
    _, opened = env
    _ctx(monkeypatch, selection="loss.backward()", where="the file `train.py` (lines 40-40)",
         around="opt.zero_grad()\nloss.backward()\nopt.step()", lang="py")
    out = askai.ask("ask gemini why this works")
    pid = opened[0].split("#kurama=")[1]
    prompt = bridge.take_prompt(pid)
    assert opened[0].startswith("https://gemini.google.com/app#kurama=") and "Gemini" in out
    assert prompt.startswith("Why this works") and "train.py" in prompt and "```py\nloss.backward()" in prompt \
        and "opt.step()" in prompt


def test_a_follow_up_goes_to_the_same_chat_without_the_selection_again(env, monkeypatch):
    _, opened = env
    _ctx(monkeypatch, selection="some paragraph", where='the web page "Attention" (https://x)')
    askai.ask("ask chatgpt what this means")
    askai.ask("ask it simpler")
    assert opened[1].startswith("https://chatgpt.com/#kurama=") and opened[1].endswith("&same=1")
    assert bridge.take_prompt(opened[1].split("#kurama=")[1].split("&")[0]) == "Simpler"


def test_the_default_site_and_nothing_to_ask(env, monkeypatch):
    kv, opened = env
    _ctx(monkeypatch)
    assert "What should I ask Gemini" in askai.ask("ask the ai")
    assert askai.set_default("chat gpt") == "'Ask the AI' now goes to ChatGPT."
    askai.ask("ask the ai what is a tensor")
    assert opened[-1].startswith("https://chatgpt.com/")


def test_the_words_are_read_right():
    assert askai.site_of("ask Chat GPT why") == "chatgpt" and askai.site_of("ask bard") == "gemini"
    assert askai.question_of("ask claude to explain this in nepali") == "Explain this in nepali"
    assert askai.addressed("ask gemini why") and not askai.addressed("how does chatgpt work")
    assert not askai.addressed("ask claude code to fix the tests")  # Claude Code on this laptop, not claude.ai


def test_routing_by_meaning(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    monkeypatch.setattr(config, "SEMANTIC_ROUTER", True)
    if not semantic.ensure_ready(30):
        pytest.skip("meaning model not available")
    semantic._tables.clear()
    try:
        for text, site in (("ask gemini why this works", "gemini"), ("ask chatgpt how to fix this error", "chatgpt"),
                           ("ask claude to explain this function in nepali", "claude"),
                           ("ask gemini what is backpropagation", "gemini"),
                           # 11-10 voice traces (they were answered by KURAMA, not sent)
                           ("Can you ask this to the Gemini that what is meaning of this sentence?", "gemini"),
                           ("Ask to the chat LGBT that what is the meaning of this sentence.", "chatgpt"),
                           ("Can you ask to the chat GPT what is propagation?", "chatgpt")):
            it = fastpath.match(text)
            assert it is not None and it.tool == "ask_ai" and it.args["site"] == site, text
        for text in ("how does chatgpt work", "open gemini", "go to claude code"):
            it = fastpath.match(text)
            assert it is None or it.tool != "ask_ai", text
    finally:
        semantic._tables.clear()


def test_a_question_of_its_own_does_not_carry_an_old_highlight(env, monkeypatch):
    _, opened = env
    _ctx(monkeypatch, selection="https://www.facebook.com/reel/1")
    askai.ask("ask gemini what is backpropagation")
    assert bridge.take_prompt(opened[0].split("#kurama=")[1]) == "What is backpropagation"


def test_sending_it_is_the_whole_answer():
    """11-10: the AI sent the question to ChatGPT and then answered it itself; the tool's sentence ends the turn."""
    assert config.DIRECT_REPLY_TOOLS.get("ask_ai") == "said"


def test_tidy_preview_says_what_tidy_means(monkeypatch, tmp_path):
    from jarvis.core import automation
    monkeypatch.setattr(automation.Path, "home", lambda: tmp_path)
    (tmp_path / "Downloads").mkdir()
    monkeypatch.setattr(automation, "sort_plan", lambda folder=None: [(tmp_path / "Downloads/a.png", tmp_path / "Downloads/Images")])
    out = automation.sort_preview()
    assert out.startswith("🗂 Tidy Downloads = put the loose files") and "a.png → Downloads/Images" in out
