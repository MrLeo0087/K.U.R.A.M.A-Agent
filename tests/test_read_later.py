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
    assert [c.value for c in ws[1]] == readlater.HEAD and ws.cell(2, 2).value == "https://example.com/b"


def test_open_page_from_browser_history(rl, monkeypatch):
    st, _ = rl
    st["title"] = "Attention Is All You Need - Brave"
    st["sel"] = "the key idea paragraph"  # highlighted text on the page, no link: kept as the note
    monkeypatch.setattr(readlater, "_history", lambda name, limit=300: [("https://arxiv.org/abs/1706.03762",
                                                                         "Attention Is All You Need")])
    assert readlater.run("add") == "Saved for later: Attention Is All You Need"
    r = readlater.unread()[0]
    assert r["site"] == "arxiv.org" and r["note"] == "the key idea paragraph" and r["status"] == "unread"


def test_list_open_read_remove(rl):
    st, opened = rl
    for x in ("x1", "x2", "x3"):
        readlater.add(f"https://e.com/{x}")
    assert readlater.show().startswith("Reading list (3 unread):\n1. Title of x3") and "https://e.com/x3" in readlater.show()
    assert readlater.run("open", n=1) == "Opened: Title of x3 (marked as read)." and opened == ["https://e.com/x3"]
    assert readlater.run("read", n=2) == "Marked as read: Title of x1"
    assert readlater.run("remove", n=1) == "Removed: Title of x2"
    assert readlater.show().startswith("Your reading list is empty")


def test_not_a_browser(rl):
    st, _ = rl
    st["title"] = "notes.txt - gedit"
    assert "Select a link" in readlater.run("add")


def test_routing(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    a = lambda t: fastpath.match(t).args
    assert a("I will read this later") == {"action": "add", "url": ""}
    assert a("add this to my reading list")["action"] == "add"
    assert a("what is on my reading list") == {"action": "list"}
    assert a("open number 3 from my reading list") == {"action": "open", "n": 3}
    assert a("mark 2 as read in my reading list") == {"action": "read", "n": 2}


def test_last_link_and_no_invented_links(rl, monkeypatch):
    st, _ = rl
    from jarvis.core import safety
    readlater.add("https://e.com/real")
    copied = []
    monkeypatch.setattr(rewrite, "_xclip", lambda a, text=None: copied.append(text))
    assert readlater.run("last").startswith("Title of real\nhttps://e.com/real") and copied == ["https://e.com/real"]
    # real bug: the AI called read_later(url='https://example.com') for 'keep this link for read later'
    monkeypatch.setattr(safety, "context", lambda: {"user_text": "Can you keep this link for read later?"})
    monkeypatch.setattr(readlater, "save_this", lambda: "saved the open page")
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
