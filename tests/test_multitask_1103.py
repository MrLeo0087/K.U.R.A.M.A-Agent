"""11-03 night: 'open browser and send ... and generate an image ... and search for command.md and send it' did only
the first part. Each class found while running 10 different multi-step requests end to end."""
import pytest

from jarvis.core import fastpath, planner

FIVE = ("open browser and also send message to telegram that task complete and also generate iamge of kurama and send "
        "it to telegram and search for command.md file and send that file also in telegram")


@pytest.mark.parametrize("text", [FIVE, "open youtube and send hello to telegram",
                                  "generate an image of a cat and send it to telegram, then open youtube",
                                  "research black holes, make a report and send it to my telegram",
                                  "find my resume pdf, then send it to telegram and open gmail"])
def test_do_it_now_requests_are_never_taken_as_for_later(text):
    assert not planner.queue_meant(text)


@pytest.mark.parametrize("text", ["put this on your list for later: write a poem about rain",
                                  "don't start yet, just save it as a job: clean my desktop",
                                  "add to my jobs for later: make a ppt about AI and send it to telegram",
                                  "job for tomorrow: back up my photos", "queue this: research electric cars"])
def test_for_later_requests_still_are(text):
    assert planner.queue_meant(text)


def test_a_complete_word_inside_a_long_request_is_not_complete_the_code(monkeypatch):
    from jarvis.core import context
    monkeypatch.setattr(context, "editor_open", lambda: True)
    monkeypatch.setattr(context, "snapshot", lambda *a, **k: {"selection": None, "file": None, "browser": None})
    assert fastpath.to_file_intent(FIVE) is None and planner.is_multi(FIVE)
    assert fastpath.to_file_intent("complete this function") is not None


@pytest.mark.parametrize("text", ["write a poem about rain, make an image for it, and send both to telegram",
                                  "write an essay about nepal, then open youtube"])
def test_a_part_no_shortcut_knows_means_not_one_tool(text):
    assert not planner.one_tool(text)


@pytest.mark.parametrize("text,back", [("send message to telegram that task complete", False),
                                       ("write a note that says hello", False), ("send that file", True),
                                       ("send that to telegram", True), ("and send it to telegram", True),
                                       ("set a timer for 5 minutes and when it finishes tell me", False)])
def test_that_as_a_joining_word_is_not_a_pointer(text, back):
    assert planner.refers_back(text) is back


def test_steps_wait_only_for_what_they_need():
    tasks = planner.add_dependencies([
        {"text": "create a folder called trip in downloads"}, {"text": "take a screenshot", "depends_on": [0]},
        {"text": "save the screenshot in the trip folder", "depends_on": [1]},
        {"text": "tell me the weather in Pokhara", "depends_on": [2]}])
    assert [t.get("depends_on") for t in tasks] == [None, [0], [0, 1], [2]]  # the planned order is kept...
    assert [t.get("soft") for t in tasks] == [None, [0], None, [2]]  # ...but the weather / screenshot never get
    # skipped when the step before fails: only 'save the screenshot' truly needs the folder and the screenshot
    chain = planner.add_dependencies([{"text": "research the top 3 electric cars"},
                                      {"text": "write a short report about them", "depends_on": [0]},
                                      {"text": "send the report to my telegram", "depends_on": [1]}])
    assert [t.get("depends_on") for t in chain] == [None, [0], [1]]


def test_a_when_tail_stays_with_its_timer_in_every_plan(monkeypatch):
    monkeypatch.setattr(planner, "_shortcut_tasks", lambda text: [
        {"text": "play some lofi music", "kind": "quick"}, {"text": "set a timer for 25 minutes", "kind": "quick"},
        {"text": "when it finishes send me a telegram message saying break time", "kind": "quick"}])
    p = planner.plan("play some lofi music, set a timer for 25 minutes and when it finishes send me a telegram "
                     "message saying break time")
    assert len(p.tasks) == 2 and "when it finishes" in p.tasks[1]["text"] and not p.tasks[1].get("depends_on")


@pytest.mark.parametrize("said,label", [("set a timer for 25 minutes and when it finishes send me a telegram message "
                                         "saying break time", "break time"),
                                        ("set a timer for 10 minutes and when it is done message me on telegram "
                                         "saying tea is ready", "tea is ready")])
def test_the_timer_sends_your_words_to_the_phone(said, label):
    it = fastpath._control_intent(said)
    assert it.tool == "set_timer" and it.args["phone"] is True and it.args["label"] == label


def test_screenshot_into_a_folder_and_biggest_files():
    from jarvis.tools.core import files, laptop
    from jarvis.tools.core._hub import resolve
    assert laptop._shot("Downloads/trip") == {"mode": "full", "folder": "Downloads/trip"}
    assert resolve(files.TABLE, {"action": "find", "path": "downloads", "text": "biggest"}) == \
        ("find_files", {"query": "*", "path": "downloads", "kind": "name", "order": "biggest"})
    assert fastpath._NOT_FINDFILE.search("the biggest files")


def test_find_files_biggest_and_newest(tmp_path):
    from jarvis.tools.interactive.find_files import find_files
    tmp_path = tmp_path / "dl"
    tmp_path.mkdir()
    (tmp_path / "a.bin").write_bytes(b"x" * 5000)
    (tmp_path / "b.bin").write_bytes(b"x" * 10)
    (tmp_path / "c.txt").write_bytes(b"x" * 900)
    out = find_files("*", str(tmp_path), "name", 2, "biggest")
    assert out.splitlines()[1].endswith("a.bin (5 KB)") and "c.txt" in out.splitlines()[2] and "b.bin" not in out


def test_replies_read_like_a_person():
    from jarvis.core.agent import checklist
    assert fastpath.natural("minimized KURAMA") == "Done — KURAMA is minimized."
    assert fastpath.natural("snapped VS Code to the left half") == "Done — VS Code is on the left half."
    assert fastpath.natural("Pokhara: 21°C") == "Pokhara: 21°C"
    tasks = [{"text": "open browser"}, {"text": "tell me the weather in pokhara"}, {"text": "make a video"}]
    out = checklist(tasks, {0: {"status": "ok", "answer": "Sure, opening Brave."},
                            1: {"status": "ok", "answer": "Pokhara: 21°C, clear."},
                            2: {"status": "waiting", "job": 3, "answer": "Making it (job #3)."}})
    assert out.splitlines() == ["2 of 3 done, 1 still working.", "✓ Open browser",
                                "✓ Tell me the weather in pokhara — Pokhara: 21°C, clear.",
                                "⏳ Make a video (job #3, I'll tell you when it's done)"]



def test_a_failed_step_skips_only_what_truly_needs_it():
    from jarvis.core import taskgraph
    tasks = planner.add_dependencies([
        {"text": "create a folder called trip in downloads"}, {"text": "take a screenshot", "depends_on": [0]},
        {"text": "save the screenshot in the trip folder", "depends_on": [1]},
        {"text": "tell me the weather in Pokhara", "depends_on": [2]}])
    done = {0: {"idx": 0, "status": "failed", "text": tasks[0]["text"], "answer": "no"},
            1: {"idx": 1, "status": "ok", "text": tasks[1]["text"], "answer": "shot"}}
    final = taskgraph.settle(tasks, done)
    assert final[2]["status"] == "skipped"  # it needs the folder that wasn't made
    assert final[3]["status"] != "skipped"  # the weather never needed it


def test_the_checklist_keeps_what_a_step_wrote():
    from jarvis.core.agent import checklist
    poem = "Soft whispers fall, silver threads on the earth's skin, dreams dance in puddles, night sighs and the " \
           "city breathes again under a washed sky."
    out = checklist([{"text": "write a poem about rain"}, {"text": "make an image for it"}, {"text": "send both"}],
                    {0: {"status": "ok", "answer": poem}, 1: {"status": "ok", "answer": "Saved the image: /x.png"},
                     2: {"status": "ok", "answer": "Sent to Telegram."}})
    assert poem in out and "✓ Send both" in out


# ---- 11-04 00:11: 10 parts asked, the image became a text file, the poem was never sent, 2 parts vanished ----
@pytest.mark.parametrize("text,kind", [("generate an image of a hill with a clear sky and grass", "quick"),
                                       ("make a short video about my trip", "quick"),
                                       ("draw a picture of a cat", "quick"),
                                       ("write an essay about nepal", "long")])
def test_making_a_picture_is_never_a_writing_job(text, kind):
    assert planner._kind(text, "long") == kind


def test_every_part_of_the_request_is_in_the_plan():
    text = ("I want you to open YouTube, Facebook, Instagram, generate an image of a hill. Then open VS Code and "
            "open the browser. Then turn on the Bluetooth of my laptop. Also send the status of my RAM in the telegram.")
    given = [{"text": "open YouTube"}, {"text": "generate an image of a hill"}, {"text": "open VS Code"}]
    texts = [t["text"] for t in planner.cover(text, given)]
    assert "turn on the Bluetooth of my laptop" in texts and "send the status of my RAM in the telegram" in texts
    assert "open the browser" in texts and texts.count("open VS Code") == 1


def test_a_step_waits_for_every_job_it_needs():
    from jarvis.core import taskgraph
    tasks = [{"text": "generate an image of a hill"}, {"text": "write a poem about nepal", "kind": "long"},
             {"text": "send image and poem to my telegram", "depends_on": [0, 1]}]
    done = {0: {"idx": 0, "status": "waiting", "job": 7, "text": "img"},
            1: {"idx": 1, "status": "waiting", "job": 8, "text": "poem"}}
    final = taskgraph.settle(tasks, done)
    assert final[2]["status"] == "after" and final[2]["jobs"] == [7, 8]


def test_the_follow_up_waits_for_all_its_jobs(monkeypatch, tmp_path):
    from jarvis.core import agent, store
    rows = {7: {"status": "done", "output_path": str(tmp_path / "hill.png")},
            8: {"status": "done", "output_path": str(tmp_path / "poem.md")}}
    (tmp_path / "poem.md").write_text("Himalaya sings")
    monkeypatch.setattr(store, "job_get", lambda j: rows[j])
    seen = []
    monkeypatch.setattr(agent.Agent, "_run_task", lambda self, text, mode, lang, prev, request="": seen.append(prev) or "sent")

    class Ctx:
        state, job = {}, type("J", (), {"title": "then: send", "cancel_event": None})()
        def step(self, *a): pass
        def check(self): pass
        def checkpoint(self, **k): pass
        def set_output(self, p): pass
    monkeypatch.setattr("jarvis.core.writer.output_path", lambda title: tmp_path / "out.md")
    agent.after_job(Ctx(), {"wait": [7, 8], "tasks": ["send image and poem to my telegram"]})
    assert "hill.png" in seen[0] and "poem.md" in seen[0] and "Himalaya sings" in seen[0]
