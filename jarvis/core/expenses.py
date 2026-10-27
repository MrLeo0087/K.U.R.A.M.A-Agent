"""Money tracker (0 tokens): what I spend and earn, by day / week / month / year, budgets and monthly bills.

One Excel file the user can also edit by hand: ~/Documents/KURAMA/expenses.xlsx
  Money   : Date, Type (expense/income), Amount, Category, Note
  Budgets : Category, Monthly   ('total' = the whole month)
  Bills   : Name, Amount, Category, Day, Last paid   (a reminder on that day of each month until 'paid X')
Words -> rows with regex (amount, category from keywords, yesterday/date); reports are plain sums.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from jarvis.core import config, sheets, store

MONEY_HEAD = ["Date", "Type", "Amount", "Category", "Note"]
BUDGET_HEAD = ["Category", "Monthly"]
BILL_HEAD = ["Name", "Amount", "Category", "Day", "Last paid"]
CATS = {  # category: words that point to it
    "food": "food|lunch|dinner|breakfast|snack|snacks|tea|coffee|momo|momos|restaurant|meal|khana|khaja|chiya|"
            "pizza|burger|biryani|chai|juice|cafe|canteen|dal bhat|chicken|eat|ate",
    "groceries": "groceries|grocery|vegetables|veggies|fruits|milk|rice|sabji|tarkari|market|kirana|eggs|bread",
    "transport": "transport|bus|taxi|bike|petrol|fuel|diesel|uber|pathao|indrive|ride|ticket|fare|parking|tempo|micro",
    "bills": "bill|bills|electricity|light bill|water bill|internet|wifi|recharge|data pack|phone bill|mobile|ntc|ncell|"
             "subscription|netflix|spotify|youtube premium",
    "rent": "rent|room rent|house rent|kotha|bhada",
    "clothes": "clothes|cloth|clothing|shirt|shirts|t-shirt|tshirt|shoes|shoe|pant|pants|jeans|jacket|dress|kurta|"
               "sari|saree|hoodie|sweater|socks|lugaa|kapada|kapda",
    "shopping": "shopping|amazon|daraz|bag|watch|gift|cosmetics|perfume",
    "health": "health|medicine|medicines|doctor|hospital|pharmacy|clinic|gym|checkup|dawai|aushadhi",
    "education": "education|study|studies|studying|book|books|course|courses|fees|fee|tuition|college|school|university|"
                 "exam|exams|stationery|pen|notebook|udemy|class|classes|coaching|padhai",
    "fun": "movie|movies|cinema|game|games|party|trip|travel|outing|concert|fun",
    "tech": "laptop|charger|mouse|keyboard|headphone|earphone|phone case|software|domain|hosting|server|cloud|ssd",
}
_INCOME = re.compile(r"\b(?:got|received|earned|income|salary|paid\s+me|credited|freelance|bonus|won|refund|"
                     r"pocket\s+money|kamaye|paye|paisa\s+aayo)\b", re.I)
_AMT = re.compile(r"(?:rs\.?|npr|inr|रु\.?|\$|₹)?\s*(\d[\d,]*(?:\.\d{1,2})?)\s*(k\b|thousand|hajar|हजार|lakh|लाख)?"
                  r"\s*(?:rs\.?|rupees?|rupaiya|रुपैयाँ|रुपये|npr|dollars?)?", re.I)


def _path() -> Path:
    return Path(config.EXPENSES_FILE).expanduser()


def _book() -> tuple[list[dict], list[dict], list[dict]]:
    p = _path()
    return (sheets.load(p, MONEY_HEAD, "Money"), sheets.load(p, BUDGET_HEAD, "Budgets"),
            sheets.load(p, BILL_HEAD, "Bills"))


def _save(money: list[dict], budgets: list[dict], bills: list[dict]) -> None:
    sheets.save_book(_path(), [("Money", MONEY_HEAD, money, (12, 10, 10, 14, 40)),
                               ("Budgets", BUDGET_HEAD, budgets, (16, 12)),
                               ("Bills", BILL_HEAD, bills, (18, 10, 14, 6, 12))])
    store.kv_set("money_changed", str(time.time()))


def money(n: float) -> str:
    cur = config.CURRENCY
    return f"{cur} {n:,.0f}" if abs(n - round(n)) < 0.005 else f"{cur} {n:,.2f}"


def _amount(text: str) -> float | None:
    for m in _AMT.finditer(text):
        raw = m.group(1).replace(",", "")
        if not raw or (re.fullmatch(r"(?:19|20)\d\d", raw) and not m.group(2)):
            continue  # a year, not money
        v = float(raw)
        mult = (m.group(2) or "").lower()
        v *= 1000 if mult in ("k", "thousand", "hajar", "हजार") else 100000 if mult in ("lakh", "लाख") else 1
        if v > 0:
            return v
    return None


def resolve_category(word: str) -> str:
    """'study' -> education, 'cloth' -> clothes, 'eating' -> food; '' when unknown."""
    w = (word or "").strip().lower()
    if w in CATS or w in ("income", "other", "total"):
        return w
    c = category_of(w)
    return "" if c == "other" else c


def category_of(text: str) -> str:
    low = text.lower()
    for cat, words in CATS.items():
        if re.search(rf"\b(?:{words})\b", low):
            return cat
    return "other"


def _day(text: str, today: date) -> date:
    low = text.lower()
    if re.search(r"\b(?:yesterday|hijo|हिजो|kal)\b", low):
        return today - timedelta(days=1)
    if m := re.search(r"\b(\d+)\s+days?\s+ago\b", low):
        return today - timedelta(days=int(m.group(1)))
    return today


def _note(text: str) -> str:
    t = re.sub(r"\b(?:i\s+)?(?:spent|spend|paid|pay|bought|buy|got|received|earned|kharcha|kharch|on|for|of|in|"
               r"rs\.?|rupees?|npr|today|yesterday|hijo|aaja|bhayo|gare|garyo|the|a|an|my|me|was|it|just|ko|ma|le)\b", " ",
               text, flags=re.I)
    t = _AMT.sub(" ", t)
    return " ".join(t.split()).strip(" ,.-")[:60]


def add(text: str, now: datetime | None = None) -> str:
    """'spent 500 on momo', 'got 20000 salary', 'paid 1500 internet bill yesterday'."""
    now = now or datetime.now()
    amt = _amount(text)
    if amt is None:
        return "How much was it? Say for example 'spent 500 on food'."
    kind = "income" if _INCOME.search(text) else "expense"
    cat = "income" if kind == "income" else category_of(text)
    day = _day(text, now.date())
    note = _note(text) or cat
    m, b, bills = _book()
    m.append({"date": day.isoformat(), "type": kind, "amount": f"{amt:g}", "category": cat, "note": note})
    _save(m, b, bills)
    if kind == "income":
        return f"Added income {money(amt)} ({note})."
    out = f"Added {money(amt)} for {cat}" + (f" ({note})" if note and note != cat else "") + \
          (" yesterday" if day < now.date() else "") + f". This month: {money(_sum(m, 'month', now.date()))}."
    return out + budget_warning(m, b, cat, now.date())


def _rows(m: list[dict], kind: str = "expense") -> list[tuple[date, float, str, str]]:
    out = []
    for r in m:
        if (r.get("type") or "expense").lower() != kind:
            continue
        try:
            out.append((date.fromisoformat(r["date"][:10]), float(str(r["amount"]).replace(",", "")),
                        r.get("category") or "other", r.get("note") or ""))
        except ValueError:
            continue
    return out


def span(period: str, today: date) -> tuple[date, date]:
    """[start, end] for today / yesterday / week / month / last month / year."""
    if period == "today":
        return today, today
    if period == "yesterday":
        y = today - timedelta(days=1)
        return y, y
    if period == "week":
        return today - timedelta(days=today.weekday()), today
    if period == "last_month":
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    if period == "year":
        return today.replace(month=1, day=1), today
    return today.replace(day=1), today


def _sum(m: list[dict], period: str, today: date, cat: str = "", kind: str = "expense") -> float:
    a, b = span(period, today)
    return sum(v for d, v, c, _ in _rows(m, kind) if a <= d <= b and (not cat or c == cat))


def _budget(b: list[dict], cat: str) -> float | None:
    for r in b:
        if (r.get("category") or "").lower() == cat:
            try:
                return float(str(r.get("monthly")).replace(",", ""))
            except ValueError:
                return None
    return None


def budget_warning(m: list[dict], b: list[dict], cat: str, today: date) -> str:
    out = []
    for c in (cat, "total"):
        lim = _budget(b, c)
        if not lim:
            continue
        spent = _sum(m, "month", today, "" if c == "total" else c)
        if spent >= lim:
            out.append(f" ⚠️ Over the {c} budget: {money(spent)} of {money(lim)}.")
        elif spent >= 0.8 * lim:
            out.append(f" Careful: {spent / lim:.0%} of the {c} budget used ({money(lim - spent)} left).")
    return "".join(out)


PERIOD_WORDS = {"today": "today", "yesterday": "yesterday", "week": "this week", "month": "this month",
                "last_month": "last month", "year": "this year"}


def report(period: str = "month", cat: str = "", now: datetime | None = None) -> str:
    today = (now or datetime.now()).date()
    m, b, _ = _book()
    a, z = span(period, today)
    rows = [(d, v, c, n) for d, v, c, n in _rows(m) if a <= d <= z and (not cat or c == cat)]
    total = sum(v for _, v, _, _ in rows)
    word = PERIOD_WORDS.get(period, period)
    if not rows:
        return f"No spending{' on ' + cat if cat else ''} {word}."
    if cat:
        top = sorted(rows, key=lambda r: -r[1])[:3]
        return (f"You spent {money(total)} on {cat} {word} ({len(rows)} times). Biggest: "
                + ", ".join(f"{money(v)} {n}" for _, v, _, n in top) + "." + _cat_budget_line(m, b, cat, today, period))
    by = defaultdict(float)
    for _, v, c, _ in rows:
        by[c] += v
    parts = ", ".join(f"{c} {money(v)} ({v / total:.0%})" for c, v in sorted(by.items(), key=lambda x: -x[1])[:5])
    inc = _sum(m, period, today, kind="income")
    line = f"You spent {money(total)} {word}: {parts}."
    if inc:
        line += f" Income {money(inc)}, saved {money(inc - total)}."
    days = (z - a).days + 1
    if period in ("week", "month", "year") and days > 1:
        line += f" About {money(round(total / days))} a day."
    if period == "month" and (lim := _budget(b, "total")):
        line += f" Budget: {total / lim:.0%} used, {money(max(0, lim - total))} left."
    return line


def breakdown(period: str = "month", now: datetime | None = None) -> str:
    """Every category with its share and budget, then the totals (the whole picture of the month/week/year)."""
    today = (now or datetime.now()).date()
    m, b, _ = _book()
    a, z = span(period, today)
    by = defaultdict(float)
    for d, v, c, _n in _rows(m):
        if a <= d <= z:
            by[c] += v
    word = PERIOD_WORDS.get(period, period)
    if not by:
        return f"No spending {word}."
    total = sum(by.values())
    lines = [f"Spending {word}, by category:"]
    for c in sorted(by, key=lambda c: -by[c]):
        lim = _budget(b, c) if period == "month" else None
        lines.append(f"• {c}: {money(by[c])} ({by[c] / total:.0%})"
                     + (f" — budget {money(lim)}, {by[c] / lim:.0%} used" + (" ⚠️" if by[c] > lim else "") if lim else ""))
    if period == "month":  # budgets with nothing spent yet
        for r in b:
            c = (r.get("category") or "").lower()
            if c and c != "total" and c not in by and (lim := _budget(b, c)):
                lines.append(f"• {c}: {money(0)} — budget {money(lim)}, 0% used")
    lines.append(f"Total: {money(total)}")
    inc = _sum(m, period, today, kind="income")
    if inc:
        lines.append(f"Income: {money(inc)} · saved {money(inc - total)}")
    if period == "month" and (lim := _budget(b, "total")):
        lines.append(f"Monthly budget: {money(lim)} · {total / lim:.0%} used · {money(max(0, lim - total))} left")
    return "\n".join(lines)


def _cat_budget_line(m, b, cat, today, period) -> str:
    lim = _budget(b, cat)
    if not lim or period != "month":
        return ""
    spent = _sum(m, "month", today, cat)
    return f" Budget {money(lim)}: {spent / lim:.0%} used."


def recent(n: int = 10, now: datetime | None = None) -> list[dict]:
    """Newest first, each with its row number (for 'delete expense 3')."""
    m, _, _ = _book()
    rows = [dict(r, row=i + 1) for i, r in enumerate(m)]
    return list(reversed(rows))[:n]


def list_text(period: str = "today", now: datetime | None = None) -> str:
    today = (now or datetime.now()).date()
    m, _, _ = _book()
    a, z = span(period, today)
    rows = [(i + 1, r) for i, r in enumerate(m) if a.isoformat() <= r.get("date", "")[:10] <= z.isoformat()]
    if not rows:
        return f"Nothing recorded {PERIOD_WORDS.get(period, period)}."
    lines = [f"{i}. {r['date'][5:]} {'+' if r.get('type') == 'income' else ''}{money(float(r['amount'] or 0))} "
             f"{r.get('category')} · {r.get('note')}" for i, r in rows[-15:]]
    return f"{PERIOD_WORDS.get(period, period).capitalize()}:\n" + "\n".join(lines) + "\nSay 'delete expense N' to remove one."


def delete(which: str | int) -> str:
    """'last' or a row number."""
    m, b, bills = _book()
    if not m:
        return "There are no expenses to delete."
    idx = len(m) - 1 if str(which).lower() in ("last", "", "-1") else int(which) - 1
    if not 0 <= idx < len(m):
        return f"There is no expense number {which}."
    r = m.pop(idx)
    _save(m, b, bills)
    return f"Deleted {money(float(r['amount'] or 0))} {r.get('category')} ({r.get('note')}) from {r.get('date')}."


def edit_last(text: str) -> str:
    """'the last one was 450' / 'change the last expense to transport'."""
    m, b, bills = _book()
    if not m:
        return "There is nothing to change yet."
    r = m[-1]
    changed = []
    if (amt := _amount(text)) is not None:
        r["amount"] = f"{amt:g}"
        changed.append(money(amt))
    cat = next((c for c in CATS if re.search(rf"\b{c}\b", text, re.I)), "") or (
        category_of(text) if category_of(text) != "other" else "")
    if cat:
        r["category"] = cat
        changed.append(cat)
    if not changed:
        return "What should I change? Say for example 'the last one was 450' or 'it was transport'."
    _save(m, b, bills)
    return f"Changed the last one to {', '.join(changed)} ({r.get('note')})."


def set_budget(cat: str, amount: float) -> str:
    m, b, bills = _book()
    cat = (cat or "total").lower()
    b = [r for r in b if (r.get("category") or "").lower() != cat] + [{"category": cat, "monthly": f"{amount:g}"}]
    _save(m, b, bills)
    spent = _sum(m, "month", date.today(), "" if cat == "total" else cat)
    return (f"Monthly {'budget' if cat == 'total' else cat + ' budget'} set to {money(amount)}. "
            f"Used so far this month: {money(spent)} ({spent / amount:.0%}).")


def add_bill(name: str, amount: float, day: int) -> str:
    m, b, bills = _book()
    name = name.strip().lower()
    bills = [r for r in bills if r.get("name", "").lower() != name]
    bills.append({"name": name, "amount": f"{amount:g}", "category": category_of(name) if category_of(name) != "other"
                  else "bills", "day": str(day), "last paid": ""})
    _save(m, b, bills)
    return f"I'll remind you to pay {name} ({money(amount)}) on day {day} of every month. Say 'paid {name}' to log it."


def pay_bill(name: str, now: datetime | None = None) -> str | None:
    """'paid internet' when internet is a bill -> logged as an expense; None if it isn't a bill."""
    now = now or datetime.now()
    m, b, bills = _book()
    hit = next((r for r in bills if r.get("name") and r["name"].lower() in name.lower()), None)
    if hit is None:
        return None
    amt = _amount(name) or float(hit.get("amount") or 0)
    m.append({"date": now.date().isoformat(), "type": "expense", "amount": f"{amt:g}",
              "category": hit.get("category") or "bills", "note": f"{hit['name']} bill"})
    hit["last paid"] = now.date().isoformat()
    _save(m, b, bills)
    return f"Logged the {hit['name']} bill, {money(amt)}. Next one on day {hit.get('day')} of next month."


def bills_due(now: datetime | None = None) -> list[dict]:
    """Bills whose day has come this month and that weren't paid this month."""
    now = now or datetime.now()
    _, _, bills = _book()
    out = []
    for r in bills:
        try:
            day = int(r.get("day") or 0)
        except ValueError:
            continue
        paid = (r.get("last paid") or "")[:7] == now.strftime("%Y-%m")
        if day and now.day >= day and not paid:
            out.append(r)
    return out


def check_bills(now: datetime | None = None) -> int:
    """Scheduler tick: one reminder per due bill per day (09:00-21:00)."""
    from jarvis.core import notify
    now = now or datetime.now()
    if not 9 <= now.hour < 21:
        return 0
    sent = 0
    for r in bills_due(now):
        key = f"bill_reminded:{r['name']}"
        if store.kv_get(key) == now.date().isoformat():
            continue
        store.kv_set(key, now.date().isoformat())
        notify.notify("💸 Bill due", f"Pay {r['name']}: {money(float(r.get('amount') or 0))} (due on day {r.get('day')}). "
                      f"Say 'paid {r['name']}' when done.", source="money")
        sent += 1
    return sent


def dashboard(now: datetime | None = None) -> dict:
    """Numbers for the Money card."""
    today = (now or datetime.now()).date()
    m, b, _ = _book()
    rows = _rows(m)
    month = _sum(m, "month", today)
    by = defaultdict(float)
    a, _z = span("month", today)
    for d, v, c, _ in rows:
        if d >= a:
            by[c] += v
    week = [sum(v for d, v, _, _ in rows if d == today - timedelta(days=i)) for i in range(6, -1, -1)]
    lim = _budget(b, "total")
    return {"today": _sum(m, "today", today), "week": _sum(m, "week", today), "month": month,
            "year": _sum(m, "year", today), "income_month": _sum(m, "month", today, kind="income"),
            "budget": lim, "budget_used": (month / lim) if lim else None,
            "top": sorted(({"cat": c, "amount": v} for c, v in by.items()), key=lambda x: -x["amount"])[:4],
            "last7": week, "recent": recent(5), "bills_due": [r["name"] for r in bills_due()],
            "currency": config.CURRENCY}
