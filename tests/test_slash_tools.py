"""Every tool is a slash command ('/<tool> [action] <text>': no routing, no AI call to pick the tool), writing
commands ('/poem <topic>'), /list shows them all (laptop + Telegram), /offline only what works without internet."""
import pytest

from jarvis.core import config, fastpath, slash


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)


@pytest.mark.parametrize("text,tool,args", [
    ("/poem rain in kathmandu", "write_document", {"request": "a poem about rain in kathmandu"}),
    ("/essay nepal", "write_document", {"request": "an essay about nepal"}),
    ("/backup status", "backup", {"action": "status"}),
    ("/saved_links list", "saved_links", {"action": "list"}),
    ("/set_timer 5", "set_timer", {"minutes": 5.0}),
    ("/make_folder ~/Downloads/x1", "make_folder", {"path": "~/Downloads/x1"}),
    ("/batery_status", "battery_status", {}),  # a typo of a tool name
    ("/write_document a short note on AI", "write_document", {"request": "a short note on AI"}),
])
def test_a_tool_runs_straight_from_its_command(fast, text, tool, args):
    it = fastpath.match(text)
    assert (it.tool, it.args) == (tool, args)


@pytest.mark.parametrize("text", ["/essay", "/write_document"])
def test_a_command_without_its_text_says_how(fast, text):
    it = fastpath.match(text)
    assert it.tool == "_say" and "Usage: /" in it.args["en"]


def test_the_list_has_every_tool_and_marks_the_online_ones():
    txt = slash.help_text()
    assert "/poem" in txt and "/battery_status" in txt and "/make_folder" in txt
    assert f"/web_search{slash.NET_MARK}" in txt or "/search" in txt
    off = slash.help_text(only_offline=True)
    assert "/make_folder" in off and "/web_search" not in off and "/poem" not in off


def test_online_tools_are_real_tools():
    assert not [n for n in slash.ONLINE_TOOLS if n not in slash.tool_cmds()]


def test_telegram_splits_a_long_reply(monkeypatch):
    from jarvis.core import notify
    from jarvis.workers import telegram_bot
    sent, files = [], []

    def call(method, body, **kw):
        (sent.append(body["text"]) if method == "sendMessage" else files.append(kw["files"]["document"][1].read()))
    monkeypatch.setattr(notify, "telegram_call", call)
    bot = telegram_bot.TelegramBot.__new__(telegram_bot.TelegramBot)
    mid = "\n".join(f"line {i} " + "x" * 60 for i in range(80))  # ~5.5k: two messages, nothing cut
    bot.send(mid)
    import html
    import re as _re
    plain = [html.unescape(_re.sub(r"</?blockquote[^>]*>", "", s)) for s in sent]
    assert len(sent) == 2 and not files and all(len(s) <= config.TELEGRAM_MAX_REPLY_CHARS + 60 for s in sent)
    assert "<blockquote expandable>" in sent[0]  # the start shows, the rest folds behind "show more"
    assert "".join(plain).replace("\n", "") == mid.replace("\n", "")
    sent.clear()
    big = "\n".join(f"line {i} " + "x" * 60 for i in range(400))  # ~27k: the start + the WHOLE text as a web page
    bot.send(big)
    page = files[0].decode()
    assert len(sent) == 2 and "The whole answer is in the page below" in sent[-1]
    assert page.startswith("<!doctype html>") and "line 399 " in page
    sent.clear()
    bot.send("## Result\n\n| file | lines |\n|---|---|\n| app.js | 120 |\n| style.css | 40 |\n\n" + "word " * 200)
    assert "<b>Result</b>" in sent[0] and "<pre>file" in sent[0] and "app.js     120" in sent[0]  # a table, lined up
    sent.clear()
    bot.send("short <b> & fine")
    assert sent == ["short &lt;b&gt; &amp; fine"]
