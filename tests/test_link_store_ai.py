"""The link store through the AI's memory tool: list / delete (name, number, all) / rename, and only the link and
name the user gave in THIS message count (traces 2026-11-01: old links and names were copied from the chat)."""
import pytest

from jarvis.core import links, readlater, rewrite, safety
from jarvis.tools.core import _hub, memory


@pytest.fixture
def page(monkeypatch):
    st = {"page": ("https://app.notion.com/p/roadmap", "Roadmap")}
    monkeypatch.setattr(rewrite, "target_window", lambda: (5, False))
    monkeypatch.setattr(rewrite, "_window_name", lambda wid, limit=60: "Roadmap - Brave")
    monkeypatch.setattr(rewrite, "grab", lambda: "nothing highlighted")
    monkeypatch.setattr(rewrite, "_xclip", lambda args, text: None)
    monkeypatch.setattr(readlater, "current_page", lambda title: st["page"])
    monkeypatch.setattr(readlater, "selected_links", lambda: [])
    return st


def said(text, fn, *a):
    tok = safety._CTX.set({"user_text": text})
    try:
        return fn(*a)
    finally:
        safety._CTX.reset(tok)


def fill(*pairs):
    for name, url in pairs:
        links._put(name, url)


@pytest.mark.parametrize("action,text,tool,args", [
    ("list_links", "", "saved_links", {"action": "list"}),
    ("delete_link", "sofascore", "saved_links", {"action": "delete", "name": "sofascore"}),
    ("delete_link", "2", "saved_links", {"action": "delete", "name": "2"}),
    ("rename_link", "nchat » chat app", "saved_links", {"action": "rename", "name": "nchat", "new_name": "chat app"}),
    ("rename_link", "drive to google drive", "saved_links", {"action": "rename", "name": "drive", "new_name": "google drive"}),
    ("open_link", "notion", "saved_links", {"action": "open", "name": "notion"}),
    ("remove_read_later", "all", "read_later", {"action": "clear", "text": "read"}),
    ("remove_read_later", "second", "read_later", {"action": "remove", "n": 2}),
    ("remove_read_later", "neurips paper", "read_later", {"action": "remove", "text": "neurips paper"}),
])
def test_memory_tool_reaches_every_link_action(action, text, tool, args):
    assert _hub.resolve(memory.TABLE, {"action": action, "text": text}) == (tool, args)


@pytest.mark.parametrize("words,n", [("2", 2), ("second", 2), ("2nd", 2), ("the second one", 2), ("no 3", 3),
                                     ("last", -1), ("sofascore", None), ("2 links", None)])
def test_position_words(words, n):
    assert links.position(words) == n


def test_delete_by_number_name_and_all():
    fill(("notion", "https://web.whatsapp.com/"), ("sofascore", "https://www.sofascore.com/"), ("gemini", "https://gemini.google.com/app"))
    assert links.run("delete", "second") == "Removed the 'sofascore' link."
    assert links.run("delete", "gemini") == "Removed the 'gemini' link."
    assert links.run("delete", "last") == "Removed the 'notion' link."
    fill(("a", "https://a.com/"), ("b", "https://b.com/"))
    out = links.run("delete", "all")
    assert out.startswith("Removed all 2 links (a, b)") and links.path().with_suffix(".backup.xlsx").exists()
    assert links.run("list").startswith("No saved links yet")
    assert links.run("delete", "everything") == "The link store is already empty."


def test_rename_by_number():
    fill(("nchat", "https://web.nchat.chat/"), ("yt", "https://youtube.com/"))
    assert links.run("rename", "2", new_name="youtube") == "Renamed 'yt' to 'youtube'."


@pytest.mark.parametrize("msg", ["save this link name notion", "store this website link as notion",
                                 "no on.. notion link is this website ,save it as notion"])
def test_old_link_from_the_chat_is_ignored_the_open_page_is_saved(page, msg):
    out = said(msg, links.run, "save", "notion", "https://socolivet.cv/")  # the AI copied the earlier turn's site
    assert out.startswith("Saved 'notion': https://app.notion.com/p/roadmap")


@pytest.mark.parametrize("msg", ["save this link in website for whatsapp", "save this link for whatsapp bro",
                                 "this page link save kar do whatsapp naam se"])
def test_old_name_from_the_chat_is_ignored(page, msg):
    out = said(msg, links.run, "save", "notion")  # the AI reused the previous link's name
    assert out.endswith("What should I call this link?")
    out = said(msg, links.run, "save", "whatsapp")
    assert out.startswith("Saved 'whatsapp': https://app.notion.com/p/roadmap")


@pytest.mark.parametrize("msg", ["save https://socolivet.cv as socolive", "https://socolivet.cv/ save this link to socolive",
                                 "add www.socolivet.cv in link store name socolive"])
def test_a_link_typed_in_the_message_is_kept(page, msg):
    assert said(msg, links.run, "save", "socolive", "https://socolivet.cv/").startswith("Saved 'socolive': https://socolivet.cv")


@pytest.mark.parametrize("row,area", [
    ({"text": "clear link store", "group": "browser", "tool": "saved_links"}, "links"),  # learned before the move
    ({"text": "is anything in read later", "group": "browser", "tool": "read_later"}, "links"),
    ({"text": "open facebook", "group": "browser", "tool": "open_url"}, "browser"),
    ({"text": "old row", "group": "media"}, "media"),  # no tool recorded: the stored area
])
def test_learned_wordings_follow_their_tool_to_its_current_area(row, area):
    from jarvis.core import learn, registry
    registry.REGISTRY._ensure()
    assert learn._group_now(row) == area


@pytest.mark.parametrize("text", ["show me link stroe", "save this link to socolive", "bro delete gemini link frm link store"])
def test_before_the_meaning_model_loads_the_link_area_still_comes(monkeypatch, text):
    """The model is freed after 10 min idle; the word rules then say 'browser' for any 'link' (17 of 87 AI requests
    10-31..11-01 were routed so): the link store's area rides along."""
    from jarvis.core import llm, registry, router, semantic
    monkeypatch.setattr(semantic, "ready", lambda: False)
    monkeypatch.setattr(semantic, "warm_soon", lambda: None)
    monkeypatch.setattr(llm, "chat", lambda *a, **k: (_ for _ in ()).throw(llm.LLMError("off")))
    registry.REGISTRY._ensure()
    r = router.route(text, log_it=False)
    assert r.method == "rules" and "links" in r.groups
