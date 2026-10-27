"""Owner's 12:05-12:12 PM log: noise heard as Russian/Portuguese, talk mode silently dropping requests, page reading
stuck on an old link, 'I already read X' starting OCR, small talk / setup guides costing tokens."""
import pytest

from jarvis.core import config, fastpath, readlater, stt


@pytest.fixture(autouse=True)
def fp(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)


def T(text, raw, lp):
    return stt.Transcript(text, "en", "m", raw, 1.0, 1, lp, 0.0)


@pytest.mark.parametrize("text,raw,lp,keep", [
    ("Japanese open with other than a", "tamil", -1.24, False), ("E aí", "portuguese", -1.10, False),
    ("Продолжение следует...", "russian", -0.25, False), ("The", "english", -1.99, False), ("RUN", "english", -1.88, False),
    ("Hello", "indonesian", -0.42, True), ("Reduce the laptop brightness.", "english", -0.35, True),
    ("आज कति गते", "nepali", -0.5, True)])
def test_only_english_nepali_hindi_get_through(text, raw, lp, keep):
    t = T(text, raw, lp)
    assert (stt.not_ours(t, t) == "") is keep
    out = stt._gate(T(text, raw, lp), T(text, raw, lp))
    assert (out.text == text) is keep


def test_talk_mode_requests_are_not_room_talk():
    from jarvis.api.turns import addressed
    for q in ("Can you tell me what this page is about?", "Tell me a joke", "Open YouTube", "is there any task for me"):
        assert addressed(q), q
    assert not addressed("and then he said the match was boring")


def test_page_questions_read_the_current_tab(monkeypatch):
    for q in ("look the screen and tell me what this website is about and what is showing ?",
              "now look at this page and tell me what this about ?", "summarize this web page"):
        assert fastpath.match(q).args == {"action": "summary"}, q
    from jarvis.core import pageread, llm, rewrite
    monkeypatch.setattr(rewrite, "target_window", lambda: (5, False))
    monkeypatch.setattr(rewrite, "_window_name", lambda wid: "Usage - GroqCloud - Brave")
    monkeypatch.setattr(readlater, "current_page", lambda title: ("https://console.groq.com/usage", "Usage - GroqCloud"))
    from jarvis.tools.general import read_webpage
    monkeypatch.setattr(read_webpage, "read_webpage", lambda url, max_chars=3000: "Usage\n" + "tokens per day 1234. " * 40)
    monkeypatch.setattr(llm, "chat", lambda msgs, **k: "GroqCloud usage: tokens per day.")
    out = pageread.summary()
    assert out == "GroqCloud usage: tokens per day.\nWant a detailed overview? Say yes."
    assert fastpath.match("yes").args == {"action": "detail"}
    assert fastpath.match("no thanks").args == {"action": "cancel"}


def test_already_read_marks_the_reading_list(monkeypatch):
    monkeypatch.setattr(readlater, "_title_for", lambda url: "Attention is All you Need")
    readlater.add("https://proceedings.neurips.cc/x", "Attention is All you Need")
    readlater.add_todo("Reading the book")
    i = fastpath.match("i already read attention al lyou need paper")
    assert i.tool == "read_later" and readlater.run(**i.args).startswith("Removed: Attention is All you Need")
    readlater.add("https://example.com/b", "Second article")
    i = fastpath.match("mark first task in read later as done")
    assert i.args == {"action": "done", "n": 1, "text": "read"}
    assert readlater.run(**i.args).startswith("✔ Done: Second article")  # not the to-do 'Reading the book'


@pytest.mark.parametrize("q", ["how is your day going", "what are you doing", "set up the colab notebook",
                               "set up the environment for a python project", "give me a whole python project setup",
                               "how do I create a virtual environment in python"])
def test_ready_answers_cost_zero_tokens(q):
    i = fastpath.match(q)
    assert i and i.tool == "_say" and i.args["en"], q
