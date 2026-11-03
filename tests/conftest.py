import os

os.environ["KURAMA_TESTING"] = "1"  # set before anything runs and never removed: _sys refuses power commands

import pytest

from jarvis.core import config, jobs, llm, ratelimit, store


@pytest.fixture(autouse=True)
def tmp_store(tmp_path, monkeypatch):
    store.init(tmp_path / "test.db")
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(config, "TRACE_DB", tmp_path / "traces.db")  # never the real traces
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)  # never KURAMA's real data (backups, learned wordings...)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")  # never the real worker logs
    monkeypatch.setattr(config, "VSCODE_STATE_DIR", tmp_path / "vscode")  # never the real VS Code windows
    monkeypatch.setattr(config, "AGENT_MARKER", tmp_path / "agent")  # never switch the real VS Code terminal watch
    from jarvis import agents
    from jarvis.agents.coding import changes as _ch, terminal as _term
    agents._last_use[0] = 0.0
    _ch._pending.clear()
    _ch._cost.clear()
    _term._last.clear()
    _term._events.clear()
    from jarvis.core import browsertab
    monkeypatch.setattr(browsertab, "_SEL", {"text": "", "url": "", "title": "", "ts": 0.0})  # no highlight leaks
    monkeypatch.setattr(config, "JOBS_NOTIFY", False)  # never pop desktop notifications in tests
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")  # never message the real phone from a test
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")  # never call the real Gemini (Phase 3 tests opt in with fakes)
    monkeypatch.setattr(config, "TIER_CHAIN", {k: [m for m in v if not m.startswith("gemini")]
                                               for k, v in config.TIER_CHAIN.items()})
    llm._cool.clear()
    monkeypatch.setattr(config, "NOTIFY_DESKTOP", False)
    monkeypatch.setattr(config, "SOUNDS", False)  # no alarm sounds from tests
    monkeypatch.setattr(config, "CORE_TOOLS", False)  # old-tool tests see the specialised tools; v2 tests opt in
    monkeypatch.setattr(config, "FASTPATH", False)  # LLM-path tests stay on the LLM path; fastpath tests enable it
    monkeypatch.setattr(config, "SEMANTIC_ROUTER", False)
    monkeypatch.setattr(config, "CONTEXT", False)  # never read the real desktop (an open VS Code changed the tools)
    monkeypatch.setattr(config, "FILES_CONTEXT", False)  # ...nor the real Files app
    monkeypatch.setattr(config, "TRAINING_KEEP_AWAKE", False)  # never start a real systemd-inhibit from a test  # no embedding model in tests unless a test opts in
    # many tests drive the generic tool loop with get_time: the model words its answer there (opt back in per test)
    monkeypatch.setattr(config, "DIRECT_REPLY_TOOLS", {k: v for k, v in config.DIRECT_REPLY_TOOLS.items() if k != "get_time"})
    monkeypatch.setattr(config, "STT_LOG", tmp_path / "stt.log")  # never the real recognition log
    monkeypatch.setattr(config, "STT_DUAL", False)  # single-pass STT unless a test opts in
    monkeypatch.setattr(config, "JOB_RESOURCE_GATE", False, raising=False)  # P9b: jobs never wait on real RAM
    from jarvis.tools.general import open_url
    opened: list[str] = []
    monkeypatch.setattr(open_url, "_open", opened.append)  # never open the real browser
    from jarvis.tools.general import _sys

    def no_real_system(argv, *a, **k):
        raise AssertionError(f"real system command in a test: {argv}")
    monkeypatch.setattr(_sys, "_exec", no_real_system)  # never touch volume/brightness/lock/clipboard
    monkeypatch.setattr(config, "GOALS_FILE", str(tmp_path / "goals.xlsx"))  # never the real goals sheet
    monkeypatch.setattr(config, "READ_LATER_FILE", str(tmp_path / "read_later.xlsx"))  # never the real to-do list
    monkeypatch.setattr(config, "CONTACTS_FILE", str(tmp_path / "contacts.xlsx"))  # never the real contacts
    monkeypatch.setattr(config, "LINKS_FILE", str(tmp_path / "links.xlsx"))
    monkeypatch.setattr(config, "EXPENSES_FILE", str(tmp_path / "expenses.xlsx"))  # never the real money sheet
    monkeypatch.setattr(config, "BRIEF", False)  # the morning brief only where a test turns it on
    monkeypatch.setattr(config, "HABITS_FILE", str(tmp_path / "habits.xlsx"))
    monkeypatch.setattr(config, "GOALS_DIR", str(tmp_path / "goals"))
    monkeypatch.setattr(config, "SKILLS_DIR", tmp_path / "skills")  # P7c: never the real saved skills
    monkeypatch.setattr(config, "SANDBOX_DIR", tmp_path / "sandbox")
    from jarvis.core import toolsmith
    toolsmith._tried.clear()
    from jarvis.tools.general import _files
    trashed: list = []
    monkeypatch.setattr(_files, "trash", trashed.append)  # never move real files to the trash
    from jarvis.core import remotedesk
    monkeypatch.setattr(remotedesk, "_helper", lambda *a: (False, "test"))  # never touch the real RustDesk service/password
    ratelimit.reset()
    from jarvis.core import assist
    for pending in (assist._use, assist._more, assist._ask_back, assist._retry, assist._pending, assist._file_ref):
        pending.clear()  # in-memory 'waiting for yes' states never leak from one test into the next
    monkeypatch.setattr(assist, "_screen_chat", lambda: "")  # no screenshots / OCR of the real screen in tests
    from jarvis.core import coderun
    coderun._last_error.clear()
    from jarvis.core import recipes
    recipes.reset_cache()  # learned shortcuts are read again from this test's own data folder
    from jarvis.core import style
    style._dropped.clear()  # a rule forgotten in one test is not "just dropped" in the next
    from jarvis.core import music
    monkeypatch.setattr(music, "launch", lambda cmds, pipe=False, env=None: [])  # never start a real player (no sound from tests)
    monkeypatch.setattr(music, "_cache_dir", lambda: tmp_path)
    music.PLAYER.queue = []
    from jarvis.core import modes
    modes._cache = (0.0, {})  # the power mode is read from each test's own DB
    yield store
    jobs.reset_manager()
    ratelimit.reset()
    store.close()
    llm.set_client(None)
