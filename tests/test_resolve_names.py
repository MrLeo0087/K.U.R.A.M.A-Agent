"""Master plan phase 4: names are resolved, or KURAMA asks. A longer / numbered name never becomes a shorter folder,
two folders with the same name are a numbered choice (the pick is remembered), 'here' is home for the weather, a
misheard own place / app is matched by sound, and 'remove second' picks from the list KURAMA showed last."""
import pytest

from jarvis.core import config, fastpath, paths, registry, workmem
from jarvis.tools.general import _apps, weather


@pytest.mark.parametrize("found,want,ok", [("Project", "project_3", False), ("clz_project", "project3", False),
                                           ("Downloads", "down", True), ("Downloads", "downloads", True),
                                           ("Projects", "project", True), ("Project1", "project one", True)])
def test_a_name_never_becomes_a_different_folder(found, want, ok):
    assert (paths._score(found, want) >= config.PATH_MATCH_MIN) == ok


def test_two_folders_with_the_same_name_are_a_choice_and_the_pick_is_kept(tmp_path, monkeypatch):
    a, b = tmp_path / "New_project" / "KURAMA", tmp_path / "Test_project" / "KURAMA"
    a.mkdir(parents=True), b.mkdir(parents=True)
    monkeypatch.setattr(paths, "roots", lambda: [tmp_path])
    found = a
    opts = paths.same_named(found, "kurama")
    assert set(opts) == {a, b}
    msg = paths.choices_text("kurama", opts)
    assert "1. " in msg and "2. " in msg and "Which one" in msg
    paths.picked(str(b))
    assert paths.same_named(found, "kurama") == [b]
    assert paths.same_named(a, "kurama in new_project") == [a]  # the other words already decide


def test_open_folder_offers_look_alikes_instead_of_opening_one(tmp_path, monkeypatch):
    from jarvis.tools.general import open_folder, open_url
    (tmp_path / "vscode_ext").mkdir()
    monkeypatch.setattr(paths, "roots", lambda: [tmp_path])
    monkeypatch.setattr(open_url, "_open", lambda p: pytest.fail("must not open a guess"))
    out = open_folder.open_folder("vscode extension")
    assert "Did you mean" in out and "1. " in out


@pytest.mark.parametrize("target", ["code from this", "Bascode from this", "B as code from this"])
def test_this_is_never_part_of_a_folder_name(target):
    assert fastpath._folder_intent(target) is None


@pytest.mark.parametrize("said", ["here", "my place", "near me", "current location", "home"])
def test_weather_here_is_the_home_place(monkeypatch, said):
    asked = []
    monkeypatch.setattr(weather._geo, "geocode", lambda p: asked.append(p) or None)
    weather.weather(said)
    assert asked[0] != said and asked[0]  # the home place, never 'here' (Hères, France)


@pytest.mark.parametrize("said,want", [("Nepal guns", "Nepalgunj"), ("nepalgunj", "Nepalgunj"), ("Paris", None)])
def test_a_misheard_own_place(said, want):
    assert weather._known_place(said) == want


@pytest.mark.parametrize("name,app", [("sitting", "settings"), ("setting", "settings")])
def test_an_app_name_that_sounds_the_same(name, app):
    assert _apps.sound_key(name) == _apps.sound_key(app)


@pytest.mark.parametrize("text", ["remove second", "delete 2"])
def test_an_ordinal_picks_from_the_list_kurama_showed_last(monkeypatch, text):
    monkeypatch.setattr(config, "FASTPATH", True)
    registry.REGISTRY.discover()
    workmem.record_call("saved_links", {"action": "list"}, True, "🔗 Your links:\n1. a: https://a.com\n2. b: https://b.com")
    it = fastpath.match(text)
    assert (it.tool, it.args) == ("saved_links", {"action": "delete", "name": "2"})


def test_an_ordinal_that_names_its_list_keeps_it(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    workmem.record_call("saved_links", {"action": "list"}, True, "🔗 Your links:\n1. a: https://a.com\n2. b: https://b.com")
    it = fastpath.match("remove second item from my todo list")
    assert it.tool == "todo"
