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
    assert f"/web_search{slash.NET_MARK}" in txt or f"/search" in txt
    off = slash.help_text(only_offline=True)
    assert "/make_folder" in off and "/web_search" not in off and "/poem" not in off


def test_online_tools_are_real_tools():
    assert not [n for n in slash.ONLINE_TOOLS if n not in slash.tool_cmds()]


def test_telegram_splits_a_long_reply(monkeypatch):
    from jarvis.core import notify
    from jarvis.workers import telegram_bot
    sent = []
    monkeypatch.setattr(notify, "telegram_call", lambda method, body: sent.append(body["text"]))
    bot = telegram_bot.TelegramBot.__new__(telegram_bot.TelegramBot)
    bot.send("\n".join(f"line {i} " + "x" * 60 for i in range(150)))
    assert 2 <= len(sent) <= 4 and all(len(s) <= config.TELEGRAM_MAX_REPLY_CHARS for s in sent)
