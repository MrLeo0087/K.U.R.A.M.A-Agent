import pytest

from jarvis.core import config, fastpath, readlater, rewrite


@pytest.fixture
def rl(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "READ_LATER_FILE", str(tmp_path / "read_later.xlsx"))
    monkeypatch.setattr(readlater, "_title_for", lambda url: "Title of " + url.rsplit("/", 1)[-1])
    st = {"sel": "", "title": "Some page - Brave"}
    monkeypatch.setattr(rewrite, "target_window", lambda: (5, False))
    monkeypatch.setattr(rewrite, "_window_name", lambda wid: st["title"])
    monkeypatch.setattr(rewrite, "grab", lambda: rewrite.Grab(st["sel"], 5, False, False, st["title"]) if st["sel"]
                        else "I couldn't see any highlighted text")
    opened = []
    from jarvis.tools.general import open_url
    monkeypatch.setattr(open_url, "_open", opened.append)
    return st, opened


def test_selected_links_are_saved_to_excel(rl):
    st, _ = rl
    st["sel"] = "look at https://example.com/a and https://example.com/b."
    out = readlater.run("add")
    assert out == "Saved for later: Title of a\nSaved for later: Title of b"
    assert readlater.run("add") .startswith("Already in your reading list")
    from openpyxl import load_workbook
    ws = load_workbook(readlater.path()).active
    assert [c.value for c in ws[1]] == readlater.HEAD and ws.cell(2, 3).value == "https://example.com/b"


def test_open_page_from_browser_history(rl, monkeypatch):
    st, _ = rl
    st["title"] = "Attention Is All You Need - Brave"
    st["sel"] = "the key idea paragraph"  # highlighted text on the page, no link: kept as the note
    monkeypatch.setattr(readlater, "_history", lambda name, limit=300: [("https://arxiv.org/abs/1706.03762",
                                                                         "Attention Is All You Need")])
    assert readlater.run("add") == "Saved for later: Attention Is All You Need"
    r = readlater.unread()[0]
    assert r["type"] == "read" and r["note"] == "the key idea paragraph"


def test_list_open_read_remove(rl):
    st, opened = rl
    for x in ("x1", "x2", "x3"):
        readlater.add(f"https://e.com/{x}")
    assert readlater.show().startswith("📋 Your list (3)\n📖 Read later\n1. Title of x3 (e.com)") and "https://e.com/x3" in readlater.show()
    assert readlater.run("open", n=1) == "Opened: Title of x3 (done, removed from your list)." and opened == ["https://e.com/x3"]
    assert readlater.run("read", n=2) == "✔ Done: Title of x1 (removed). 1 left."  # done = deleted
    assert readlater.run("remove", n=1) == "Removed: Title of x2"
    assert readlater.show().startswith("Your list is empty")


def test_not_a_browser(rl):
    st, _ = rl
    st["title"] = "notes.txt - gedit"
    assert "Select a link" in readlater.run("add")


def test_routing(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    a = lambda t: fastpath.match(t).args
    assert a("I will read this later") == {"action": "add", "url": ""}
    assert a("add this to my reading list")["action"] == "add"
    assert a("what is on my reading list") == {"action": "list", "text": "read"}
    assert a("open number 3 from my reading list") == {"action": "open", "n": 3}
    assert a("mark 2 as read in my reading list") == {"action": "done", "n": 2}


def test_last_link_and_no_invented_links(rl, monkeypatch):
    st, _ = rl
    from jarvis.core import safety
    readlater.add("https://e.com/real")
    copied = []
    monkeypatch.setattr(rewrite, "_xclip", lambda a, text=None: copied.append(text))
    assert readlater.run("last").startswith("Title of real\nhttps://e.com/real") and copied == ["https://e.com/real"]
    # real bug: the AI called read_later(url='https://example.com') for 'keep this link for read later'
    monkeypatch.setattr(safety, "context", lambda: {"user_text": "Can you keep this link for read later?"})
    monkeypatch.setattr(readlater, "save_this", lambda *a: "saved the open page")
    assert readlater.run("add", "https://example.com") == "saved the open page"


def test_owner_phrasings(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    a = lambda t: (fastpath.match(t).tool, fastpath.match(t).args)
    assert a("Can you keep this link for read later?") == ("read_later", {"action": "add", "url": ""})
    # STT heard 'read later' as 'read letter'; it went to the screen reader
    assert a("Can you give me the read letter link that I gave you just a minute ago?") == ("read_later", {"action": "last"})
    assert a("show me all my read later links") == ("read_later", {"action": "list"})
    assert a("read this letter")[0] == "read_text"


def test_selected_link_words_use_the_html_href(rl, monkeypatch):
    """The owner selects a link on a page (its words, not its address) and says 'keep it for read later'."""
    st, _ = rl
    st["sel"] = "Attention Is All You Need"
    monkeypatch.setattr(readlater, "selected_links", lambda: [("https://arxiv.org/abs/1706.03762", "Attention Is All You Need")])
    assert readlater.run("add") == "Saved for later: Attention Is All You Need"
    assert readlater.unread()[0]["link"] == "https://arxiv.org/abs/1706.03762"


def test_comma_sentences_reach_read_later_through_the_agent(monkeypatch):
    """Real failure (3:09 PM): the multi-task splitter saw a comma, skipped the fast path, and the AI asked
    'give me the link' although the link was selected."""
    from jarvis.core import agent, llm, planner, safety
    monkeypatch.setattr(config, "FASTPATH", True)
    monkeypatch.setattr(llm, "chat", lambda *a, **k: pytest.fail("must not reach the AI"))
    ran = []
    monkeypatch.setattr(safety, "execute", lambda name, args, **k: ran.append((name, args)) or
                        safety.ToolResult(True, "Saved for later: X"))
    a = agent.Agent()
    for text in ("Okay, keep this link in read later, I will read this link later.",
                 "This link, put this link in the read later."):
        assert a.run(text) == "Saved for later: X", text
    assert [n for n, _ in ran] == ["read_later", "read_later"]
    assert planner.is_multi("open youtube and set a timer for 5 minutes")  # real multi-task still splits
    assert not planner.one_tool("open youtube and set a timer for 5 minutes")


def test_todo_list_tags_time_and_done(rl, monkeypatch):
    from jarvis.core import reminders, store
    readlater.add("https://e.com/paper")
    assert readlater.run("todo", text="buy milk", tag="#Shopping", when="in 2 hours").startswith(
        "Added to your to-do list: Buy milk #shopping. I'll remind you")
    assert readlater.run("todo", text="call Ram") == "Added to your to-do list: Call Ram."
    out = readlater.show()
    assert out.splitlines()[:3] == ["📋 Your list (3)", "✅ To-do", "1. Buy milk  #shopping  ⏰ " + out.splitlines()[2].split("⏰ ")[1]]
    assert "2. Call Ram" in out and "📖 Read later\n3. Title of paper (e.com)" in out
    assert readlater.show(tag="shopping").count("\n1. ") == 1 and "Call Ram" not in readlater.show(tag="shopping")
    sid = int(readlater.ordered()[0]["reminder"])
    row = next(r for r in store.schedules_list(enabled_only=True) if r["id"] == sid)
    assert row["kind"] == "task" and row["text"] == "todo: Buy milk"
    assert readlater.run("done", n=1).startswith("✔ Done: Buy milk (removed). 2 left.")
    assert sid not in [r["id"] for r in store.schedules_list(enabled_only=True)]  # its reminder is cancelled too
    assert "Not saved" in readlater.run("todo", text="x", when="January 1 2020 3 am")


def test_read_later_with_a_time_reminds_before_and_at_the_time(rl, monkeypatch):
    from jarvis.core import notify, reminders, store
    sent = []
    monkeypatch.setattr(notify, "notify", lambda title, text="", **k: sent.append((title, text)) or [])
    monkeypatch.setattr("jarvis.core.sound.play", lambda *a, **k: None)
    st, _ = rl
    st["sel"] = "https://e.com/deep"
    assert "I'll remind you" in readlater.run("add", when="in 2 hours")
    row = next(r for r in store.schedules_list(enabled_only=True) if r["kind"] == "task")
    assert reminders.heads_up(now=row["next_run"] - 9 * 60) == [row["id"]]
    assert sent[-1][0].startswith("🔔 In 9 min") and "You saved this to read at" in sent[-1][1] and "e.com/deep" in sent[-1][1]
    reminders.fire(row)
    assert sent[-1][0] == "📖 Read it now" and "https://e.com/deep" in sent[-1][1]


def test_random_nudge_for_items_without_a_time(rl, monkeypatch):
    import time as _t
    from jarvis.core import notify, store
    sent = []
    monkeypatch.setattr(notify, "notify", lambda title, text="", **k: sent.append((title, text, k)) or [])
    store.kv_set(readlater.NUDGE_KEY, "{}")
    readlater.add_todo("clean the room")
    noon = _t.mktime((2026, 10, 27, 12, 0, 0, 0, 0, -1))
    assert readlater.nudge(noon) is None  # first: picks a random moment later today
    nxt = __import__("json").loads(store.kv_get(readlater.NUDGE_KEY))["next"]
    assert noon < nxt <= noon + 4 * 3600
    body = readlater.nudge(nxt + 1)
    assert "Clean the room" in body and "done 1" in body and sent[-1][2]["source"] == "todo"
    late = _t.mktime((2026, 10, 27, 22, 30, 0, 0, 0, -1))
    assert readlater.nudge(late) is None  # never at night


def test_todo_routing():
    a = lambda t: fastpath.match(t).args  # noqa: E731
    assert a("add buy milk to my to-do list #shopping tomorrow 5 pm") == \
        {"action": "todo", "text": "buy milk", "tag": "shopping", "when": "tomorrow 5 pm"}
    assert a("save this in the read later and I can read this after 2 hours") == \
        {"action": "add", "url": "", "when": "after 2 hours"}
    assert a("keep this link for read later, november 28, 5 pm")["when"] == "november 28, 5 pm"
    assert a("I will read this at 2 pm") == {"action": "add", "url": "", "when": "at 2 pm"}
    assert a("show my to-do list") == {"action": "list", "text": "todo"}
    assert a("show my list #work") == {"action": "list", "tag": "work"}
    assert a("done 2") == {"action": "done", "n": 2} and a("mark 3 as complete") == {"action": "done", "n": 3}
    assert fastpath.match("what to do") is None and fastpath.match("done") is None


def test_one_list_has_reminders_and_follows_up_on_unfinished_tasks(rl, monkeypatch):
    import time as _t
    from jarvis.core import notify, reminders, store
    sent = []
    monkeypatch.setattr(notify, "notify", lambda title, text="", **k: sent.append((title, text)) or [])
    monkeypatch.setattr("jarvis.core.sound.play", lambda *a, **k: None)
    reminders.add("call mom", "in 3 hours", use_llm=False)
    readlater.add_todo("submit the form", when_text="in 1 hour")
    readlater.add("https://e.com/a")
    out = readlater.show()
    assert "⏰ Reminders\n1. call mom  ⏰" in out and "✅ To-do\n2. Submit the form" in out and "📖 Read later\n3." in out
    # the to-do's time comes: 'do it now', then an hour later 'not done yet' (only if still open)
    task = next(r for r in store.schedules_list() if r["kind"] == "task")
    reminders.fire(task)
    assert sent[-1][0] == "✅ Do it now" and "done 2" in sent[-1][1]
    follow = next(r for r in store.schedules_list() if r["text"].startswith(readlater.OVERDUE))
    assert follow["next_run"] == task["next_run"] + config.TASK_OVERDUE_S
    reminders.fire(follow)
    assert sent[-1][0] == "⏳ Not done yet" and "You haven't finished this yet" in sent[-1][1]
    # finishing it cancels the follow-up; a finished one is never nagged about
    assert readlater.run("done", n=2).startswith("✔ Done: Submit the form (removed)")
    assert not any(r["text"].startswith(readlater.OVERDUE) for r in store.schedules_list())
    assert reminders.fire({**follow, "id": 999}) == []
    # 'done 1' on a reminder cancels it
    assert readlater.run("done", n=1).startswith("✔ Done: call mom (reminder cancelled)")
    assert not [r for r in store.schedules_list() if r["kind"] == "reminder"]
