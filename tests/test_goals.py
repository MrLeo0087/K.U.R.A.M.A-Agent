from datetime import date, datetime, timedelta

import pytest

from jarvis.core import config, fastpath, goals, store

D0 = date(2026, 10, 26)


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(goals, "_send", lambda title, text: out.append((title, text)))
    monkeypatch.setattr(config, "FASTPATH", True)
    return out


def args(text):
    i = fastpath.match(text)
    assert i and i.tool == "goals", (text, i)
    return i.args


def test_end_dates_and_times():
    assert goals.end_in("my exam starts in the 30 day", D0) == D0 + timedelta(days=30)
    assert goals.end_in("the project takes six months", D0) == date(2027, 4, 26)
    assert goals.end_in("exam is on November 28, remind me twice a day", D0) == date(2026, 11, 28)
    assert goals.end_in("remind me twice a day", D0) is None  # 'a day' is a frequency, not an end
    assert goals.times_in("at 6 am and 9 pm") == ["06:00", "21:00"]
    assert goals.times_in("2-3 times a day") == ["07:00", "13:00", "20:00"]
    assert goals.times_in("at 3 am") == ["05:00"]  # never before 05:00 (owner's KURAMA hours)
    assert goals.times_in("at 11 pm") == ["21:30"]  # never after 22:00


def test_new_goals_from_plain_words(sent):
    a = args("my school exam starts in the 30 day, so remind me every day how many days are left")
    assert a["action"] == "add" and a["name"] == "school exam" and "ask" not in a
    a = args("I am working on a project which takes 6 months, ask me every day what I am doing")
    assert a["name"] == "project" and a["ask"] == "yes"
    a = args("remind me every day at 7 am and 9 pm, my board exam is after 45 days")
    assert goals.times_in(a["remind"]) == ["07:00", "21:00"]
    assert fastpath.match("remind me to submit the project in 3 days").tool == "add_reminder"  # one-off reminder
    assert fastpath.match("I have an interview in 2 weeks") is None or fastpath.match("I have an interview in 2 weeks").tool != "goals"
    # a custom question is worded by the AI (goals tool through the router), not guessed by regex
    assert fastpath.match("ask me every day whether I studied 2 hours, my exam is in 20 days") is None


def test_add_countdown_and_project(sent):
    out = goals.add("Physics exam", "in 30 days", today=D0)
    assert "ends Wed, Nov 25 (30 days)" in out and "7 AM, 1 PM and 8 PM" in out
    out = goals.add("KURAMA app", "in 3 months", ask="yes", today=D0)
    assert "9 PM" in out and "Its folder" in out
    g = goals.find("kurama")
    assert g["kind"] == "project" and g["remind"] == "08:00" and g["weekly"] == "yes"
    assert (goals.Path(g["folder"]) / "log.md").exists()
    assert goals.add("physics exam", "in 40 days", today=D0).startswith("You already have")
    assert goals.find("exam")["end"] == (D0 + timedelta(days=40)).isoformat()
    from openpyxl import load_workbook
    wb = load_workbook(goals.path())
    assert wb.sheetnames == ["Goals", "Log"] and [c.value for c in wb["Goals"][1]] == goals.HEAD


def test_countdown_messages_only_in_working_hours(sent):
    goals.add("Exam", "in 30 days", today=D0)
    assert goals.tick(datetime(2026, 10, 26, 4, 59)) == []  # before 05:00: nothing
    assert goals.tick(datetime(2026, 10, 26, 7, 0, 20)) == ["1:r:07:00"]
    assert sent[-1] == ("Goal: Exam", "📅 Exam: 30 days left (Wed, Nov 25).")
    assert goals.tick(datetime(2026, 10, 26, 7, 5)) == []  # once per slot
    assert goals.tick(datetime(2026, 10, 26, 15, 0)) == []  # 1 PM missed by 2 h (laptop off): skipped, not sent late
    assert goals.reminder_text(goals.find("exam"), date(2026, 11, 22)) == "⏳ Exam: only 3 days left (Wed, Nov 25)."
    assert goals.reminder_text(goals.find("exam"), date(2026, 11, 24)) == "⏳ Exam is tomorrow (Wed, Nov 25)."
    assert goals.tick(datetime(2026, 11, 25, 13, 0)) == []  # the big day: only the first slot
    assert goals.tick(datetime(2026, 11, 26, 7, 0)) == ["1:ended"] and goals.all_goals("active") == []


def test_checkin_answer_log_and_summaries(sent, monkeypatch):
    goals.add("Thesis", "in 30 days", ask="yes", today=D0)
    monkeypatch.setattr(goals, "commits", lambda repo, since, until=None, limit=30: [])
    assert "1:a" in goals.tick(datetime(2026, 10, 26, 21, 0))
    assert sent[-1][0] == "Check-in: Thesis" and "What did you do on Thesis today?" in sent[-1][1]
    # a plain answer right after the question goes to its log (0 tokens)
    a = args("today I finished the literature review")
    assert a == {"action": "log", "goal": "1", "text": "today I finished the literature review"}
    assert goals.run(**a).startswith("Saved to Thesis's log")
    assert goals.waiting() is None
    assert goals.run(**args("Thesis update: wrote the intro")) == "Saved to Thesis's log (2 notes today)."
    day = goals.day_text(goals.find("thesis"))
    assert "today I finished the literature review" in day and "wrote the intro" in day
    assert args("what did we do today in the thesis")["action"] == "today"
    assert args("what did we do this week on thesis")["action"] == "week"
    assert "notes on 1 of 7 days" in goals.week_text(goals.find("thesis"))
    f = goals.Path(goals.find("thesis")["folder"])
    assert "wrote the intro" in (f / "log.md").read_text() and any((f / "daily").iterdir())


def test_ask_again_once_then_no_answer_is_logged(sent, monkeypatch):
    monkeypatch.setattr(config, "GOAL_ASK_AGAIN_S", 0)
    goals.add("Thesis", "in 30 days", ask="yes", today=D0)
    goals.tick(datetime(2026, 10, 26, 6, 0))
    assert goals.tick(datetime(2026, 10, 26, 21, 0)) == ["1:a"]
    assert goals.tick(datetime(2026, 10, 26, 21, 30)) == ["1:a2"] and sent[-1][1].startswith("Still waiting: what did you do")
    assert goals.tick(datetime(2026, 10, 26, 21, 45)) == []
    goals.tick(datetime(2026, 10, 27, 6, 0))
    assert [x["entry"] for x in goals._logs()] == ["(no answer)"]


def test_telegram_reply_to_a_checkin_is_saved(sent):
    goals.add("KURAMA app", "in 3 months", ask="yes", today=D0)
    from jarvis.workers.telegram_bot import TelegramBot
    bot = TelegramBot.__new__(TelegramBot)
    out = bot.answer("fixed the mic bug", {"text": "Check-in: KURAMA app\nWhat did you do on KURAMA app today?"})
    assert out.startswith("Saved to KURAMA app's log") and goals._logs()[0]["from"] == "telegram"


def test_changes(sent):
    goals.add("Physics exam", "in 30 days", today=D0)
    goals.add("Thesis", "in 6 months", ask="yes", today=D0)
    assert args("move my exam to December 2") == {"action": "edit", "goal": "1", "end": "december 2"}
    assert "ends" in goals.run(**args("move my exam to December 2"))
    assert goals.run(**args("remind me about the exam twice a day")) == "Physics exam: reminders at 8 AM and 8 PM."
    assert goals.run(**args("stop asking about the thesis")) == "Thesis: I won't ask about it any more."
    assert goals.run(**args("pause the thesis goal")).endswith("paused (no messages).")
    assert goals.run(**args("resume the thesis goal")).endswith("running again.")
    assert goals.run(**args("the exam is over")).endswith("marked done, messages stopped.")
    assert args("show my goals") == {"action": "list"}
    assert "Thesis" in goals.show() and "Physics" not in goals.show()
    assert args("how many days until my thesis")["action"] == "status"
    assert fastpath.match("the download is done") is None or fastpath.match("the download is done").tool != "goals"


def test_report_job(sent, monkeypatch, tmp_path):
    from jarvis.core import convert, jobs, llm
    goals.add("Thesis", "in 30 days", ask="yes", today=D0)
    goals.log_entry("thesis", "wrote chapter 1")
    calls = []
    monkeypatch.setattr(llm, "chat", lambda msgs, **k: calls.append(k["purpose"]) or "## Section\nDid things.")
    monkeypatch.setattr(convert, "html_to_pdf", lambda html, out: out.write_bytes(b"%PDF"))
    i = fastpath.match("make the thesis report")
    assert i.args == {"action": "report", "goal": "1"}
    out = goals.run(**i.args)
    jid = int(out.split("#")[1].rstrip(")."))
    job = jobs.get_manager().wait(jid, timeout=10)
    assert job.status == "done" and len(calls) == 2  # one month + the summary
    f = goals.Path(goals.find("thesis")["folder"])
    assert "# Thesis: report" in (f / "report.md").read_text() and (f / "report.pdf").exists()


def test_dashboard_work_card(sent):
    goals.add("Exam", "in 10 days", today=date.today())
    from jarvis.api.routes import dash
    w = dash._work()
    assert w["goals"][0]["name"] == "Exam" and w["goals"][0]["left"] == 10 and "todo" in w["list"]


def test_owner_log_remove_and_correct(sent):
    """Owner's 8:56 PM log: the 30-day fix cost 5k tokens and 'remove that exam' went to delete_to_trash."""
    a = args("Actually, my exam are in the 40 days, so I want to track my study and I want you to remind me every day. Can you do this?")
    goals.run(**a)
    a = args("Actually, the thing is, it's not 40 days, it's actually 30 days.")
    assert a == {"action": "edit", "goal": "1", "end": "in 30 days"}
    assert goals.run(**a).startswith("Exam: ends")
    assert goals.find("exam")["end"] == (date.today() + timedelta(days=30)).isoformat()
    assert args("Okay, I think the exam is postponed") == {"action": "postponed", "goal": "1"}
    assert "When is Exam now?" in goals.run(**args("the exam is postponed"))
    assert args("the exam got postponed to December 10")["action"] == "edit"
    for q in ("Okay, I think the exam is postponed, so can we remove that 30 day exam routing.",
              "delete my exam goal", "cancel the exam countdown", "I don't need the exam reminder anymore"):
        assert args(q) == {"action": "delete", "goal": "1"}, q
    assert fastpath.match("delete exam.pdf") is None or fastpath.match("delete exam.pdf").tool != "goals"
    assert goals.run(**args("remove the exam")).startswith("Deleted the long task 'Exam'") and goals.show().startswith("No long tasks")


def test_correction_never_hits_another_goal(sent):
    goals.add("Exam", "in 40 days")
    a = args("actually my project ends in 6 months, ask me every day")
    assert a["action"] == "add" and a["name"] == "project"


def test_work_overview(sent, monkeypatch):
    goals.add("Exam", "in 30 days")
    for q in ("Can you tell me what is in my working list right now? What project?", "what am I working on",
              "show my work list", "which projects do I have"):
        assert args(q) == {"action": "overview"}, q
    out = goals.run("overview")
    assert "Exam: 30 days left" in out and "Your long tasks" in out
    assert fastpath.match("what is my project about") is None or fastpath.match("what is my project about").tool != "goals"
    assert fastpath.match("what was I working on").tool == "where_was_i"


def test_todo_vs_long_tasks_vs_code(sent):
    """Owner's 11:33 PM log: to-do questions went to knowledge/web, 'schedule a work for 11:41 pm' became a computer
    command waiting for yes ('Stopped.'), and Whisper's 'tax' meant 'task'."""
    todo = {"action": "list", "text": "todo"}
    for q in ("Is there anything in my ToDo?", "Is there any tax for me today?", "what is my reminder today",
              "what is the current work I have to do", "Show today's reminders and the current work I have to do",
              "what are my tasks for today", "what do I have to do today"):
        i = fastpath.match(q)
        assert i and i.tool == "read_later" and i.args == todo, (q, i)
    i = fastpath.match("Okay, schedule a work for 11.41pm for reading the book.")
    assert i.tool == "read_later" and i.args == {"action": "todo", "text": "reading the book", "when": "11.41pm"}
    assert fastpath.match("Schedule 2-2 tax for 11.41 pm for reading book.").args["text"] == "reading book"
    i = fastpath.match("schedule a shutdown at 10 pm")
    assert i is None or i.tool != "read_later"  # a computer action stays schedule_command
    for q in ("What is the thing that I have to do for my month?", "show my long tasks"):
        assert args(q) == {"action": "list"}, q
    assert args("what am I working on") == {"action": "overview"}
    assert fastpath.normalize("I need to pay income tax") == "I need to pay income tax"
