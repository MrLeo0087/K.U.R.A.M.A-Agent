"""Regression gate on the real-request test set (tests/eval): the zero-token shortcuts may only get better.
Floors are raised when the score improves (see data/eval/ scorecards); the full AI level is run by hand."""
from tests.eval import harness


def test_shortcuts_on_real_requests_stay_accurate(monkeypatch):
    from jarvis.core import config
    monkeypatch.setattr(config, "FASTPATH", True)
    cases = harness.load()
    assert len(cases) >= 200
    sc = harness.run_shortcut(cases)
    coverage, precision = sc["handled"] / len(cases), sc["right"] / max(1, sc["handled"])
    wrong = [f"#{w['id']} {w['text'][:50]!r} -> {w['got']}" for w in sc["wrong"]]
    assert coverage >= 0.55, f"shortcuts handle only {coverage:.0%}"
    # baseline 2026-10-29: 4 known mistakes (#74 'find X and send me', #77 'get it on telegram', #196/#197 two tasks
    # in one sentence) are phase-3 work; the floor goes up as they are fixed
    assert precision >= 0.96, f"shortcut mistakes ({precision:.0%} right):\n" + "\n".join(wrong)


def test_intent_map_knows_every_case_intent():
    known = set(harness.TOOL_INTENT.values()) | {"chat", "clarify", "multi", "todo.add", "todo.list", "todo.done",
                                                  "todo.delete", "todo.clear", "day.today", "reminder.list",
                                                  "reminder.cancel", "power.shutdown", "power.restart",
                                                  "readlater.add", "readlater.list", "web.news", "remote"}
    for c in harness.load():
        for intent in c.get("all") or [c["expect"]]:
            assert intent in known, (c["id"], intent)
