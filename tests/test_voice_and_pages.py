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


def test_coding_projects_list_pin_forget(tmp_path):
    import json
    from jarvis.core import store, timemachine as tm
    for n in ("KURAMA", "civic-report", "Dummpy"):
        (tmp_path / n).mkdir()
    store.kv_set("tm_added", json.dumps([str(tmp_path / n) for n in ("KURAMA", "civic-report", "Dummpy")]))
    assert fastpath.match("list my coding projects").args == {"action": "list"}
    assert fastpath.match("pin the kurama project").args == {"action": "pin", "project": "kurama"}
    assert fastpath.match("stop watching the dummpy project").args == {"action": "forget", "project": "dummpy"}
    tm.pin("kurama")
    assert tm.resolve("").name == "KURAMA"
    assert tm.forget("dummpy").startswith("I stopped watching Dummpy") and (tmp_path / "Dummpy").is_dir()
    assert [p.name for p in tm.projects()] == ["KURAMA", "civic-report"]
    assert tm.unforget("dummpy") == "Watching Dummpy again."
    assert "(you pinned it)" in tm.overview()


def test_where_was_i_is_not_a_folder_path():
    i = fastpath.match("where was I?")
    assert i.tool == "where_was_i" and i.name != "where"  # the 'The full path is ...' template is for folders only


def test_only_projects_the_user_gave_are_watched(tmp_path):
    import json
    from jarvis.core import store, timemachine as tm
    (tmp_path / "old").mkdir()
    (tmp_path / "mine").mkdir()
    store.kv_set("tm_found", json.dumps([str(tmp_path / "old")]))  # found on disk: NOT watched any more
    assert tm.projects() == []
    assert fastpath.match(f"watch the project at {tmp_path / 'mine'}").args == {"action": "protect", "project": str(tmp_path / "mine")}
    store.kv_set("tm_added", json.dumps([str(tmp_path / "mine")]))
    assert [p.name for p in tm.projects()] == ["mine"]
    assert fastpath.match("stop watching").args == {"action": "forget", "project": ""}
    assert tm.forget("").startswith("Which one? I'm watching:\n1. mine")
    assert tm.forget("#1").startswith("I stopped watching mine") and tm.projects() == []


def test_rankings_read_the_numbered_block_and_use_one_source(monkeypatch):
    """Owner: 'top 10 Ballon d'Or 2026' came back half invented (only 1800 chars of 2 pages were read)."""
    from jarvis.core import live, llm
    page = "Intro.\n" * 40 + "RankPlayerNationalityClub\nWINNERHarry KaneEnglandBayern Munich\n" + \
        "\n".join(f"{i}.Player {i}Country{i}Club{i}" for i in range(2, 11)) + "\nAfter the list."
    block = live.relevant(page, "top 10 ballon d'or 2026", 2200)
    assert "WINNERHarry Kane" in block and "10.Player 10" in block and block.count("Intro.") <= 4
    monkeypatch.setattr(live, "news", lambda q, k=5, days=1: [])
    monkeypatch.setattr(live, "_web_recent", lambda q, k=5: [{"title": "Top 10", "url": "https://s.example/top10", "snippet": "x"}])
    monkeypatch.setattr(live, "_article_text", lambda url, limit=1800, question="": block)
    seen = {}
    from types import SimpleNamespace
    monkeypatch.setattr(llm, "chat", lambda msgs, **k: seen.update(k, sys=msgs[0]["content"]) or
                        SimpleNamespace(text="Page: s.example (OFFICIAL)\n1. Harry Kane"))
    out = live.answer("who are top 10 ranking for ballon d'or 2026")
    assert seen["tier"] == "smart" and "ONE page" in seen["sys"] and "Never fill a gap" in seen["sys"]
    assert out.startswith("Page: s.example (OFFICIAL)")
