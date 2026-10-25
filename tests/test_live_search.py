from datetime import datetime, timedelta, timezone

from jarvis.core import fastpath, live


def _ev(eid, days, state, home=("Inter Miami CF", "2"), away=("DC United", "1")):
    d = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%MZ")
    return {"id": eid, "date": d, "league": {"abbreviation": "MLS"}, "competitions": [{
        "status": {"type": {"state": state, "shortDetail": "FT" if state == "post" else "45'"}},
        "competitors": [{"homeAway": "home", "team": {"displayName": home[0]}, "score": {"displayValue": home[1]}},
                        {"homeAway": "away", "team": {"displayName": away[0]}, "score": {"displayValue": away[1]}}]}]}


def test_sports_last_and_next(monkeypatch):
    live._cache.clear()

    def get(url, params=None):
        if "search" in url:
            return {"items": [{"id": "1", "displayName": "Inter Miami CF", "sport": "soccer", "league": "usa.1"}]}
        if url.endswith("/schedule"):
            return {"events": [_ev("2", -1, "post"), _ev("1", -8, "post")]}
        if url.endswith("/summary"):
            return {"keyEvents": [{"scoringPlay": True, "clock": {"displayValue": "10'"},
                                   "participants": [{"athlete": {"displayName": "Messi"}}]}]}
        return {"team": {"nextEvent": [_ev("3", 3, "pre")]}}
    monkeypatch.setattr(live, "_get", get)
    out = live.sports("what is the result of today inter miami match")
    assert "Last result: Inter Miami CF 2-1 DC United (FT, yesterday" in out
    assert "Goals: Messi 10'" in out and "Next: Inter Miami CF vs DC United" in out


def test_team_query_and_sport():
    assert live.team_query("what is the result of today inter miami match") == "inter miami"
    assert live.sport_in("nepal cricket score") == "cricket"


def test_news_parsing(monkeypatch):
    live._cache.clear()
    rss = ("<rss><channel><item><title>Big win - BBC</title><link>https://x/1</link><pubDate>"
           + datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
           + "</pubDate><source url='https://bbc.com'>BBC</source></item></channel></rss>")

    class R:
        text = rss

    class C:
        def get(self, url):
            return R()
    from jarvis.tools.general import _web
    monkeypatch.setattr(_web, "client", lambda: C())
    assert "1. Big win (BBC, 1 min ago)" in live.news_text("nepal")


def test_intents():
    assert fastpath.match("what is the result of today inter miami match").tool == "live_search"
    assert fastpath.match("did real madrid win").args["kind"] == "sports"
    assert fastpath.match("latest news about Nepal").args == {"query": "news Nepal", "kind": "news"}
    for t in ("did the tests pass", "what is the result of my exam", "did my training finish"):
        i = fastpath.match(t)
        assert i is None or i.tool != "live_search", t


def test_more_sport_phrases_and_false_friends():
    for t in ("Tell.me today man united match", "man united match today", "how did man united do",
              "man united vs bournemouth", "what happened in the man united match"):
        assert fastpath.match(t).tool == "live_search", t
    assert fastpath.match("open vs code").tool == "open_app"
    i = fastpath.match("find the best match")
    assert i is None or i.tool != "live_search"


def test_price_and_fresh_routing():
    for t in ("what is the gold price in Nepal today", "dollar rate today", "bitcoin price", "tesla stock price",
              "price of iphone 17 in nepal", "who is leading the election now"):
        assert fastpath.match(t).tool == "live_search", t
    for t in ("what is the weather today", "what time is it now", "how is my training going now"):
        assert fastpath.match(t).tool != "live_search", t


def test_gold_and_fx_formatting(monkeypatch):
    live._cache.clear()
    gold = [{"todayDate": "2026-10-25T04:50:30+00:00", "yestardayDate": "2026-10-19T04:52:59+00:00",
             "rateType": "छापावाल सुन (१ तोला)", "todayBaseRatePerGram": 278500.0, "yestardayBaseRatePerGram": 290200.0}]
    fx = {"rates": {"NPR": 152.0, "USD": 1.0, "INR": 95.0}, "time_last_update_utc": "Sun, 25 Oct 2026 00:02"}
    monkeypatch.setattr(live, "_get", lambda url, params=None: gold if "fenegosida" in url else fx)
    assert "Fine gold (hallmark): Rs 278,500 per tola, down Rs 11,700" in live.facts("gold price in nepal today")
    assert "1 USD = Rs 152.00" in live.facts("dollar rate today")
    assert "1 INR = Rs 1.60" in live.facts("indian rupee rate")
