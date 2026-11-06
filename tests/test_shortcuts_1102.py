"""Master plan phase 3: requests the 11-01 traces sent to the AI that are fixed commands or clear meaning actions:
volume to a number (also above 100) / "more volume", close all tabs, list the tabs, key combos; a name-slot action
needs the word all its examples share ('Open sitting.' is not 'open the X tab')."""
import pytest

from jarvis.core import config, fastpath, lanes, meta, semantic, templates


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)


def _fresh():
    """Embeddings cached by other tests' fake model (another size) must not meet the real one."""
    from jarvis.core import lanes as _l, meta as _m, templates as _t
    _t._st = _l._mat = _m._claim_mat = None
    semantic._tables.clear()


@pytest.fixture
def model(fast, monkeypatch):
    monkeypatch.setattr(config, "SEMANTIC_ROUTER", True)
    _fresh()
    if not semantic.ensure_ready(30):
        pytest.skip("meaning model not available")
    yield
    _fresh()  # other tests use a fake embedder (other size)


@pytest.mark.parametrize("text,args", [("Make the volume 130.", {"action": "set", "level": 130}),
                                       ("make volume to 130%", {"action": "set", "level": 130}),
                                       ("keep the volume at 40", {"action": "set", "level": 40}),
                                       ("Increase the more volume.", {"action": "up"}),
                                       ("increase the volume more", {"action": "up"}),
                                       ("reduce the volume a bit", {"action": "down"})])
def test_volume_commands(fast, text, args):
    it = fastpath.match(text)
    assert it.tool == "volume" and it.args == args


@pytest.mark.parametrize("text,keys", [("Press Alt and Tab key together.", "alt+Tab"), ("press ctrl and t at once", "ctrl+t"),
                                       ("Press Alt Tab Key", "alt+Tab")])
def test_key_combos(text, keys):
    from jarvis.core import uiagent
    assert uiagent.keys_from_words(uiagent.parse_press(text)["keys"]).lower() == keys.lower()


@pytest.mark.parametrize("text", ["close all tabs", "Close all tab.", "close every tab in my browser"])
def test_close_all_tabs_closes_the_browser(model, text):
    it = fastpath.match(text)
    assert (it.tool, it.args) == ("app_control", {"action": "shortcut", "text": "close_tabs:all"})


@pytest.mark.parametrize("text", ["Give me the list of the tab open in my browser.", "what tabs are open",
                                  "tell me the tabs open in my browser"])
def test_list_tabs(model, text):
    it = fastpath.match(text)
    assert it.tool == "app_control" and it.args["text"] == "tabs"


@pytest.mark.parametrize("text", ["Open sitting.", "open notes", "show me the weather"])
def test_a_tab_switch_needs_the_word_tab(model, text):
    it = fastpath.match(text)
    assert it is None or not str(it.args.get("text", "")).startswith(("tab:", "close_tab:"))


def test_a_tab_by_name_still_switches(model):
    it = fastpath.match("switch to the facebook tab")
    assert it.args["text"] == "tab:facebook"
