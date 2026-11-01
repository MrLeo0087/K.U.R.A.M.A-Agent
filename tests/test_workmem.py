"""Working memory (Phase 1 of the memory + multitasking rebuild): what tools made/touched is remembered as THINGS,
a numbered list of real paths is a CHOICE the next reply picks, KURAMA's own question routes the short reply,
and each reply in the AI's history says what its tools did."""
import time
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from jarvis.core import agent, config, fastpath, focus, safety, store, workmem
from tests.test_p7c import Responder, names, respond, roots, tg  # noqa: F401  (fixtures)


@pytest.fixture
def files(tmp_path):
    img = tmp_path / "pics" / "horse.png"
    img.parent.mkdir()
    img.write_bytes(b"png")
    folder = tmp_path / "new_project2"
    folder.mkdir()
    doc = tmp_path / "My Notes" / "essay about nepal.md"
    doc.parent.mkdir()
    doc.write_text("Nepal")
    return SimpleNamespace(img=img, folder=folder, doc=doc, root=tmp_path)


def test_tool_paths_become_things_by_kind(files):
    workmem.record_call("generate_image", {"prompt": "a horse"}, True, f"Saved the picture to {files.img}. Ask me to send it.")
    workmem.record_call("make_folder", {"path": str(files.folder)}, True, "Made it.")
    workmem.record_call("write_document", {"title": "essay"}, True, f"Saved to {files.doc}. It's in the workspace.")
    assert workmem.latest() == files.doc  # a path with spaces, followed by more words
    assert workmem.latest("image") == files.img and workmem.latest("folder") == files.folder
    assert [t["k"] for t in workmem.things()] == ["document", "folder", "image"]
    line = workmem.line()
    assert line.startswith("Things from this chat") and "horse.png" in line and "new_project2" in line


def test_only_real_paths_of_calls_that_worked(files):
    ghost = files.root / "ghost"
    workmem.record_call("make_folder", {"path": str(ghost)}, True, f"Made {ghost}")  # not on disk: never a guess
    workmem.record_call("write_file", {"path": str(files.doc)}, False, "error: disk full")  # failed: nothing
    many = "\n".join(str(p) for p in (files.img, files.folder, files.doc, files.img.parent))
    workmem.record_call("find_files", {"query": "x"}, True, many)  # a listing is not a thing it made
    workmem.record_call("_say", {"text": str(files.img)}, True, str(files.img))
    workmem.record_call("text_assist", {"path": "/"}, True, "Read / and /media")  # never the root or a top folder
    assert workmem.things() == [] and workmem.line() == ""


@pytest.mark.parametrize("ref,kind", [("that image", "img"), ("the photo", "img"), ("this picture", "img"),
                                      ("the essay", "doc"), ("that document", "doc"), ("the md file", "doc")])
def test_a_kind_named_points_at_the_newest_thing_of_that_kind(files, ref, kind):
    workmem.note(files.img)
    workmem.note(files.doc)
    workmem.note(files.folder)  # newest, but not what "that image" means
    assert focus.refer(ref) == getattr(files, kind)


def test_no_thing_of_that_kind_means_nothing_never_some_folder(files, monkeypatch):
    from jarvis.core import filemanager
    monkeypatch.setattr(filemanager, "current", lambda: files.root)
    workmem.note(files.folder)
    for ref in ("that video", "the song", "the pdf"):
        assert focus.refer(ref) is None
    assert fastpath.match("send that video to telegram") is None or \
        fastpath.match("send that video to telegram").args.get("path") != str(files.folder)


def test_just_made_beats_the_open_files_folder(files, monkeypatch):
    from jarvis.core import filemanager
    elsewhere = files.root / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr(filemanager, "current", lambda: elsewhere)
    workmem.record_call("make_folder", {"path": str(files.folder)}, True, "Made it.")
    for ref in ("this folder", "it", "that folder"):
        assert focus.refer(ref) == files.folder
    monkeypatch.setattr(config, "WORKMEM_FRESH_S", 0)  # made long ago: the folder open in Files is "this"
    assert focus.refer("this folder") == elsewhere


@pytest.mark.parametrize("q", ["open it in vs code", "open this folder on vs code", "Open that folder in VS Code."])
def test_make_a_folder_then_open_it_in_vs_code(files, q, monkeypatch):
    from jarvis.core import semantic
    monkeypatch.setattr(semantic, "ready", lambda: True)  # the meaning model picks 'open in VS Code' (the scorecard
    monkeypatch.setattr(semantic, "best_of", lambda t, n, table: ("open_vscode", 0.95))  # checks the real one)
    monkeypatch.setattr(semantic, "scores", lambda t: [(semantic.CHAT, 0.5)])
    workmem.record_call("make_folder", {"path": str(files.folder)}, True, f"Made {files.folder}")
    it = fastpath.match(q)
    assert it is not None and it.tool == "open_path" and it.args == {"path": str(files.folder), "app": "vscode"}


@pytest.mark.parametrize("q", ["send it to telegram", "send the essay to my telegram", "share that document to telegram"])
def test_found_file_then_send_it(files, q):
    workmem.record_call("find_files", {"query": "essay"}, True, f"1 file named like 'essay':\n{files.doc}")
    it = fastpath.match(q)
    assert it is not None and it.tool == "send_file_telegram" and it.args["path"] == str(files.doc)


def _three_copies(files):
    copies = []
    for d in ("Redmi 9A", "iPhone", "Backup"):
        p = files.root / d / "IMG_1.jpg"
        p.parent.mkdir()
        p.write_bytes(b"jpg")
        copies.append(p)
    res = "I found three copies of that file.\n" + "\n".join(f"{i}. {p}" for i, p in enumerate(copies, 1))
    workmem.record_call("send_file_telegram", {"path": "IMG_1.jpg"}, False, res)
    return copies


@pytest.mark.parametrize("reply,which", [("2", 1), ("the second one", 1), ("send the 2nd", 1), ("last one", 2),
                                         ("the one in Redmi 9A", 0), ("iphone", 1), ("first", 0)])
def test_a_numbered_list_of_paths_is_a_choice_the_reply_picks(files, reply, which):
    copies = _three_copies(files)
    it = fastpath.match(reply)
    assert it is not None and it.name == "choice" and it.tool == "send_file_telegram"
    assert it.args == {"path": str(copies[which])}
    assert workmem.choice() is None  # used once


@pytest.mark.parametrize("reply", ["open brave", "what is the weather in pokhara today", "the one"])
def test_a_new_request_is_not_a_choice(files, reply):
    _three_copies(files)
    it = fastpath.match(reply)
    assert it is None or it.name != "choice"


def test_a_choice_expires(files, monkeypatch):
    _three_copies(files)
    monkeypatch.setattr(workmem, "CHOICE_TTL_S", -1)
    assert workmem.choose("2") is None


def test_a_finished_job_output_is_a_thing(files):
    workmem.note_job(SimpleNamespace(status="done", output_path=str(files.doc), id=7))
    workmem.note_job(SimpleNamespace(status="failed", output_path=str(files.img), id=8))
    assert workmem.latest() == files.doc and workmem.things()[0]["by"] == "job #7"


def test_send_that_image_prefers_the_image_this_chat_touched(files, monkeypatch, tmp_path):
    from jarvis.tools.general import send_last_result as slr
    out = tmp_path / "outputs" / "images"
    out.mkdir(parents=True)
    old = out / "old.png"
    old.write_bytes(b"png")
    workmem.note(files.img)  # found on disk / made a moment ago: newer than old.png
    assert slr._newest("image") == files.img
    workmem.clear()
    assert slr._newest("image") == old


# --- KURAMA's own question ---
def _asked(bot, text):
    bot.history = [HumanMessage("i am sad today"), AIMessage(text)]
    bot._last_turn = time.time()


@pytest.mark.parametrize("reply", ["yes", "yeah do it", "ok go ahead please"])
def test_a_reply_to_my_offer_gets_the_offers_tools(respond, reply):
    seen = []

    def fn(messages, kw):
        seen.append((names(kw), messages[0].content))
        return AIMessage("Playing some calm music.")
    respond(fn)
    bot = agent.Agent(persist=False)
    _asked(bot, "I'm sorry. Want me to play some relaxing music")  # an offer, even without a '?'
    assert bot.run(reply) == "Playing some calm music."
    tools, system = seen[0]
    assert any("music" in t or "media" in t for t in tools), tools
    assert "Your latest message to the user asked" in system and "relaxing music" in system


def test_bare_yes_only_when_i_asked_nothing():
    bot = agent.Agent(persist=False)
    _asked(bot, "Done, I sent it to your Telegram.")
    assert bot._bare_answer("yes") == agent.Agent.BARE["yes"]
    _asked(bot, "Should I also send the video?")
    assert bot._bare_answer("yes") is None
    bot._last_turn = time.time() - config.QUESTION_TTL_S - 5  # asked long ago: stale
    assert bot._bare_answer("yes") == agent.Agent.BARE["yes"]


def test_a_question_asked_on_telegram_is_answered_on_the_laptop():
    sid = store.session_start("telegram")
    store.add_message("assistant", "Your essay is ready. Want me to open it in VS Code?", session=sid)
    bot = agent.Agent(persist=True, channel="")
    assert "open it in VS Code" in bot._open_question()
    store.add_message("assistant", "Okay, done.", session=sid)  # something newer that asks nothing
    assert bot._open_question() == ""


def test_history_keeps_what_tools_did_for_the_last_replies_only(respond):
    respond(lambda m, kw: AIMessage("ok"))
    bot = agent.Agent(persist=False)
    bot.history = [HumanMessage("a"), AIMessage("A\n[tools this turn: make_folder(path=/x) -> Made it]"),
                   HumanMessage("b"), AIMessage("B\n[tools this turn: open_path(path=/x) -> Opened]"),
                   HumanMessage("c"), AIMessage("C\n[tools this turn: get_time() -> 6 PM]")]
    msgs = bot._messages("d", "text", "en")
    ai = [m.content for m in msgs if isinstance(m, AIMessage)]
    assert ai == ["A", "B\n[tools this turn: open_path(path=/x) -> Opened]", "C\n[tools this turn: get_time() -> 6 PM]"]
    assert agent.tidy("Sure.\n[tools this turn: x() -> y]") == "Sure."  # the model never shows it


def test_did_line_from_the_turns_trace(monkeypatch):
    from jarvis.core import trace
    tr = {"tools": [{"name": "send_message_telegram", "args": {"text": "hello"}, "ok": True, "result": "Sent (5)."},
                    {"name": "telegram", "args": {"action": "message", "text": "hello"}, "ok": True, "result": "Sent (5)."},
                    {"name": "write_file", "args": {"path": "/a.py", "content": "x" * 500}, "ok": False,
                     "result": "error: exists"}]}
    monkeypatch.setattr(trace, "current", lambda: tr)
    line = agent.did_line()
    assert line == ("\n[tools this turn: send_message_telegram(text=hello) -> Sent (5).; "
                    "write_file(path=/a.py, content=<500 chars>) -> FAILED error: exists]")


def test_end_to_end_write_then_send_it(roots, tg, monkeypatch):  # noqa: F811
    monkeypatch.setattr(config, "FASTPATH", True)
    res = safety.execute("write_file", {"path": str(roots / "plan.md"), "content": "# Plan\n" + "x" * 5000},
                         confirm=lambda p: True)
    assert res.ok
    ans = agent.Agent(persist=False).run("send it to telegram")
    assert tg and tg[0][0] == "sendDocument" and "plan.md" in str(tg[0][2]) and "telegram" in ans.lower()
