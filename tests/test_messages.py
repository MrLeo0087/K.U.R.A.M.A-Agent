import time

from jarvis.core import fastpath, inbox
from jarvis.workers.msg_watch import parse_block


def test_parse_dbus_block_multiline_body():
    block = ["method call time=1 sender=:1.5 -> destination=:1.4 serial=9 path=/org/freedesktop/Notifications; "
             "interface=org.freedesktop.Notifications; member=Notify",
             '   string "Brave"', "   uint32 0", '   string ""', '   string "Ram Sharma"',
             '   string "<a href=\\"https://web.whatsapp.com/\\">web.whatsapp.com</a>', "", 'Are you coming?"',
             "   array [", "   ]", "   int32 -1"]
    app, summary, body = parse_block(block)
    assert (app, summary) == ("Brave", "Ram Sharma") and body.endswith("Are you coming?")
    assert inbox.classify(app, summary, body) == ("whatsapp", "Ram Sharma", "Are you coming?")
    assert inbox.classify("Brave", "x", "example.com\n\nhi") is None
    assert inbox.classify("Thunderbird", "Boss", "Report due")[0] == "email"


def test_store_filter_unread(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox.config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(inbox, "tab_counts", lambda: {})
    monkeypatch.setattr(inbox, "imap_unread", lambda limit=5: None)
    assert inbox.add("whatsapp", "Ram", "hi")
    assert not inbox.add("whatsapp", "Ram", "hi")  # D-Bus relay duplicate
    inbox.add("instagram", "sita_k", "hello")
    inbox.add("email", "Old", "x", ts=time.time() - 100 * 3600)
    out = inbox.report("whatsapp")
    assert "[WhatsApp] Ram: hi" in out and "sita_k" not in out
    assert "No new WhatsApp" in inbox.report("whatsapp")  # marked read after showing
    assert "sita_k" in inbox.report(sender="sita")
    assert "[WhatsApp] Ram" in inbox.report(unread=False)
    inbox.prune()
    assert not inbox.query("email", hours=200)


def test_intents():
    assert fastpath.match("any new whatsapp messages").args == {"action": "unread", "source": "whatsapp",
                                                               "sender": ""}
    assert fastpath.match("what did Ram send on whatsapp").args["sender"] == "Ram"
    assert fastpath.match("check my email").args["source"] == "email"
    assert fastpath.match("message me on telegram") is None or \
        fastpath.match("message me on telegram").tool != "messages"
