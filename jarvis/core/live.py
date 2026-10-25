"""Real-time answers from sources that are actually live, not search-engine snippets (which are often days old).

  sports(): ESPN's public JSON API (free, no key): find the team, then its live game, last result (with scorers)
            and next fixture, in local time. Football/soccer (all big leagues), NBA, NFL, MLB, NHL ...  0 tokens
  news():   Google News RSS (free, minutes fresh), newest first, each with its age and source.        0 tokens
  answer(): for a "what happened / who won / latest ..." question: fresh headlines + the top 2 articles' text,
            then the fast LLM answers in 1-3 sentences with dates (~1.5k tokens). Used when 0-token parts can't.
Results are cached briefly (sports 60 s, news 5 min) so repeats are free.
"""
from __future__ import annotations

import html
import logging
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

log = logging.getLogger(__name__)
_ESPN = "https://site.api.espn.com/apis/site/v2/sports"
_SEARCH = "https://site.web.api.espn.com/apis/common/v3/search"
_cache: dict[tuple, tuple[float, object]] = {}
_STOP = re.compile(r"\b(?:what(?:'s| is| was)?|who|did|does|do|is|was|the|a|an|of|for|in|on|at|today'?s?|tonight'?s?|"
                   r"yesterday'?s?|last|latest|recent|current|live|now|right|score|scores|result|results|match|matches|"
                   r"game|games|fixture|fixtures|next|upcoming|when|won|win|wins|lose|lost|play|playing|plays|"
                   r"tell|me|give|show|check|update|final|full|time|ft|vs|versus|against|between|and|how|team|"
                   r"football|soccer|basketball|cricket|kick ?off|schedule|please|kurama|happened|goal|goals)\b", re.I)


def _cached(key: tuple, ttl: float, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def _get(url: str, params: dict | None = None):
    from jarvis.tools.general import _web
    status, data = _web.get_json(url, params=params)
    return data if status == 200 else None


def _local(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()


def _when(dt: datetime) -> str:
    today = datetime.now().astimezone().date()
    d = (dt.date() - today).days
    day = {0: "today", -1: "yesterday", 1: "tomorrow"}.get(d, dt.strftime("%a %d %b"))
    return f"{day} {dt.strftime('%I:%M %p').lstrip('0')}"


# --- sports ---
def team_query(text: str) -> str:
    q = _STOP.sub(" ", text or "")
    q = re.sub(r"[?!.,']", " ", q)
    return " ".join(q.split())


_SPORT_WORDS = {"cricket": "cricket", "football": "soccer", "soccer": "soccer", "basketball": "basketball",
                "nba": "basketball", "nfl": "football", "baseball": "baseball", "mlb": "baseball", "hockey": "hockey",
                "nhl": "hockey", "rugby": "rugby", "tennis": "tennis"}


def sport_in(text: str) -> str:
    m = re.search(r"\b(" + "|".join(_SPORT_WORDS) + r")\b", text or "", re.I)
    return _SPORT_WORDS[m.group(1).lower()] if m else ""


def find_team(name: str, sport: str = "") -> dict | None:
    """Best ESPN team for a name: {id, name, sport, league} (only teams with a league = schedulable)."""
    data = _cached(("team", name.lower()), 86400, lambda: _get(_SEARCH, {"query": name, "limit": 8, "type": "team"}))
    items = [i for i in (data or {}).get("items", []) if i.get("league") and i.get("sport")
             and (not sport or i["sport"] == sport or (sport == "soccer" and i["sport"] == "soccer"))]
    if not items:
        return None
    want = name.lower()
    items.sort(key=lambda i: (want not in i.get("displayName", "").lower(),
                              bool(re.search(r"\b(?:II|U-?\d{2}|Under-\d+|Women|Reserves|B)\b", i["displayName"]))))
    i = items[0]
    return {"id": i["id"], "name": i["displayName"], "sport": i["sport"], "league": i["league"]}


def _line(ev: dict, team_id: str) -> str:
    c = ev["competitions"][0]
    st = c.get("status", {}).get("type", {})
    teams = []
    for x in sorted(c["competitors"], key=lambda x: x.get("homeAway") != "home"):
        sc = x.get("score")
        sc = sc.get("displayValue") if isinstance(sc, dict) else sc
        teams.append((x["team"].get("displayName") or x["team"].get("name"), sc))
    when = _when(_local(ev["date"]))
    comp = (ev.get("league") or {}).get("abbreviation") or (ev.get("league") or {}).get("name") or ""
    when = f"{when}, {comp}" if comp else when
    if st.get("state") == "pre":
        return f"{teams[0][0]} vs {teams[1][0]}, {when}"
    score = f"{teams[0][0]} {teams[0][1]}-{teams[1][1]} {teams[1][0]}"
    return f"{score} ({st.get('shortDetail') or st.get('detail', '')}, {when})"


def _scorers(sport: str, league: str, event_id: str) -> str:
    d = _get(f"{_ESPN}/{sport}/{league}/summary", {"event": event_id}) or {}
    goals = []
    for k in d.get("keyEvents", []):
        if k.get("scoringPlay"):
            who = next((p["athlete"]["displayName"] for p in k.get("participants", []) if p.get("athlete")), "")
            goals.append(f"{who} {k.get('clock', {}).get('displayValue', '')}".strip())
    return ("Goals: " + ", ".join(goals[:8])) if goals else ""


def sports(text: str) -> str | None:
    """Live / last / next game for the team named in `text`, or None if no team found."""
    name = team_query(text)
    if not name:
        return None
    team = find_team(name, sport_in(text))
    if not team:
        return None  # unknown team or a sport ESPN has no schedules for here (e.g. cricket) -> fresh-news answer
    sport, league, tid = team["sport"], team["league"], team["id"]
    every = "all" if sport == "soccer" else league  # soccer: every competition (league + cups + Champions League)

    def load():
        sched = _get(f"{_ESPN}/{sport}/{every}/teams/{tid}/schedule") or {}
        info = _get(f"{_ESPN}/{sport}/{league}/teams/{tid}") or {}
        return sched, info
    sched, info = _cached(("sched", sport, league, tid), 60, load)
    events = sorted(sched.get("events", []) + (info.get("team", {}).get("nextEvent") or []), key=lambda e: e["date"])
    seen, uniq = set(), []
    for e in events:
        if e["id"] not in seen:
            seen.add(e["id"])
            uniq.append(e)
    state = lambda e: e["competitions"][0].get("status", {}).get("type", {}).get("state")  # noqa: E731
    live = [e for e in uniq if state(e) == "in"]
    done = [e for e in uniq if state(e) == "post"]
    nxt = [e for e in uniq if state(e) == "pre" and _local(e["date"]) > datetime.now().astimezone()]
    out = []
    if live:
        out.append("LIVE: " + _line(live[-1], tid))
        if sport == "soccer" and (g := _scorers(sport, every, live[-1]["id"])):
            out.append(g)
    if done:
        out.append(("Last result: " if live or nxt else "Result: ") + _line(done[-1], tid))
        if sport == "soccer" and not live and (g := _scorers(sport, every, done[-1]["id"])):
            out.append(g)
    if nxt:
        out.append("Next: " + _line(nxt[0], tid))
    if not out:
        return None
    if not live and not nxt and done and (datetime.now().astimezone() - _local(done[-1]["date"])).days > 45:
        return None  # only an old result: probably the wrong team/sport -> let the fresh-news answer handle it
    stamp = datetime.now().astimezone().strftime("%I:%M %p").lstrip("0")
    return f"{team['name']} (ESPN, live data as of {stamp}):\n" + "\n".join(out)


# --- news ---
def news(query: str, k: int = 5, days: int = 1) -> list[dict]:
    """Newest Google News items for `query` within `days` (falls back to 7 days if empty)."""
    from jarvis.tools.general import _web

    def load(d: int):
        url = (f"https://news.google.com/rss/search?q={quote_plus(query)}+when:{d}d&hl=en-US&gl=US&ceid=US:en")
        r = _web.client().get(url)
        items = []
        for raw in re.findall(r"<item>(.*?)</item>", r.text, re.S):
            title = html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", (re.search(r"<title>(.*?)</title>", raw, re.S)
                                                                    or [None, ""])[1]))
            link = (re.search(r"<link>(.*?)</link>", raw, re.S) or [None, ""])[1].strip()
            src = html.unescape((re.search(r"<source[^>]*>(.*?)</source>", raw, re.S) or [None, ""])[1])
            try:
                when = parsedate_to_datetime(re.search(r"<pubDate>(.*?)</pubDate>", raw).group(1))
            except (AttributeError, TypeError, ValueError):
                continue
            if src and title.endswith(" - " + src):
                title = title[: -len(src) - 3]
            items.append({"title": title, "url": link, "source": src, "when": when})
        items.sort(key=lambda i: i["when"], reverse=True)
        return items
    items = _cached(("news", query.lower(), days), 300, lambda: load(days))
    if not items and days < 7:
        items = _cached(("news", query.lower(), 7), 300, lambda: load(7))
    return items[:k]


def _ago(dt: datetime) -> str:
    s = (datetime.now(timezone.utc) - dt).total_seconds()
    if s < 3600:
        return f"{max(1, int(s // 60))} min ago"
    if s < 86400:
        return f"{int(s // 3600)} h ago"
    return f"{int(s // 86400)} d ago"


def news_text(query: str, k: int = 5) -> str:
    items = news(query, k)
    if not items:
        return f"No recent news found for '{query}'."
    return "Latest news:\n" + "\n".join(f"{n}. {i['title']} ({i['source']}, {_ago(i['when'])})"
                                        for n, i in enumerate(items, 1))


# --- fresh answer (LLM over fresh sources) ---
def _article_text(url: str, limit: int = 1800) -> str:
    try:
        from jarvis.tools.general.read_webpage import fetch
        title, text = fetch(url)
        return text[:limit]
    except Exception as e:  # noqa: BLE001 - one bad page shouldn't sink the answer
        log.info("article fetch failed: %s", e)
        return ""


def answer(question: str) -> str:
    """Answer a current-events question from minutes-fresh sources, with dates. ~1.5k tokens."""
    q = team_query(question) or question
    items = news(question, 6) or news(q, 6)
    if not items:
        return f"I couldn't find anything recent about that. ({question})"
    now = datetime.now().astimezone()
    heads = "\n".join(f"- [{i['when'].astimezone().strftime('%d %b %H:%M')}] {i['title']} ({i['source']})"
                      for i in items)
    bodies = "\n\n".join(f"[{i['source']}, {i['when'].astimezone().strftime('%d %b %H:%M')}]\n{t}"
                         for i in items[:2] if (t := _article_text(i["url"])))
    from jarvis.core import llm
    msgs = [{"role": "system", "content": "Answer the question ONLY from the sources below, in 1-3 short sentences. "
                                          "Prefer the newest source. Say the date/time of the fact. If the sources "
                                          "don't contain the answer, say so plainly. No guessing."},
            {"role": "user", "content": f"Now: {now.strftime('%A %d %B %Y %H:%M %Z')}\nQuestion: {question}\n\n"
                                        f"Headlines (newest first):\n{heads}\n\nArticles:\n{bodies[:4000]}"}]
    try:
        reply = llm.chat(msgs, tier="fast", purpose="live_answer", max_tokens=300)
        text = (reply.text or "").strip()
    except Exception as e:  # noqa: BLE001 - fall back to the 0-token headlines
        log.warning("live answer LLM failed: %s", e)
        text = ""
    src = ", ".join(dict.fromkeys(i["source"] for i in items[:3] if i["source"]))
    return (text + f"\n(Sources: {src}; newest {_ago(items[0]['when'])})") if text else news_text(question)


def search(query: str, kind: str = "auto") -> str:
    """Router: sports -> ESPN, news -> headlines, question -> fresh answer."""
    if kind in ("auto", "sports") and (kind == "sports" or SPORTS_Q.search(query)):
        try:
            if r := sports(query):
                return r
        except Exception as e:  # noqa: BLE001 - fall through to a fresh answer
            log.warning("sports lookup failed: %s", e)
        return answer(query)  # not a team ESPN knows (e.g. cricket): answer from fresh news
    if kind == "news" or (kind == "auto" and re.match(r"^(?:latest\s+|today'?s\s+|recent\s+)?(?:news|headlines)\b",
                                                      query, re.I)):
        topic = re.sub(r"^(?:latest\s+|today'?s\s+|recent\s+)?(?:news|headlines)\s*(?:about|on|of|for|from|in)?\s*",
                       "", query, flags=re.I) or "top stories"
        return news_text(topic)
    return answer(query)


SPORTS_Q = re.compile(r"\b(?:score|scores|result|results|match|game|fixture|kick ?off|won|win|beat|lost|lose|draw|"
                      r"vs\.?|versus|playing|play\s+next|next\s+(?:match|game)|goals?|full\s*time|half\s*time)\b", re.I)
