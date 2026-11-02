"""Master plan phase 2: each tool waits as long as its own runs need before going to the background, a tool-less
answer that MEANS "done" is caught, and an image request with no subject (or a typo) is still one 0-token call."""
import json
import time

import pytest

from jarvis.core import config, fastpath, lanes, meta, safety, semantic, store, templates


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setattr(config, "SEMANTIC_ROUTER", True)
    if not semantic.ensure_ready(30):
        pytest.skip("meaning model not available")
    yield
    templates._st = lanes._mat = meta._claim_mat = None


@pytest.mark.parametrize("runs,want", [([], 3.0), ([4.0, 4.5, 5.0], 6.25), ([2.6, 2.9, 3.1, 3.3], 4.125),
                                       ([9.0, 12.0, 15.0], 8.0), ([0.2, 0.3, 0.4], 3.0)])
def test_a_tool_waits_for_its_own_usual_run_time(runs, want):
    safety._waits.clear()
    store.kv_set(safety._RUNS_KEY, json.dumps({"live_search": runs}))
    assert safety._wait_for("live_search") == pytest.approx(want)


def test_real_run_times_are_remembered_even_after_the_background():
    safety._waits.clear()
    for s in (5.1, 4.2, 6.0):
        safety._ran("music", s)
    assert json.loads(store.kv_get(safety._RUNS_KEY))["music"] == [5.1, 4.2, 6.0]
    assert safety._wait_for("music") == pytest.approx(7.5)


@pytest.mark.parametrize("answer", ["Here is a cozy four-room house plan with a central balcony walkway in your workspace.",
                                    "Music volume 85%.", "I made a new folder called \"new folder\" in KURAMA/data."])
def test_a_toolless_answer_that_means_done_is_a_claim(model, answer):
    assert meta.claims(answer)


@pytest.mark.parametrize("answer", ["The sky looks blue because the air scatters sunlight.", "Shadow.",
                                    "Namaste, sabai thik cha! How can I help you today?", "It's 9:16 AM in Kathmandu.",
                                    "Here is a short poem: rain falls softly on the roof.",
                                    "I'm sorry you're feeling this way. Want to talk about what's on your mind?"])
def test_answers_are_not_claims(model, answer):
    assert not meta.claims(answer)


@pytest.mark.parametrize("text,prompt", [("generate a random image and send to telegram", "surprising"),
                                         ("generate iamge of futurestic computer and send it to telegram", "futurestic"),
                                         ("create a cute image", "cute")])
def test_image_with_no_subject_or_a_typo_is_one_call(monkeypatch, text, prompt):
    monkeypatch.setattr(config, "FASTPATH", True)
    it = fastpath.match(text)
    assert it.tool == "generate_image" and prompt in it.args["prompt"]
    assert bool(it.args.get("send_to_telegram")) == ("telegram" in text)


def test_an_image_of_nothing_is_asked_by_the_ai(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    it = fastpath.match("generate an image")
    assert it is None or it.tool != "generate_image"
