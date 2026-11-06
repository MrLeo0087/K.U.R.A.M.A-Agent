import random
from datetime import datetime

from jarvis.core import fastpath, phrases, suggest


def test_pool_is_big_and_every_chip_is_a_0_token_answer():
    assert suggest.total() >= 250
    bad = [q for k, v in suggest.POOL.items() if k != "agent" for q in v if fastpath.match(q) is None]
    # (the coding agent's chips are matched by its own meaning examples while it is on, else offered: 0 tokens)
    assert not bad, bad
    for q in ("Delete the last expense", "Free port 5173", "Lock the screen", "Spent 100 on tea"):
        assert all(q not in v for v in suggest.POOL.values())  # a chip sends at once: nothing that changes things


def test_random_mixed_and_coding_weighted():
    rng = random.Random(7)
    seen = set()
    code_hits = plain_hits = 0
    for _ in range(40):
        suggest._recent.clear()
        a = suggest.pick(4, datetime(2026, 10, 27, 14), coding=True, rng=rng)
        b = suggest.pick(4, datetime(2026, 10, 27, 14), coding=False, rng=rng)
        assert len(set(a)) == 4 and len(set(b)) == 4
        seen.update(a + b)
        code_hits += sum(x in suggest.POOL["code"] for x in a)
        plain_hits += sum(x in suggest.POOL["code"] for x in b)
    assert len(seen) > 120  # really random, not the same few
    assert code_hits > 2 * plain_hits and code_hits < 40 * 4 * 0.8  # more coding while coding, but not only


def test_greetings_vary():
    hellos = {phrases.greeting(datetime(2026, 10, 27, 9), random.Random(i)) for i in range(30)}
    assert len(hellos) > 15
    assert len({fastpath.match("bye").args["en"] for _ in range(30)}) > 3
    assert phrases.bye("good night")["en"] in phrases.NIGHT_BYE
