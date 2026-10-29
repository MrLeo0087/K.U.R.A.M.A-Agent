"""KURAMA monitoring report from data/traces.db (see MONITORING.md).

    venv/bin/python scripts/trace_report.py              # last 7 days
    venv/bin/python scripts/trace_report.py --days 30
    venv/bin/python scripts/trace_report.py --show <id>  # one request in full
    venv/bin/python scripts/trace_report.py --csv out.csv  # every row, for a spreadsheet

Sections: totals by path / channel, speed, tokens, errors, likely mistakes (the next message corrects it), AI answers
with no tool for a command, retries and refusals, failed tools, the slowest and most expensive requests, and the
AI requests asked most often (the best candidates for new 0-token shortcuts).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CORRECTION = re.compile(r"^\W*(?:no+|nope|not (?:that|this|what)|wrong|that'?s (?:not|wrong)|i (?:said|mean|meant|asked)|"
                        r"you (?:didn'?t|did not|don'?t)|it (?:didn'?t|did not|doesn'?t)|again|why (?:did|didn'?t|not)|"
                        r"hoina|haina|galat|nahi|nai)\b", re.I)
COMMANDISH = re.compile(r"^\W*(?:open|close|play|set|turn|start|stop|send|find|show|make|create|add|remind|delete|remove|"
                        r"move|copy|run|search|download|install|kill|lock|mute|increase|decrease|change|switch|take|"
                        r"save|cancel|schedule)\b", re.I)


def fixed_at(db: Path) -> float:
    """When the problems found so far were fixed (--mark-fixed): older traces are left out unless --all."""
    try:
        return float((db.parent / "traces_fixed_at").read_text().strip())
    except (OSError, ValueError):
        return 0.0


def load(db: Path, days: float, since: float = 0.0) -> list[dict]:
    if not db.exists():
        return []
    c = sqlite3.connect(str(db))
    c.row_factory = sqlite3.Row
    start = max(time.time() - days * 86400, since)
    return [dict(r) for r in c.execute("SELECT * FROM traces WHERE ts >= ? ORDER BY ts", (start,))]


def short(t: str, n: int = 70) -> str:
    t = re.sub(r"\s+", " ", t or "").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def when(ts: float) -> str:
    return time.strftime("%m-%d %H:%M", time.localtime(ts))


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.0f}%" if b else "-"


def tools_of(r: dict) -> list[dict]:
    try:
        return [t for t in json.loads(r["tools"] or "[]") if t.get("name") != "request_tools"]
    except ValueError:
        return []


def report(rows: list[dict], days: float) -> str:
    out: list[str] = []
    add = out.append
    n = len(rows)
    add(f"KURAMA monitoring · last {days:g} days · {n} requests"
        + (f" · {when(rows[0]['ts'])} → {when(rows[-1]['ts'])}" if rows else ""))
    if not rows:
        return "\n".join(out + ["No traces yet."])
    paths = Counter(r["path"] for r in rows)
    add("Path: " + ", ".join(f"{k} {v} ({pct(v, n)})" for k, v in paths.most_common()))
    add("Channel: " + ", ".join(f"{k or 'laptop'} {v}" for k, v in Counter(r["channel"] for r in rows).most_common())
        + " · Mode: " + ", ".join(f"{k or '-'} {v}" for k, v in Counter(r["mode"] for r in rows).most_common()))
    ms = sorted(r["ms"] for r in rows)
    add(f"Time: median {statistics.median(ms):.0f} ms · p90 {ms[int(0.9 * (n - 1))]} ms · max {ms[-1]} ms")
    ai = [r for r in rows if r["tokens"]]
    tot = sum(r["tokens"] for r in rows)
    add(f"Tokens: {tot} total · {tot // max(1, days):.0f}/day · {tot // max(1, len(ai))} per AI request "
        f"({len(ai)} requests used the AI)")

    def section(title: str, items: list[str]) -> None:
        if items:
            add("")
            add(f"## {title} ({len(items)})")
            out.extend(items[:15])
            if len(items) > 15:
                add(f"  … {len(items) - 15} more")

    section("Errors", [f"  {r['id']} {when(r['ts'])} {short(r['text'])!r}: {short(r['error'], 90)}"
                       for r in rows if r["error"] and r["error"] != "stopped early"])
    fixes = []
    for a, b in zip(rows, rows[1:]):
        if b["ts"] - a["ts"] < 120 and CORRECTION.search(b["text"] or ""):
            did = ",".join(t["name"] for t in tools_of(a)) or a["path"]
            fixes.append(f"  {a['id']} {short(a['text'], 50)!r} → did {did} → then {short(b['text'], 50)!r}")
    section("Likely mistakes (the next message corrects it)", fixes)
    section("AI answered a command without any tool", [
        f"  {r['id']} {short(r['text'], 55)!r} → {short(r['answer'], 50)!r}"
        for r in rows if r["path"] == "ai" and not tools_of(r) and COMMANDISH.search(r["text"] or "")])
    section("Retried after 'I can't' / a claimed action", [f"  {r['id']} {short(r['text'])!r}" for r in rows if r["retried"]])
    section("Said no to a yes/no question", [f"  {r['id']} {short(r['text'])!r}" for r in rows if r["denied"]])
    fails = []
    for r in rows:
        for t in tools_of(r):
            if t.get("ok") is False and t.get("outcome") != "denied":
                fails.append(f"  {r['id']} {t['name']} {short(json.dumps(t.get('args'), ensure_ascii=False), 40)}: "
                             f"{short(t.get('result'), 60)!r}")
    section("Failed tool calls", fails)
    section("Slowest", [f"  {r['id']} {r['ms']} ms {r['path']} {short(r['text'], 60)!r}"
                        for r in sorted(rows, key=lambda r: -r["ms"])[:10]])
    section("Most tokens", [f"  {r['id']} {r['tokens']} tok ({r['llm_calls']} calls) {short(r['text'], 60)!r}"
                            for r in sorted(ai, key=lambda r: -r["tokens"])[:10]])
    norm = Counter(re.sub(r"[^\w\s]", "", (r["text"] or "").lower()).strip() for r in ai)
    section("Asked the AI most often (make these 0-token shortcuts)",
            [f"  {v}× {k!r}" for k, v in norm.most_common(15) if v > 1])
    used = Counter(t["name"] for r in rows for t in tools_of(r))
    add("")
    add("Tools used: " + ", ".join(f"{k} {v}" for k, v in used.most_common(25)))
    return "\n".join(out)


def show(db: Path, tid: str) -> str:
    c = sqlite3.connect(str(db))
    c.row_factory = sqlite3.Row
    r = c.execute("SELECT * FROM traces WHERE id LIKE ?", (tid + "%",)).fetchone()
    if not r:
        return f"no trace {tid}"
    lines = []
    for k in r.keys():
        v = r[k]
        if isinstance(v, str) and v[:1] in "[{":
            try:
                v = json.dumps(json.loads(v), ensure_ascii=False, indent=1)
            except ValueError:
                pass
        lines.append(f"{k}: {when(v) if k == 'ts' else v}")
    return "\n".join(lines)


def main() -> int:
    from jarvis.core import config
    ap = argparse.ArgumentParser(description="KURAMA monitoring report")
    ap.add_argument("--days", type=float, default=7)
    ap.add_argument("--show", help="one trace id (or its first letters) in full")
    ap.add_argument("--csv", help="write every row of the period to this CSV file")
    ap.add_argument("--db", default=str(config.TRACE_DB))
    ap.add_argument("--mark-fixed", action="store_true",
                    help="the problems found so far are fixed: later reports start from now (old traces are kept)")
    ap.add_argument("--all", action="store_true", help="include traces from before the last --mark-fixed")
    a = ap.parse_args()
    db = Path(a.db)
    if a.show:
        print(show(db, a.show))
        return 0
    if a.mark_fixed:
        (db.parent / "traces_fixed_at").write_text(str(time.time()))
        print(f"Marked as fixed at {time.strftime('%Y-%m-%d %H:%M')}: reports start from now (old traces kept; --all shows them).")
        return 0
    since = 0.0 if a.all else fixed_at(db)
    if since:
        print(f"(Only requests after the fixes of {time.strftime('%Y-%m-%d %H:%M', time.localtime(since))}; --all for older ones.)")
    rows = load(db, a.days, since)
    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["id"])
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {len(rows)} rows to {a.csv}")
        return 0
    print(report(rows, a.days))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
