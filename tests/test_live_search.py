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
