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
    assert i.args == {"action": "done", "n": 1}  # the reading list only (to-dos are their own list)
    assert readlater.run(**i.args).startswith("✔ Read: Second article")  # not the to-do "Reading the book"


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


def test_selection_help_from_the_log(monkeypatch):
    """Owner's 2:14 PM log: 'this word' heard as 'this wood' was translated literally, 'summary of this whole
    paragraph' went to the AI without the selection, explanations quoted the text back with silly word lists."""
    from jarvis.core import assist, rewrite
    i = fastpath.match("Convert this wood into Nepali.")
    assert i.args == {"action": "translate", "lang": "ne", "replace": False, "text": ""}
    assert fastpath.match("Can you give me the Nepali translation of this word?").args["action"] == "translate"
    i = fastpath.match("What is the summary of this whole paragraph? I mean, what is the main things that this paragraph want to say to me?")
    assert i.args == {"action": "summary", "lang": ""}
    assert fastpath.match("summarize this web page").tool == "page_summary"
    monkeypatch.setattr(rewrite, "grab", lambda: rewrite.Grab("readable", 5, False, False, "Doc - Brave"))
    seen = []
    monkeypatch.setattr(assist, "_llm", lambda system, user, smart, max_tokens, purpose: seen.append((purpose, user, smart)) or "ok")
    assist.run("translate", lang="ne", text="this wood")  # a pointer at the selection, not text to translate
    assert seen[-1][:2] == ("assist_translate", "readable")
    assist.run("summary", text="A long paragraph. " * 5)
    assert seen[-1][0] == "assist_summary" and seen[-1][2] is True
    assist.explain("The search found the right articles but read only the start.")
    assert seen[-1][2] is True and "No 'It says'" not in assist.EXPLAIN_RULES and "no 'It says'" in assist.EXPLAIN_RULES


def test_ask_about_selection_and_token_guard(monkeypatch):
    """Owner: 'give me code to test this function' (code highlighted in VS Code) asked 'please share the function';
    explanations must stay short and ASK before writing a long one."""
    from jarvis.core import assist, rewrite
    q = ("This is the function that I created in the python and I want a code to test this function. "
         "Can you give me the code for test this function?")
    assert fastpath.match(q).args == {"action": "ask", "request": q.rstrip("?")}
    assert fastpath.match("convert this function to javascript").args["action"] == "ask"
    assert fastpath.match("improve this code").args["action"] == "improve"
    code = "def calculator():\n    expr = input('x')\n    print(eval(expr))\n"
    monkeypatch.setattr(rewrite, "grab", lambda: rewrite.Grab(code, 5, False, False, "test.py - KURAMA - Visual Studio Code"))
    calls = []

    def fake(system, user, smart, max_tokens, purpose):
        calls.append((purpose, max_tokens, system, user))
        return "Short version.\n[more]" if purpose != "assist_more" else "# Full\nlong text"
    monkeypatch.setattr(assist, "_llm", fake)
    out = assist.run("ask", request=q)
    assert "from test import" in calls[-1][2] and calls[-1][1] == assist.SHORT_MAX["ask_code"] and "calculator" in calls[-1][3]
    assert out.endswith("Want me to write it (in the workspace)? Say yes.") and "[more]" not in out
    assert fastpath.match("yes").args == {"action": "more"}
    assert assist.run("more") == "# Full\nlong text" and calls[-1][1] == 1800 and not assist.more_waiting()
    assist.explain("A normal sentence that needs no long answer at all.")
    assert calls[-1][1] == assist.SHORT_MAX["explain"] and "[more]" in calls[-1][2]


def test_use_complete_and_code_chat_line(monkeypatch, tmp_path):
    """Owner: 'use this function' = only a run block put into the VS Code file; 'complete this code' finishes it
    (asks if unclear); 'test' = pytest; the chat says 'I wrote the tests ... in the workspace', never code lines."""
    from jarvis.core import assist, rewrite, workspace
    f = tmp_path / "test.py"
    f.write_text("def calculator():\n    return 1\n")
    monkeypatch.setattr(assist, "open_file_in_editor", lambda: f)
    g = rewrite.Grab("def calculator():\n    return 1\n", 5, False, False, "test.py - KURAMA - Visual Studio Code")
    monkeypatch.setattr(rewrite, "grab", lambda: g)
    monkeypatch.setattr(assist, "_llm", lambda *a, **k: "```python\nif __name__ == \"__main__\":\n    calculator()\n```\nNEEDS: none")
    assert fastpath.match("how can I use this function").args == {"action": "use"}
    out = assist.run("use")
    assert "calls calculator()" in out and out.endswith("Should I add it at the end of test.py? Say yes, or no.")
    assert "__main__" not in f.read_text()  # nothing written before the user says yes
    assert fastpath.match("yes").args == {"action": "use_yes"}
    assert assist.run("use_yes").startswith("Added at the end of test.py") and 'if __name__ == "__main__":' in f.read_text()
    assert "already has a run block" in assist.run("use")  # never twice
    # 'no' -> 'try again?' -> yes = a new, better attempt (the rejected one is sent as feedback)
    f.write_text("def calculator():\n    return 1\n")
    assist.run("use")
    assert fastpath.match("no").args == {"action": "use_no"}
    assert assist.run("use_no").startswith("Okay, I didn't add it. Should I try again")
    seen = []
    monkeypatch.setattr(assist, "_llm", lambda s, u, **k: seen.append(u) or "```python\nif __name__ == \"__main__\":\n    print(calculator())\n```\nNEEDS: none")
    assert fastpath.match("yes try again").args["action"] == "use_retry"
    assert "calls calculator()" in assist.run("use_retry") and "did NOT like this attempt" in seen[-1]
    # complete: unclear -> one question first, the reply continues the job
    monkeypatch.setattr(assist, "_llm", lambda *a, **k: "QUESTION: Should it also handle powers like 2**3?")
    assert assist.complete_code("def f(x):\n    ...\n", "").startswith("QUESTION:")
    assert fastpath.match("hey kurama can you complete this code").args["action"] == "complete"
    md = ("**`test_calculator.py`**\n\n```python\nimport pytest\nfrom test import calculator\n\ndef test_x():\n    pass\n```\n\n"
          "**How to run the tests**\n\n```bash\npytest -q test_calculator.py\n```")
    assert workspace.short_line(md) == ("I wrote the tests (test_calculator.py). It's in the workspace, you can check it there. "
                                        "Run them with: pytest -q test_calculator.py")


def test_use_block_with_unsaved_editor(monkeypatch, tmp_path):
    """Unsaved file (owner's case: test.py empty on disk, the code only in VS Code): the editor's current text is
    copied, the block added at its end, and the whole text pasted back (never Enter after an indented line)."""
    from jarvis.core import assist, rewrite, uiagent
    f = tmp_path / "test.py"
    f.write_text("")  # disk: empty
    buf = {"clip": ""}
    editor = "def calculator():\n    print('hi')\n"
    keys = []

    def xclip(args, text=None):
        if text is not None:
            buf["clip"] = text
            return ""
        return buf["clip"]

    def key(k):
        keys.append(k)
        if k == "ctrl+c":
            buf["clip"] = editor
    monkeypatch.setattr(rewrite, "_xclip", xclip)
    monkeypatch.setattr(rewrite, "_activate", lambda wid: None)
    monkeypatch.setattr(uiagent, "key", key)
    monkeypatch.setattr(assist, "open_file_in_editor", lambda: f)
    g = rewrite.Grab(editor, 7, False, False, "● test.py - KURAMA - Visual Studio Code")
    monkeypatch.setattr(rewrite, "grab", lambda: g)
    monkeypatch.setattr(assist, "_llm", lambda *a, **k: "if __name__ == \"__main__\":\n    calculator()\nNEEDS: none")
    assert "calls calculator()" in assist.run("use")
    pasted = {}
    orig = key

    def key2(k):
        if k == "ctrl+v":
            pasted["text"] = buf["clip"]
        orig(k)
    monkeypatch.setattr(uiagent, "key", key2)
    assert assist.run(**fastpath.match("Yes? Yes?").args).startswith("Added at the end of test.py. Save with Ctrl+S")
    assert pasted["text"] == "def calculator():\n    print('hi')\n\n\nif __name__ == \"__main__\":\n    calculator()\n"
    assert "Return" not in keys and f.read_text() == ""  # disk untouched; no Enter that could auto-indent


def test_generated_tests_are_run_and_fixed(monkeypatch):
    from jarvis.core import assist
    answer = "**`test_calc.py`**\n\n```python\ndef test_a():\n    assert 1 == 2\n```\n"
    runs = iter([(False, "E assert 1 == 2\n1 failed in 0.01s"), (True, "1 passed in 0.01s")])
    monkeypatch.setattr(assist, "_run_tests", lambda code, name, tests: next(runs))
    monkeypatch.setattr(assist, "_llm", lambda *a, **k: "```python\ndef test_a():\n    assert 1 == 1\n```")
    out = assist.verify_tests(answer, "def calc():\n    return 1\n", "calc")
    assert "assert 1 == 1" in out and out.endswith("✅ I ran them on a copy of your code: 1 passed in 0.01s.")
    for yes in ("Yes? Yes?", "Yeah, yeah, add it.", "हो", "ok yes"):
        assert fastpath.yes_no(yes) == "yes", yes
    for no in ("No no, leave it", "don't add it", "nope."):
        assert fastpath.yes_no(no) == "no", no
    assert fastpath.yes_no("open youtube") == ""
