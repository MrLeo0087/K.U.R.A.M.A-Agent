"""Charts from data (0 tokens to draw): my money, a CSV/Excel/JSON file, or a link (a government data page, a
.csv/.xlsx download, an HTML table). Drawn with Pillow as PNGs in data/outputs/charts/ (they show in the workspace
and can go to Telegram). Several views at once: bar + pie for categories, line + bar for years/dates.

Columns are picked by the words of the request (0 tokens); only a wide table that the words don't explain gets one
small LLM call that names the columns.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import math
import re
from datetime import datetime
from pathlib import Path

from jarvis.core import config

log = logging.getLogger(__name__)
W, H = 1200, 700
BG, FG, MUTED, GRID = (17, 19, 24), (232, 228, 222), (139, 134, 128), (40, 43, 50)
COLORS = [(255, 138, 61), (95, 211, 141), (91, 160, 255), (255, 200, 87), (199, 125, 255), (255, 99, 132),
          (64, 210, 210), (180, 180, 180)]
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


# ------------------------------------------------------------------ data in
def _num(v) -> float | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = re.sub(r"[,\s%₹$]|rs\.?|npr", "", str(v or ""), flags=re.I)
    s = s.replace("−", "-")
    try:
        return float(s)
    except ValueError:
        return None


def _table_from_rows(rows: list[list]) -> tuple[list[str], list[list]]:
    rows = [r for r in rows if any(str(c or "").strip() for c in r)]
    if not rows:
        return [], []
    head = [str(c or f"col{i + 1}").strip() for i, c in enumerate(rows[0])]
    width = len(head)
    return head, [list(r[:width]) + [""] * (width - len(r)) for r in rows[1:]]


def parse_bytes(data: bytes, name: str = "", ctype: str = "") -> tuple[list[str], list[list]]:
    """(header, rows) from CSV / TSV / XLSX / JSON / HTML (the biggest numeric table)."""
    low = (name or "").lower()
    if low.endswith((".xlsx", ".xlsm")) or "spreadsheetml" in ctype or data[:2] == b"PK":
        from openpyxl import load_workbook
        ws = load_workbook(io.BytesIO(data), read_only=True, data_only=True).active
        return _table_from_rows([list(r) for r in ws.iter_rows(values_only=True)][:5000])
    text = data.decode("utf-8-sig", "replace")
    if low.endswith(".json") or "json" in ctype or text.lstrip()[:1] in "[{":
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):  # {'data': [...]} / {'records': [...]}
                obj = next((v for v in obj.values() if isinstance(v, list) and v and isinstance(v[0], dict)), [obj])
            if isinstance(obj, list) and obj and isinstance(obj[0], dict):
                head = list(obj[0].keys())
                return head, [[r.get(k, "") for k in head] for r in obj[:5000]]
        except ValueError:
            pass
    if "<table" in text[:2_000_000].lower():
        return _html_table(text)
    try:
        dialect = csv.Sniffer().sniff(text[:4000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return _table_from_rows(list(csv.reader(io.StringIO(text), dialect))[:5000])


def _html_table(html: str) -> tuple[list[str], list[list]]:
    import lxml.html
    doc = lxml.html.fromstring(html)
    best, score = ([], []), -1
    for t in doc.iter("table"):
        rows = [[" ".join(c.text_content().split()) for c in tr.xpath("./th|./td")] for tr in t.iter("tr")]
        head, body = _table_from_rows(rows)
        nums = sum(1 for r in body for c in r if _num(c) is not None)
        if body and nums > score:
            best, score = (head, body), nums
    return best


def load(source: str) -> tuple[list[str], list[list], str]:
    """(header, rows, a short name) from a path or a URL."""
    src = source.strip().strip("'\"")
    if re.match(r"https?://", src):
        import httpx
        r = httpx.get(src, timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 KURAMA"})
        r.raise_for_status()
        name = re.sub(r"[?#].*$", "", src.rstrip("/").rsplit("/", 1)[-1]) or "data"
        head, rows = parse_bytes(r.content, name, r.headers.get("content-type", ""))
        return head, rows, name
    p = Path(src).expanduser()
    if not p.is_file():
        from jarvis.core.paths import smart_path
        p = smart_path(src, want="file") or p
    head, rows = parse_bytes(p.read_bytes(), p.name)
    return head, rows, p.stem


# ------------------------------------------------------------------ which columns
_TIME = re.compile(r"^(?:1[89]\d\d|20\d\d)(?:[-/]\d{1,2}(?:[-/]\d{1,2})?)?$|^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|"
                   r"dec)\w*\.?(?:\s+\d{2,4})?$|^\d{4}/\d{2}$|^(?:fy\s*)?\d{4}[-/]\d{2,4}$", re.I)


def pick(head: list[str], rows: list[list], request: str = "") -> tuple[int, list[int]]:
    """(label column, value columns) by the words of the request, else the first text + numeric columns."""
    n = len(head)
    numeric = [i for i in range(n) if sum(_num(r[i]) is not None for r in rows) >= max(1, 0.6 * len(rows))]
    words = set(re.findall(r"[a-z]{3,}", request.lower()))
    def hits(i):
        return len(words & set(re.findall(r"[a-z]{3,}", head[i].lower())))
    labels = [i for i in range(n) if i not in numeric or all(_TIME.match(str(r[i]).strip()) for r in rows[:20] if r[i])]
    if not labels:
        labels = [0]
    x = max(labels, key=lambda i: (hits(i), -i))
    ys = [i for i in numeric if i != x]
    asked = [i for i in ys if hits(i)]
    ys = asked or [i for i in ys if not re.search(r"\b(?:s\.?n|sn|id|code|no|rank|year)\b", head[i].lower())] or ys
    return x, ys[:4]


def pick_llm(head: list[str], rows: list[list], request: str) -> tuple[int, list[int]] | None:
    """One small call for wide tables the words don't explain: which label column and which numbers."""
    from jarvis.core import llm
    sample = "\n".join(" | ".join(str(c)[:20] for c in r) for r in rows[:5])
    try:
        reply = llm.chat([{"role": "system", "content": "Pick chart columns. Reply ONLY JSON: {\"x\": <label column index>, "
                                                           "\"y\": [<1-3 numeric column indexes>]}"},
                          {"role": "user", "content": f"Request: {request}\nColumns: " + ", ".join(f"{i}={h}" for i, h in enumerate(head))
                           + f"\nRows:\n{sample}"}], tier="fast", purpose="chart_columns", max_tokens=80)
        d = json.loads(re.search(r"\{.*\}", reply.text or "", re.S).group(0))
        return int(d["x"]), [int(i) for i in d["y"]][:3]
    except Exception as e:
        log.info("chart column pick failed: %s", e)
        return None


# ------------------------------------------------------------------ drawing (Pillow)
def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(BOLD if bold else FONT, size)
    except OSError:
        return ImageFont.load_default()


def _short(v: float) -> str:
    a = abs(v)
    def trim(x: str) -> str:
        return x.replace(".0M", "M").replace(".0k", "k").replace(".0B", "B")
    return trim(f"{v / 1e9:.1f}B") if a >= 1e9 else trim(f"{v / 1e6:.1f}M") if a >= 1e6 else trim(f"{v / 1e3:.1f}k") \
        if a >= 1e4 else f"{v:,.0f}" if a >= 100 or v == int(v) else f"{v:.1f}"


def _nice(low: float, top: float) -> tuple[float, float, float]:
    """Round axis ends + a 1/2/5 step: 0..2,041,587 -> 0..2.5M step 0.5M."""
    span = (top - low) or abs(top) or 1
    raw = span / 5
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    return math.floor(low / step) * step, math.ceil(top / step) * step, step


def _grid(d, low: float, top: float, x0: int, x1: int, y0: int, y1: int) -> tuple[float, float]:
    lo, hi, step = _nice(low, top)
    f = _font(14)
    v = lo
    while v <= hi + step / 2:
        y = y1 - (v - lo) / ((hi - lo) or 1) * (y1 - y0)
        d.line((x0, y, x1, y), fill=GRID)
        d.text((x0 - 10, y), _short(round(v, 10)), fill=MUTED, font=f, anchor="rm")
        v += step
    return lo, hi


def _canvas(title: str, subtitle: str = ""):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((40, 26), title[:80], fill=FG, font=_font(30, True))
    if subtitle:
        d.text((40, 66), subtitle[:120], fill=MUTED, font=_font(17))
    return img, d


def bar(labels: list[str], series: list[tuple[str, list[float]]], title: str, subtitle: str = ""):
    img, d = _canvas(title, subtitle)
    n, k = len(labels), len(series)
    vals = [v for _, s in series for v in s]
    x0, x1, y0, y1 = 110, W - 40, 110, H - 110
    low, top = _grid(d, min(vals + [0]), max(vals + [0]), x0, x1, y0, y1)
    span = (top - low) or 1
    yz = y1 - (0 - low) / span * (y1 - y0)
    f = _font(14)
    slot = (x1 - x0) / max(1, n)
    bw = max(2, slot * 0.75 / k)
    for j, (_, s) in enumerate(series):
        for i, v in enumerate(s):
            bx = x0 + i * slot + slot * 0.125 + j * bw
            by = y1 - (v - low) / span * (y1 - y0)
            d.rectangle((bx, min(by, yz), bx + bw - 1, max(by, yz)), fill=COLORS[j % len(COLORS)])
            if n <= 16 and k == 1:
                d.text((bx + bw / 2, min(by, yz) - 6), _short(v), fill=FG, font=f, anchor="md")
    step = max(1, math.ceil(n / 16))
    for i, lab in enumerate(labels):
        if i % step == 0:
            d.text((x0 + i * slot + slot / 2, y1 + 10), str(lab)[:12], fill=MUTED, font=f, anchor="ma")
    _legend(d, series)
    return img


def line(labels: list[str], series: list[tuple[str, list[float]]], title: str, subtitle: str = ""):
    img, d = _canvas(title, subtitle)
    n = len(labels)
    vals = [v for _, s in series for v in s]
    x0, x1, y0, y1 = 110, W - 50, 110, H - 110
    low, top = _grid(d, min(vals + [0]), max(vals), x0, x1, y0, y1)
    span = (top - low) or 1
    f = _font(14)
    def px(i):
        return x0 + (x1 - x0) * (i / max(1, n - 1))
    for j, (_, s) in enumerate(series):
        pts = [(px(i), y1 - (v - low) / span * (y1 - y0)) for i, v in enumerate(s)]
        col = COLORS[j % len(COLORS)]
        if len(pts) > 1:
            d.line(pts, fill=col, width=4, joint="curve")
        for x, y in pts if n <= 40 else pts[-1:]:
            d.ellipse((x - 4, y - 4, x + 4, y + 4), fill=col)
        if pts:
            d.text((pts[-1][0], pts[-1][1] - 10), _short(s[-1]), fill=FG, font=f, anchor="rd")
    step = max(1, math.ceil(n / 14))
    for i, lab in enumerate(labels):
        if i % step == 0 or i == n - 1:
            d.text((px(i), y1 + 10), str(lab)[:10], fill=MUTED, font=f, anchor="ma")
    _legend(d, series)
    return img


def pie(labels: list[str], values: list[float], title: str, subtitle: str = ""):
    img, d = _canvas(title, subtitle)
    pairs = sorted(((lab, v) for lab, v in zip(labels, values) if v > 0), key=lambda p: -p[1])
    if len(pairs) > 7:
        pairs = pairs[:6] + [("others", sum(v for _, v in pairs[6:]))]
    total = sum(v for _, v in pairs) or 1
    cx, cy, r = 360, 400, 230
    a = -90.0
    for i, (_, v) in enumerate(pairs):
        sweep = v / total * 360
        d.pieslice((cx - r, cy - r, cx + r, cy + r), a, a + sweep, fill=COLORS[i % len(COLORS)])
        a += sweep
    d.ellipse((cx - r * 0.55, cy - r * 0.55, cx + r * 0.55, cy + r * 0.55), fill=BG)  # donut
    d.text((cx, cy), _short(total), fill=FG, font=_font(30, True), anchor="mm")
    f = _font(20)
    for i, (lab, v) in enumerate(pairs):
        y = 170 + i * 52
        d.rectangle((700, y, 724, y + 24), fill=COLORS[i % len(COLORS)])
        d.text((740, y + 12), f"{str(lab)[:22]}  {v / total:.0%}", fill=FG, font=f, anchor="lm")
        d.text((1150, y + 12), _short(v), fill=MUTED, font=f, anchor="rm")
    return img


def _legend(d, series):
    if len(series) < 2:
        return
    f = _font(15)
    x = 40
    for j, (name, _) in enumerate(series):
        d.rectangle((x, H - 40, x + 16, H - 24), fill=COLORS[j % len(COLORS)])
        d.text((x + 24, H - 32), name[:24], fill=FG, font=f, anchor="lm")
        x += 40 + 9 * min(24, len(name))


# ------------------------------------------------------------------ the job
def _save(img, name: str) -> Path:
    out = config.OUTPUTS_DIR / "charts"
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"{datetime.now():%Y%m%d-%H%M%S}-{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:40] or 'chart'}.png"
    img.save(p, optimize=True)
    return p


def draw(labels: list[str], series: list[tuple[str, list[float]]], title: str, kind: str = "auto",
         subtitle: str = "") -> list[Path]:
    """Save 1-3 views; kind auto = line + bar for time, bar + pie for categories."""
    is_time = sum(bool(_TIME.match(str(x).strip())) for x in labels) >= 0.7 * max(1, len(labels))
    if not is_time and len(labels) > 20:  # categories: the biggest 15 (sorted), the rest dropped from the bar
        order = sorted(range(len(labels)), key=lambda i: -series[0][1][i])[:15]
        labels = [labels[i] for i in order]
        series = [(n, [s[i] for i in order]) for n, s in series]
    views = {"auto": (["line", "bar"] if is_time else ["bar", "pie"]), "all": ["bar", "line", "pie"]}.get(kind, [kind])
    out = []
    for v in views:
        if v == "pie" and (len(series) > 1 or any(x < 0 for x in series[0][1])):
            continue
        img = (pie(labels, series[0][1], title, subtitle) if v == "pie" else
               line(labels, series, title, subtitle) if v == "line" else bar(labels, series, title, subtitle))
        out.append(_save(img, f"{title}-{v}"))
    return out


def from_table(head: list[str], rows: list[list], request: str, name: str, kind: str = "auto") -> tuple[list[Path], str]:
    if not head or not rows:
        return [], "I couldn't find a table with numbers there."
    x, ys = pick(head, rows, request)
    if (not ys or (len(head) > 8 and not set(re.findall(r"[a-z]{4,}", request.lower())) &
                   set(re.findall(r"[a-z]{4,}", " ".join(head).lower())))) and request.strip():
        if got := pick_llm(head, rows, request):
            x, ys = got
    if not ys:
        return [], f"I found a table ({', '.join(head[:6])}) but no number column to draw."
    good = [r for r in rows if all(_num(r[y]) is not None for y in ys)][:400]
    labels = [str(r[x]).strip() for r in good]
    series = [(head[y], [_num(r[y]) for r in good]) for y in ys]
    title = (f"{', '.join(head[y] for y in ys)} by {head[x]}")[:70]
    paths = draw(labels, series, title, kind, f"Source: {name} · {len(good)} rows")
    return paths, f"{title} ({len(good)} rows)"


def chart_money(period: str = "month", now: datetime | None = None) -> tuple[list[Path], str]:
    """My spending: by category (bar + pie) and per day (line)."""
    from collections import defaultdict
    from datetime import timedelta

    from jarvis.core import expenses as ex
    today = (now or datetime.now()).date()
    m, _, _ = ex._book()
    a, z = ex.span(period, today)
    rows = [(d, v, c) for d, v, c, _ in ex._rows(m) if a <= d <= z]
    if not rows:
        return [], f"No spending recorded {ex.period_words(period)} to draw."
    by = defaultdict(float)
    for _, v, c in rows:
        by[c] += v
    cats = sorted(by, key=lambda c: -by[c])
    word = ex.period_words(period)
    sub = f"Total {ex.money(sum(by.values()))} · {word}"
    paths = draw(cats, [("spent", [by[c] for c in cats])], f"Spending by category, {word}", "auto", sub)
    days = (z - a).days + 1
    if days > 1:
        per = defaultdict(float)
        for d, v, _ in rows:
            per[d] += v
        labels = [(a + timedelta(days=i)) for i in range(days)]
        paths += draw([d.strftime("%b %d") for d in labels], [("spent", [per[d] for d in labels])],
                      f"Spending per day, {word}", "line", sub)
    return paths, f"your spending {word}"
