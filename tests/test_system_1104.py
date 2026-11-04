"""11-04 afternoon traces: the AI got the wrong tools (18 tools reachable by none), shortcuts took wrong words, follow-
ups lost context, music had no seek / card, 👎 forced a correction."""
import pytest

from jarvis.core import config, fastpath, music, recipes, registry, spelling


def test_every_tool_is_offered_when_the_request_means_it(monkeypatch):
    """18 tools were reachable by no general tool (the AI could never use them, 11-04): each is offered when the
    request means it, and 'tracker' (money) goes to `life`, which has the expense tool."""
    from jarvis.core import semantic
    monkeypatch.setattr(config, "CORE_TOOLS", True)
    monkeypatch.setattr(config, "SEMANTIC_ROUTER", True)
    if not semantic.ensure_ready(30):
        pytest.skip("meaning model not available")
    R = registry.REGISTRY
    R._reach_cache = None
    reach = set().union(*R.reach().values())
    hidden = [n for n, t in R.tools.items() if registry.group_of(t) not in ("core", *config.AGENT_GROUPS) and n not in reach]
    for n in hidden:
        t = R.tools[n]
        assert n in [x.name for x in R.schemas_for([registry.group_of(t)], text=t.description)], n
    assert [t.name for t in R.schemas_for(["tracker"])][0] == "life"


@pytest.mark.parametrize("said,fixed", [("remain me to drink water in 2 min", "remind me to drink water in 2 min"),
                                        ("set 2000 budjet", "set 2000 budget"), ("stop alram", "stop alarm"),
                                        ("breakdown my expensive", "breakdown my expenses"),
                                        ("an expensive phone", "an expensive phone"), ("Kari Minati", "Kari Minati")])
def test_spelling(said, fixed):
    assert spelling.fix(said) == fixed


@pytest.mark.parametrize("said,tool,args", [
    ("what is speed of my internet", "internet_doctor", {"action": "speed"}),
    ("Lock laptop fast", "lock_screen", {}),
    ("turn on always on display", "laptop_toggle", {"setting": "stay_awake", "state": "on"}),
    ("let the screen sleep", "laptop_toggle", {"setting": "stay_awake", "state": "off"}),
    ("what is 10000 km in meter", "calculate", {"expression": "10000 km in meter"})])
def test_shortcuts_take_the_right_tool(said, tool, args):
    it = fastpath._match(said)
    assert it.tool == tool and it.args == args


@pytest.mark.parametrize("said", ["send this number in telegram as well", "send morning brief to telegram"])
def test_filler_is_never_the_message(said):
    assert fastpath.tg_message_text(said) is None


def test_type_here_and_greetings():
    from jarvis.core import templates, uiagent
    assert uiagent.parse_type("type hello here")["text"] == "hello"
    assert uiagent.parse_type("type I am here")["text"] == "I am here"
    assert templates.small_talk("type hello here") is None


def test_units_and_budget(tmp_path):
    from jarvis.tools.general.calculate import calculate
    assert calculate("what is 10000 km in meter") == "10,000 km = 10,000,000 m"
    assert calculate("convert 5 kilograms into grams") == "5 kg = 5,000 g"


def test_kept_answers_never_for_my_own_data():
    assert not recipes._cacheable({"text": "what is in my reminder ?", "answer": "one reminder", "path": "ai", "tools": "[]"})
    assert recipes._PERSONAL.search("do you know my name")


@pytest.mark.parametrize("spec,want", [("+30 seconds", (30.0, True)), ("-10 seconds", (-10.0, True)),
                                       ("1:30", (90, False)), ("2 minute", (120.0, False))])
def test_music_seek_times(spec, want):
    assert music.parse_time(spec) == want


@pytest.mark.parametrize("said,query", [("skip 30 seconds", "+30 seconds"), ("go back 10 seconds", "-10 seconds"),
                                        ("jump direct to 2 minutes", "2 minutes"), ("start from 1 minute", "1 minute")])
def test_music_seek_words(monkeypatch, said, query):
    monkeypatch.setattr(music, "running", lambda: True)
    assert fastpath.music_intent(said).args == {"action": "seek", "query": query}


def test_music_state_none_when_nothing_plays(monkeypatch):
    monkeypatch.setattr(music, "running", lambda: False)
    assert music.state() is None


def test_find_in_two_folders(tmp_path):
    from jarvis.tools.interactive.find_files import find_files
    (tmp_path / "a" / "kurama_x").mkdir(parents=True)
    (tmp_path / "b" / "kurama_y").mkdir(parents=True)
    out = find_files("kurama", f"{tmp_path / 'a'} and {tmp_path / 'b'}", "folder", 5)
    assert "kurama_x" in out and "kurama_y" in out


@pytest.mark.parametrize("said,tool,args", [
    ("Turn off laptop guard", "laptop_guard", {"action": "off"}), ("arm laptop guard", "laptop_guard", {"action": "on"}),
    ("show me my contact list", "contacts", {"action": "list"})])
def test_guard_and_contacts(said, tool, args):
    it = fastpath._match(said)
    assert it.tool == tool and it.args == args


def test_biggest_files_shortcut():
    assert fastpath.ranked_files_intent("show the 5 newest pdf files in documents").args == {
        "query": "*.pdf", "path": "documents", "kind": "name", "order": "newest", "limit": 5}


def test_budget_takes_number_and_category_from_the_text(monkeypatch):
    from jarvis.tools.general import expenses as tool
    got = []
    monkeypatch.setattr("jarvis.core.expenses.set_budget", lambda cat, amt: got.append((cat, amt)) or "ok")
    tool.expenses("budget", text="2000")
    tool.expenses("budget", text="clothes 500")
    assert got[0] == ("total", 2000.0) and got[1][1] == 500.0 and got[1][0] != "total"


def test_the_laptop_tool_reaches_the_whole_guard():
    from jarvis.tools.core import laptop
    from jarvis.tools.core._hub import resolve
    assert resolve(laptop.TABLE, {"action": "guard", "value": "off"}) == ("laptop_guard", {"action": "off"})


@pytest.mark.parametrize("said,name", [("find a function rate_limit in here", "rate_limit"),
                                       ("find rate_limit function", "rate_limit"),
                                       ("find the class RateLimiter in this project", "RateLimiter")])
def test_find_a_function_or_class_by_name(said, name):
    it = fastpath._match(said)
    assert it.tool == "code_nav" and it.args == {"action": "find", "name": name}


def test_the_closest_real_name_when_the_exact_one_is_missing(tmp_path):
    from jarvis.core import codenav
    (tmp_path / "limits.py").write_text("class RateLimiter:\n    pass\n\ndef load_state():\n    return 1\n")
    r = codenav.find("rate_limit", tmp_path, None)
    assert r["name"] == "RateLimiter" and r["line"] == 1
    assert codenav.find("load_sate", tmp_path, None)["name"] == "load_state"
    assert "error" in codenav.find("nothingatallxyz", tmp_path, None)


def test_caffeine_is_switched_by_the_key_it_listens_to(monkeypatch, tmp_path):
    """11-04: 'turn off always on display' wrote 'user-enabled' (only the login restore value), said "Caffeine is
    off", and the cup stayed on. The extension acts on 'cli-toggle'; KURAMA checks the switch took."""
    from jarvis.tools.general import laptop_toggle as L
    (tmp_path / "gschemas.compiled").write_text("x")
    monkeypatch.setattr(L, "_CAFFEINE", tmp_path)
    monkeypatch.setattr(L.time, "sleep", lambda s: None)
    state, cmds = {"cli-toggle": "true"}, []

    def run(argv, **kw):
        cmds.append(argv)
        if argv[3] == "set":
            state[argv[5]] = argv[6]
        return state.get(argv[5], "false")
    monkeypatch.setattr(L._sys, "run", run)
    assert L.laptop_toggle("stay_awake", "off").startswith("Okay: Caffeine is off")
    assert state["cli-toggle"] == "false" and not any("user-enabled" in c for c in cmds)
    monkeypatch.setattr(L._sys, "run", lambda argv, **kw: "true")  # the extension didn't follow: say so
    assert L.laptop_toggle("stay_awake", "off").startswith("error")


@pytest.mark.parametrize("said,state", [("turn on AOD", "on"), ("turn on always on display", "on"), ("enable always on", "on"),
                                        ("turn off AOD", "off"), ("AOD off", "off"), ("disable caffeine", "off"),
                                        ("turn off coffin", "off"), ("what is status of my AOD", "status"),
                                        ("is AOD on?", "status"), ("AOD status", "status")])
def test_aod_is_instant(said, state):
    it = fastpath._match(said)
    assert it.tool == "laptop_toggle" and it.args == {"setting": "stay_awake", "state": state}
