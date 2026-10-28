"""Real-time answers from sources that are actually live, not search-engine snippets (which are often days old).

  sports(): ESPN's public JSON API (free, no key): find the team, then its live game, last result (with scorers)
            and next fixture, in local time. Football/soccer (all big leagues), NBA, NFL, MLB, NHL ...  0 tokens
  news():   Google News RSS (free, minutes fresh), newest first, each with its age and source.        0 tokens
  facts():  prices/rates with a reliable free live API: gold/silver in Nepal (FENEGOSIDA, official), currency
            rates in NPR (open.er-api), crypto (CoinGecko), stocks (Yahoo Finance).                       0 tokens
  answer(): ANY other current question: Google News (< 1 day) + DuckDuckGo (< 1 week), top pages read, then the
            fast LLM answers ONLY from them, with dates (~1.5-2k tokens).
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
                   r"football|soccer|basketball|cricket|kick ?off|schedule|please|kurama|happened|goal|goals|"
                   # Roman Nepali / Hindi fillers: 'aja arsenal ko match ko result k vayo'
                   r"aja|aaja|aaj|aj|hijo|kal|ko|ka|ki|ke|k|kya|kasto|kesto|vayo|bhayo|bhaye|hua|huwa|tyo|yo|ma|ni|"
                   r"hai|ho|cha|xa|thiyo|kun|jityo|haryo|jita|hara|khel|kheleko|khela|"
                   r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
                   r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|\d{1,4}(?:st|nd|rd|th)?)\b", re.I)


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


# --- prices and rates from official / market-data APIs (0 tokens) ---
_GOLD_Q = re.compile(r"\b(?:gold|silver|sun|chandi|सुन|चाँदी)\b", re.I)
_FX_Q = re.compile(r"\b(?:exchange\s+rate|dollar|usd|euro|eur|pound|gbp|rupee|inr|indian\s+rupee|yen|jpy|yuan|cny|riyal|"
                   r"sar|dirham|aed|ringgit|myr|won|krw|aud|cad|qatari|qar|kuwaiti|kwd)\b", re.I)
_CRYPTO = {"bitcoin": "bitcoin", "btc": "bitcoin", "ethereum": "ethereum", "eth": "ethereum", "solana": "solana",
           "sol": "solana", "dogecoin": "dogecoin", "doge": "dogecoin", "xrp": "ripple", "ripple": "ripple",
           "bnb": "binancecoin", "cardano": "cardano", "ada": "cardano", "usdt": "tether", "tether": "tether"}
_STOCK_Q = re.compile(r"\b(?:stock|share|shares)\s+(?:price|value|rate)\b|\bprice\s+of\s+.+\s+(?:stock|shares?)\b", re.I)
_FX_CODES = {"dollar": "USD", "usd": "USD", "euro": "EUR", "eur": "EUR", "pound": "GBP", "gbp": "GBP", "rupee": "INR",
             "inr": "INR", "indian rupee": "INR", "yen": "JPY", "jpy": "JPY", "yuan": "CNY", "cny": "CNY",
             "riyal": "SAR", "sar": "SAR", "dirham": "AED", "aed": "AED", "ringgit": "MYR", "myr": "MYR",
             "won": "KRW", "krw": "KRW", "aud": "AUD", "cad": "CAD", "qatari": "QAR", "qar": "QAR",
             "kuwaiti": "KWD", "kwd": "KWD"}


def _money(n: float) -> str:
    return f"Rs {n:,.0f}" if n >= 100 else f"Rs {n:,.2f}"


def gold_nepal() -> str | None:
    """Official daily gold/silver rates from FENEGOSIDA (Nepal's gold & silver dealers' federation)."""
    rows = _cached(("gold",), 600, lambda: _get("https://api.fenegosida.org/api/website/v1/Dashboard/today"))
    if not isinstance(rows, list) or not rows:
        return None
    names = {"छापावाल सुन": "Fine gold (hallmark)", "तेजाबी सुन": "Tejabi gold", "असली चाँदी": "Silver"}
    out, when = [], ""
    for r in rows:
        label = next((v for k, v in names.items() if k in r.get("rateType", "")), r.get("rateType", ""))
        unit = "tola" if "तोला" in r.get("rateType", "") else "10 g"
        now, before = float(r.get("todayBaseRatePerGram") or 0), float(r.get("yestardayBaseRatePerGram") or 0)
        diff = now - before
        trend = f", {'up' if diff > 0 else 'down'} {_money(abs(diff))} since {_local(r['yestardayDate']).strftime('%d %b')}" \
            if before and diff else ""
        out.append(f"{label}: {_money(now)} per {unit}{trend}")
        when = _local(r["todayDate"]).strftime("%d %b %Y %I:%M %p")
    return "Gold/silver in Nepal (FENEGOSIDA, " + when + "):\n" + "\n".join(out)


def forex(text: str) -> str | None:
    t = text.lower()
    codes = list(dict.fromkeys(c for w, c in _FX_CODES.items() if re.search(r"\b" + w + r"\b", t)))
    if not codes:
        codes = ["USD", "EUR", "INR", "GBP"] if re.search(r"exchange\s+rate", t) else []
    if not codes:
        return None
    data = _cached(("fx",), 1800, lambda: _get("https://open.er-api.com/v6/latest/USD"))
    rates = (data or {}).get("rates") or {}
    npr = rates.get("NPR")
    if not npr:
        return None
    lines = [f"1 {c} = Rs {npr / rates[c]:,.2f}" for c in codes if c in rates and c != "NPR"]
    upd = (data or {}).get("time_last_update_utc", "")[:16]
    return ("Exchange rates in Nepali rupees (market rate, updated " + upd + " UTC; banks/NRB differ slightly):\n"
            + "\n".join(lines)) if lines else None


def crypto(text: str) -> str | None:
    ids = list(dict.fromkeys(v for k, v in _CRYPTO.items() if re.search(r"\b" + k + r"\b", text.lower())))
    if not ids:
        return None
    data = _cached(("cg", tuple(ids)), 120, lambda: _get(
        "https://api.coingecko.com/api/v3/simple/price",
        {"ids": ",".join(ids), "vs_currencies": "usd,npr", "include_24hr_change": "true"}))
    if not data:
        return None
    lines = []
    for i in ids:
        d = data.get(i) or {}
        if "usd" in d:
            ch = d.get("usd_24h_change")
            lines.append(f"{i.title()}: ${d['usd']:,.2f}" + (f" (Rs {d['npr']:,.0f})" if d.get("npr") else "")
                         + (f", {ch:+.1f}% in 24 h" if ch is not None else ""))
    return "Crypto (CoinGecko, live):\n" + "\n".join(lines) if lines else None


def stock(text: str) -> str | None:
    name = re.sub(r"\b(?:stock|share|shares|price|value|rate|of|the|what(?:'s| is)|today|now|current|live|latest)\b",
                  " ", text, flags=re.I)
    name = " ".join(name.split())
    if not name:
        return None
    hdr = {"User-Agent": "Mozilla/5.0"}
    from jarvis.tools.general import _web
    st, found = _web.get_json("https://query1.finance.yahoo.com/v1/finance/search",
                              params={"q": name, "quotesCount": 1, "newsCount": 0}, headers=hdr)
    quotes = (found or {}).get("quotes") or []
    if st != 200 or not quotes:
        return None
    sym = quotes[0]["symbol"]
    st, chart = _web.get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                              params={"range": "1d", "interval": "1d"}, headers=hdr)
    try:
        m = chart["chart"]["result"][0]["meta"]
    except (TypeError, KeyError, IndexError):
        return None
    prev = m.get("chartPreviousClose") or m.get("previousClose")
    ch = f", {((m['regularMarketPrice'] - prev) / prev * 100):+.2f}% today" if prev else ""
    when = datetime.fromtimestamp(m["regularMarketTime"]).astimezone().strftime("%d %b %I:%M %p")
    return (f"{quotes[0].get('longname') or quotes[0].get('shortname') or sym} ({sym}): "
            f"{m['regularMarketPrice']:,.2f} {m.get('currency', '')}{ch} (Yahoo Finance, as of {when})")


def facts(text: str) -> str | None:
    """0-token answers for prices/rates that have a reliable free live source."""
    try:
        if _GOLD_Q.search(text) and re.search(r"\b(?:price|rate|cost|today|now|current|bhau|भाउ|kati)\b", text, re.I):
            return gold_nepal()
        if re.search(r"\b(?:crypto|coin)\b", text, re.I) or any(re.search(r"\b" + k + r"\b", text.lower())
                                                                  for k in _CRYPTO):
            if r := crypto(text):
                return r
        if _STOCK_Q.search(text):
            return stock(text)
        if _FX_Q.search(text) and re.search(r"\b(?:rate|price|to|in|npr|nepali|value|today|how\s+much)\b", text, re.I):
            return forex(text)
    except Exception as e:  # noqa: BLE001 - a dead API falls back to the fresh-source answer
        log.warning("facts lookup failed: %s", e)
    return None


# --- fresh answer (LLM over fresh sources) ---
_RANK_LINE = re.compile(r"^\s*(?:#\s*)?(?:\d{1,2})(?:[.):]|\s*[-–—]|\s+(?=[A-Z]))|^\s*(?:\d{1,2}(?:st|nd|rd|th))\b", re.I)
_LIST_Q = re.compile(r"\btop\s*\d+|\btop\s+(?:ten|five|three|twenty)|\branking|\brank(?:ed|s)?\b|\blist\b|\bwinners?\b|\bstandings?\b|"
                     r"\bshortlist|\bnominees?\b|\bleaderboard|\bpoints\s+table|\bwho\s+(?:won|are|were)\b.*\b(?:award|ballon|oscar|prize)", re.I)


def relevant(text: str, question: str, limit: int) -> str:
    """The part of a page that answers: for rankings the block of numbered lines (articles bury the list under an
    intro), else the paragraphs that share the most words with the question; the start of the page as a fallback."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    ranks = [i for i, ln in enumerate(lines) if _RANK_LINE.match(ln) and len(ln) < 220]
    if len(ranks) >= 3:
        best, cur = [ranks[0]], [ranks[0]]  # the longest run of rank lines (gaps of <= 6 lines allowed)
        for i in ranks[1:]:
            cur = cur + [i] if i - cur[-1] <= 6 else [i]
            if len(cur) > len(best):
                best = cur
        a, b = max(0, best[0] - 4), min(len(lines), best[-1] + 4)
        block = "\n".join(lines[a:b])
        if len(block) >= 80:
            return block[:limit]
    words = {w for w in re.findall(r"[a-z0-9']{4,}", question.lower())}
    scored = sorted(range(len(lines)), key=lambda i: -len(words & set(re.findall(r"[a-z0-9']{4,}", lines[i].lower()))))
    keep = sorted(scored[:25])
    out = "\n".join(lines[i] for i in keep)
    return (out if len(out) > 200 else "\n".join(lines))[:limit]


def _article_text(url: str, limit: int = 1800, question: str = "") -> str:
    try:
        from jarvis.tools.general import _web
        from jarvis.tools.general.read_webpage import fetch
        ctype, body = fetch(url)
        if "html" not in ctype:
            return ""
        text = _web.html_to_text(body)[1]
        return relevant(text, question, limit) if question else text[:limit]
    except Exception as e:  # noqa: BLE001 - one bad page shouldn't sink the answer
        log.info("article fetch failed: %s", e)
        return ""


def _web_recent(query: str, k: int = 5) -> list[dict]:
    """DuckDuckGo results from the past week (direct links, unlike Google News redirects)."""
    try:
        from ddgs import DDGS
        rows = DDGS(timeout=10).text(query, max_results=k, timelimit="w") or []
        return [{"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")} for r in rows]
    except Exception as e:  # noqa: BLE001
        log.info("ddg recent failed: %s", e)
        return []


def answer(question: str) -> str:
    """Answer a current question from fresh sources (news < 1 day + web < 1 week, top pages read), with dates."""
    items = news(question, 6)
    web = _cached(("ddgw", question.lower()), 300, lambda: _web_recent(question))
    if not items and not web:
        return f"I couldn't find anything recent about that. ({question})"
    now = datetime.now().astimezone()
    heads = "\n".join(f"- [{i['when'].astimezone().strftime('%d %b %H:%M')}] {i['title']} ({i['source']})"
                      for i in items)
    snips = "\n".join(f"- {w['title']}: {w['snippet'][:220]} ({w['url'][:80]})" for w in web)
    listy = bool(_LIST_Q.search(question))
    if listy:  # rankings / lists: read more pages, at the numbered block, and let the smart model copy ONE source
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as ex:
            texts = list(ex.map(lambda w: _article_text(w["url"], 2200, question), web[:4]))
        bodies = "\n\n".join(f"[PAGE {n}: {w['url']}]\n{t}" for n, (w, t) in enumerate(zip(web[:4], texts), 1) if t)
    else:
        bodies = "\n\n".join(f"[{w['url'][:80]}]\n{t}" for w in web[:2] if (t := _article_text(w["url"])))
    from jarvis.core import llm
    rules = ("Answer ONLY from the sources below. For a ranking or list: copy it from ONE page exactly as that page "
             "lists it (same order, names, teams), start with one line naming that page and its date and whether it "
             "is the OFFICIAL result or a prediction / power ranking, then one item per line. If no page lists every "
             "place, give only what it lists and write 'not listed in the sources' for the rest. Never fill a gap, "
             "never mix pages, never use old knowledge.") if listy else (
             "Answer the question ONLY from the sources below, in 1-3 short sentences. Prefer the newest source and "
             "give the date of the fact (and the number with its unit for prices). If the sources don't contain the "
             "answer, say so plainly. No guessing, no old knowledge.")
    msgs = [{"role": "system", "content": rules},
            {"role": "user", "content": f"Now: {now.strftime('%A %d %B %Y %H:%M %Z')}\nQuestion: {question}\n\n"
                                        f"News headlines (newest first):\n{heads or '-'}\n\nWeb results (past week):\n"
                                        f"{snips or '-'}\n\nPages:\n{bodies[:9000 if listy else 3500] or '-'}"}]
    try:
        reply = llm.chat(msgs, tier="smart" if listy else "fast", purpose="live_answer", max_tokens=700 if listy else 300)
        text = re.sub(r"【[^】]*】", "", (reply.text or "")).strip()  # gpt-oss inline citation marks
    except Exception as e:  # noqa: BLE001 - fall back to the 0-token headlines
        log.warning("live answer LLM failed: %s", e)
        text = ""
    src = ", ".join(dict.fromkeys([i["source"] for i in items[:2] if i["source"]] +
                                  [re.sub(r"^https?://(?:www\.)?([^/]+).*", r"\1", w["url"]) for w in web[:2]]))
    if text:
        return text + f"\n(Sources: {src})"
    return news_text(question) if items else format_web(web)


def format_web(rows: list[dict]) -> str:
    return "Recent results:\n" + "\n".join(f"{n}. {r['title']} - {r['snippet'][:140]}" for n, r in enumerate(rows, 1))


def search(query: str, kind: str = "auto") -> str:
    """Router: prices/rates -> official APIs, sports -> ESPN, news -> headlines, anything else -> fresh answer."""
    if kind in ("auto", "answer") and (f := facts(query)):
        return f
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
