from datetime import datetime, timedelta

from jarvis.core import brief, config, expenses as ex, fastpath, habits as hb, notify, store

NOW = datetime(2026, 10, 27, 9, 0)


def test_expenses_add_report_budget_edit(monkeypatch):
    assert "Rs 500 for food" in ex.add("spent 500 on momo", NOW)
    assert "yesterday" in ex.add("paid 1,500 for internet bill yesterday", NOW)
    assert ex.add("got 20000 salary", NOW).startswith("Added income Rs 20,000")
    assert "shopping" in ex.add("spent 2k on shoes", NOW)
    assert ex.add("bought nothing", NOW).startswith("How much")
    rep = ex.report("month", now=NOW)
    assert "Rs 4,000 this month" in rep and "Income Rs 20,000, saved Rs 16,000" in rep
    assert ex.report("today", now=NOW).startswith("You spent Rs 2,500 today")
    assert "on food" in ex.report("month", "food", NOW)
    ex.set_budget("food", 1000)
    assert "Over the food budget" in ex.add("spent 600 on dinner", NOW)
    assert "Rs 450" in ex.edit_last("the last one was 450")
    assert "Deleted Rs 450" in ex.delete("last")
    assert "4." in ex.list_text("month", NOW)
    d = ex.dashboard(NOW)
    assert d["month"] == 4000 and d["top"][0]["cat"] == "shopping" and len(d["last7"]) == 7


def test_bills_remind_once_and_pay(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "notify", lambda *a, **k: sent.append(a) or [])
    ex.add_bill("internet", 1500, 5)
    assert ex.check_bills(NOW) == 1 and ex.check_bills(NOW) == 0 and "internet" in sent[0][1]
    assert "Logged the internet bill, Rs 1,500" in ex.pay_bill("paid internet", NOW)
    assert ex.bills_due(NOW) == [] and ex.pay_bill("paid rent", NOW) is None


def test_habits_streaks_and_reminders(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "notify", lambda *a, **k: sent.append(a) or [])
    assert hb.parse_new("drink water 8 glasses a day, remind me at 10 am") == ("drink water", 8, "glasses", "10:00")
    hb.add("drink water", 8, "glasses", "10:00")
    hb.add("exercise")
    for i in (3, 2, 1):  # three earlier days of exercise
        hb.check_in("did exercise", NOW - timedelta(days=i))
    assert "Streak: 4 days" in hb.check_in("I did exercise", NOW)
    assert "3/8" in hb.check_in("I drank 3 glasses of water", NOW)
    ov = {h["name"]: h for h in hb.overview(NOW)}
    assert ov["exercise"]["streak"] == 4 and ov["exercise"]["week"][-4:] == [True] * 4 and not ov["drink water"]["done"]
    assert "Still to do today: drink water" in hb.status_text(NOW)
    assert hb.remind_due(NOW.replace(hour=11)) == 1 and hb.remind_due(NOW.replace(hour=11)) == 0
    assert "drink water" in sent[0][1]
    assert "Removed" in hb.undo("exercise", NOW) and hb.streak("exercise", today=NOW.date()) == 3
    assert "Stopped tracking exercise" in hb.delete("exercise habit")


def test_routing(monkeypatch):
    m = fastpath.match
    assert m("spent 500 on food").args == {"action": "add", "text": "spent 500 on food"}
    assert m("how much did I spend on food this week").args == {"action": "report", "period": "week", "category": "food"}
    assert m("set my food budget to 8000").args["amount"] == 8000
    assert m("remind me to pay internet 1500 every month on the 5th").args == {"action": "bill", "text": "internet",
                                                                               "amount": 1500.0, "day": 5}
    assert m("spent 2 hours on coding") is None and m("I got 90 marks") is None
    assert m("got 20000 salary").args["action"] == "add" and getattr(m("the exam got postponed to December 10"), "tool", "") != "expenses"
    assert m("my habits").tool == "habits" and m("/money week").args["period"] == "week"
    hb.add("exercise")
    assert m("did exercise").args["action"] == "done" and m("I didn't do exercise").args["action"] == "undo"
    assert m("give me my morning brief").tool == "_brief"


def test_brief_once_a_day_and_watch(monkeypatch):
    monkeypatch.setattr(config, "BRIEF", True)
    sent = []
    monkeypatch.setattr(notify, "notify", lambda *a, **k: sent.append(a) or [])
    monkeypatch.setattr(brief, "_weather", lambda: "It's 18°C and clear sky in Nepalgunj.")
    hb.add("exercise")
    ex.add("spent 300 on tea yesterday", NOW)
    store.kv_set(brief.DONE_KEY, "")
    text = brief.deliver("unlock", NOW)
    assert text.startswith("Good morning") and "18°C" in text and "Habits today: exercise" in text \
        and "Yesterday you spent Rs 300" in text
    assert brief.deliver("unlock", NOW) is None and len(sent) == 1
    assert brief.take_pending() == text and brief.take_pending() == ""
    assert brief.deliver("unlock", NOW.replace(hour=3) + timedelta(days=1)) is None  # 3 AM = still last night
    w = brief.Watch()
    assert w.tick(True, 1000) is None and w.tick(False, 1015) == "unlock"
    assert w.tick(False, 1030) is None and w.tick(False, 5000) == "wake"
    monkeypatch.setattr(config, "BRIEF", False)
    store.kv_set(brief.DONE_KEY, "")
    assert brief.deliver("unlock", NOW) is None
