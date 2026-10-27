from jarvis.core import fastpath, slash
from jarvis.workers import telegram_bot


def test_commands_unique_and_valid():
    names = [n for c in slash.COMMANDS for n in (c.name, *c.aliases)]
    assert len(names) == len(set(names))
    assert all(c.cat in slash.CATS and c.desc for c in slash.COMMANDS)
    for c in slash.COMMANDS:  # every phrase-command really hits the 0-token fast path
        bare = slash.phrase_for(c, "")
        if bare:
            assert fastpath.match(bare) is not None, (c.name, bare)


def test_expansion_typos_and_paths():
    m = fastpath.match
    assert m("/weather pokhara").args == {"place": "pokhara", "days": 1}
    assert m("/todo buy milk").args == {"action": "todo", "text": "buy milk"}
    assert m("/wether").tool == "weather" and m("/plya").args == {"action": "play"}
    assert m("/search python asyncio").args == {"query": "python asyncio"}
    assert "Usage: /search" in m("/search").args["en"]
    assert m("/def calc").args == {"action": "find", "name": "calc"}
    assert m("/focus 50").args["minutes"] == 50
    assert "/list" in m("/qqqzzz").args["en"]
    assert m("/home/leo/report.pdf") is None  # a path, not a command
    help_md = m("/list").args["en"]
    assert "`/weather [place]`" in help_md and "**Code**" in help_md


def test_telegram_menu_and_all():
    menu = telegram_bot.menu()
    names = [c for c, _ in menu]
    assert len(names) == len(set(names)) <= 100 and {"list", "all", "weather", "def", "play"} <= set(names)
    assert all(c.islower() and len(c) <= 32 for c in names)
    assert "/all" in telegram_bot.HELP
    assert "/weather" in slash.help_text() and "**" not in slash.help_text()


def test_api_catalog():
    from fastapi.testclient import TestClient
    from jarvis.api.app import create_app
    from tests.test_api import BASE, settings
    r = TestClient(create_app(settings()), base_url=BASE).get("/api/v1/slash")
    cmds = r.json()["commands"]
    assert r.status_code == 200 and any(c["cmd"] == "weather" and c["hint"] == "[place]" for c in cmds)
