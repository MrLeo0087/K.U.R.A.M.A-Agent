import pytest

from jarvis.core import config, fastpath, links, rewrite, store


@pytest.fixture
def desk(monkeypatch):
    """A fake desktop: what is highlighted, which browser page is open (no real windows or clipboard)."""
    monkeypatch.setattr(config, "FASTPATH", True)
    st = {"sel": "", "title": "Claude Code - Brave", "page": ("https://claude.com/claude-code", "Claude Code")}
    monkeypatch.setattr(rewrite, "target_window", lambda: (5, False))
    monkeypatch.setattr(rewrite, "_window_name", lambda wid: st["title"])
    monkeypatch.setattr(rewrite, "grab", lambda: rewrite.Grab(st["sel"], 5, False, False, st["title"]) if st["sel"]
                        else "I couldn't see any highlighted text")
    monkeypatch.setattr(rewrite, "_xclip", lambda args, text: None)
    from jarvis.core import readlater
    monkeypatch.setattr(readlater, "current_page", lambda title: st["page"])
    monkeypatch.setattr(readlater, "selected_links", lambda: [])
    return st


def run(text):
    i = fastpath.match(text)
    assert i and i.tool == "saved_links", (text, i)
    return links.run(**i.args)


def test_save_open_page_with_a_name_and_get_it_later(desk):
    assert run("this is the link for the Claude Code, save it for later").startswith("Saved 'Claude Code': https://claude.com/claude-code")
    desk["page"] = ("https://www.facebook.com/", "Facebook")
    assert run("this is a link for my Facebook, save it").startswith("Saved 'Facebook'")
    assert run("give me the link of my facebook") == "Facebook: https://www.facebook.com/ (copied)"
    assert run("what's my claude code link").startswith("Claude Code: https://claude.com/claude-code")
    opened = []
    from jarvis.tools.general import open_url
    open_url._open = opened.append
    assert run("open my facebook link").startswith("Opening Facebook") and opened == ["https://www.facebook.com/"]
    assert "1. Claude Code" in run("show my saved links")


def test_not_saved_goes_to_the_ai(desk):
    i = fastpath.match("give me the link of my grok")
    assert i is None or i.tool != "saved_links"  # the AI answers from its own knowledge


def test_no_name_asks_for_one_then_the_reply_is_the_name(desk):
    out = run("store the link of this in your memory")
    assert out.endswith("What should I call this link?") and links.pending()
    assert run("grep.claude.code").startswith("Saved 'grep.claude.code'") and links.pending() is None
    run("save this link")
    assert run("call it docs").startswith("Saved 'docs'")
    run("save this link")
    assert run("never mind") == "Okay, I didn't save it."


def test_say_it_name_and_highlighted_link(desk):
    assert run("store the link of this in your memory and say it grep.claude.code").startswith("Saved 'grep.claude.code'")
    desk["sel"] = "see https://grok.com/chat here"
    assert run("save this link as grok").startswith("Saved 'grok': https://grok.com/chat")
    assert run("save this link as grok").startswith("Updated 'grok'")


def test_no_link_found_asks_to_select(desk):
    desk["page"] = None
    assert run("save this link as notes").startswith("I couldn't find a link. Select the link")


def test_rename_delete(desk):
    run("save this link as cc")
    assert run("rename the cc link to Claude Code") == "Renamed 'cc' to 'Claude Code'."
    assert run("delete the claude code link") == "Removed the 'Claude Code' link."
    assert run("show my links").startswith("No saved links")


def test_stores_never_mix_up(desk, monkeypatch):
    """Owner: KURAMA must not confuse the link store, contacts, to-do, read later, reminders and long goals."""
    from jarvis.core import goals
    run("save this link as facebook")
    goals.add("Exam", "in 30 days")
    want = {
        "this is the link for my github, save it": "saved_links",
        "give me my facebook link": "saved_links",
        "show my saved links": "saved_links",
        "save this link for later": "read_later",
        "read this later": "read_later",
        "what's on my reading list": "read_later",
        "add buy milk to my to-do list": "read_later",
        "show my to-do list": "read_later",
        "save Ram's number 9800000000": "contacts",
        "what is Ram's number": "contacts",
        "show my contacts": "contacts",
        "remind me to call mom at 5 pm": "add_reminder",
        "my exam is in 30 days, remind me every day": "goals",
        "show my goals": "goals",
        "how many days until my exam": "goals",
        "remove the exam goal": "goals",
    }
    for text, tool in want.items():
        i = fastpath.match(text)
        assert i and i.tool == tool, (text, i and i.tool)
    assert store  # (fixtures keep everything in temp files)


def test_open_website_looks_in_the_link_store(desk):
    from jarvis.tools.general import open_url
    desk["page"] = ("https://leo.dev/portfolio", "My portfolio")
    run("save this link as portfolio")
    desk["page"] = ("https://www.facebook.com/groups/kurama", "KURAMA group")
    run("save this link as facebook")
    assert open_url.resolve("portfolio") == "https://leo.dev/portfolio"  # unknown to the built-in list
    assert open_url.resolve("my portfolio website") == "https://leo.dev/portfolio"
    assert open_url.resolve("facebook") == "https://www.facebook.com/groups/kurama"  # the user's own link wins
    assert open_url.resolve("youtube") == "https://www.youtube.com"
    i = fastpath.match("open portfolio")
    assert i.tool == "open_url" and i.args == {"target": "portfolio"}


def test_digest_at_10_pm():
    from jarvis.workers import daily_digest
    assert daily_digest.digest_time().hour == 22
