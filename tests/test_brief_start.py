from jarvis.core import brief, fastpath


def test_brief_on_the_first_look_after_a_fresh_boot():
    w = brief.Watch()
    assert w.tick(False) == "start"  # KURAMA just started and the session is unlocked: the day's first use
    assert w.tick(False) is None
    w2 = brief.Watch()
    assert w2.tick(True) is None and w2.tick(False) == "unlock"  # started at the lock screen: on unlock


def test_send_me_the_morning_brief():
    for t in ("send morning brief", "send me the morning brief", "show my brief", "give me my morning brief"):
        i = fastpath.match(t)
        assert i is not None and i.tool == "_brief", t
