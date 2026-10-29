"""v2 phase 1: the to-do list is its own list (SQLite), separate from reminders and the reading list."""
from datetime import datetime, timedelta

from jarvis.core import config, fastpath, readlater, store, todos
from jarvis.tools.core.todo import todo


def test_a_todo_never_rings_unless_asked():
    out = todos.add("finish the report", "by friday", tag="#Work", priority="high")
    assert out.startswith("Added to your to-do list: Finish the report (high priority), due ")
    assert store.schedules_list(enabled_only=True) == []  # a due date is not an alarm
    r = todos.items()[0]
    assert (r["tag"], r["priority"], r["due_time"], r["reminder_id"]) == ("work", 1, 0, None)
    assert datetime.fromtimestamp(r["due"]).strftime("%H:%M") == "23:59"  # a date without a time = by the end of that day
    out = todos.add("call the bank", remind_text="in 2 hours")
    assert "I'll remind you" in out
    rid = todos.find("bank")["reminder_id"]
    s = store.schedule_get(rid)
    assert s["kind"] == "reminder" and s["text"] == "To-do: Call the bank" and s["enabled"]
    assert todos.done("bank").startswith("✔ Done: Call the bank.")
    assert not store.schedule_get(rid)["enabled"]  # finishing the to-do cancels its reminder


def test_order_numbers_find_edit_delete():
    todos.add("undated thing")
    todos.add("later thing", "in 3 days")
    todos.add("urgent today", "today 11:58 pm", priority="urgent")
    todos.add("normal today", "today 11:58 pm")
    titles = [r["title"] for r in todos.items()]
    assert titles == ["Urgent today", "Normal today", "Later thing", "Undated thing"]  # soonest first, high priority first
    assert todos.find("2")["title"] == "Normal today" and todos.find("last")["title"] == "Undated thing"
    assert todos.find("the later one")["title"] == "Later thing" and todos.find("nothing like it") is None
    assert todos.edit("later", title="Later task", priority="low", tag="home").startswith("Updated 'Later thing'")
    r = todos.find("later task")
    assert (r["priority"], r["tag"]) == (3, "home")
    assert todos.edit("later task", when_text="none") == "Updated 'Later task': no due date."
    assert todos.remove("undated").startswith("Deleted from your to-do list: Undated thing")
    assert "❗ Urgent today" in todos.show() and "Say 'done 2'" in todos.show()


def test_overdue_and_bad_dates():
    rid = store.todo_add("Pay rent", due=(datetime.now() - timedelta(days=1)).timestamp(), due_time=False)
    assert todos.items()[0]["due_text"].startswith("overdue") and todos.summary_counts()["overdue"] == 1
    assert todos.add("x", "the 45th of never").startswith("I couldn't understand the date")
    assert store.todo_get(rid)["done_at"] is None


def test_tool_actions_and_today_view():
    assert todo("add", task="buy milk", tag="shopping").startswith("Added to your to-do list: Buy milk")
    assert "1. Buy milk  #shopping" in todo("list")
    assert todo("list", tag="work").startswith("Your to-do list is empty tagged #work")
    assert todo("done").startswith("Which one?")
    assert todo("done", item="1").startswith("✔ Done: Buy milk")
    assert todo("clear", item="done") == "Cleared 1 finished to-do."
    assert "✅ To-do" in todo("today") or "empty" in todo("today")


def test_old_sheet_todos_move_to_the_database(tmp_path, monkeypatch):
    """Owner's existing to-dos in the combined Excel list are copied over once; links stay in the reading list."""
    monkeypatch.setattr(config, "READ_LATER_FILE", str(tmp_path / "read_later.xlsx"))
    sid = store.schedule_add("todo: Read chapter 2", "task", (datetime.now() + timedelta(hours=3)).timestamp())
    rows = [{"type": "todo", "title": "Read chapter 2", "link": "", "tag": "study", "due": "2030-01-01 09:00",
             "saved": "2026-10-20 10:00", "note": "", "reminder": str(sid)},
            {"type": "read", "title": "A paper", "link": "https://e.com/p", "tag": "", "due": "", "saved": "2026-10-21 10:00",
             "note": "", "reminder": ""}]
    readlater._save(rows)
    store.kv_delete(todos.MIGRATED_KEY)
    assert todos.migrate_from_sheet() == 1 and todos.migrate_from_sheet() == 0  # once
    r = todos.items()[0]
    assert (r["title"], r["tag"], r["due_time"], r["reminder_id"]) == ("Read chapter 2", "study", 1, sid)
    assert store.schedule_get(sid)["kind"] == "reminder"  # the old alert stays, as the to-do's linked reminder
    assert [x["title"] for x in readlater.ordered()] == ["A paper"]


def test_voice_phrases_route_to_the_right_list():
    a = lambda t: (lambda i: (i.tool, i.args) if i else None)(fastpath.match(t))  # noqa: E731
    assert a("add finish the report to my to-do list, it's urgent") == \
        ("todo", {"action": "add", "task": "finish the report", "priority": "high"})
    assert a("add call the bank to my to-do and remind me tomorrow at 10 am")[1]["remind"] == "tomorrow at 10 am"
    assert a("remind me to call mom at 5 pm")[0] == "add_reminder"  # an alert, not a to-do
    todos.add("Submit the form")
    assert a("I finished submit the form") == ("todo", {"action": "done", "item": "submit the form"})
    assert a("what are my reminders") == ("schedules", {"action": "list"})
