"""One test round over a SAMPLE of KURAMA's tools, asked the way the owner asks (typos, short, loose grammar).

    venv/bin/python scripts/tool_round.py --round 1            # make questions + run them (Groq tokens only)
    venv/bin/python scripts/tool_round.py --round 1 --report   # the summary again, no tokens

1. Pick ~25 tools: one per area first (no area skipped), the rest weighted toward tools that failed before.
2. The fast Groq model writes 3 questions per tool, copying the owner's real messages from the traces (style only).
3. Every question goes through the real agent (shortcuts, router, AI) with FAKE tools: nothing happens on the
   laptop; only which tool KURAMA chose (and with what) is recorded.
4. A short summary, grouped by kind of failure, is printed and saved in data/eval/round<N>.json.
Fix the CLASS behind a failure, then the next round's new tools show whether the fix is general.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "eval"
SKIP_GROUPS = {"core", "skills", "toolsmith", "agents"}
# tools whose own work is a big AI job (essays, code review, video scripts...): left out of the rounds, so a round
# costs only the request's routing + one or two small calls (owner 11-01: keep rounds cheap)
HEAVY = {"write_document", "review_code", "coding", "make_video", "videomaker", "text_assist", "fix_error",
         "make_tool", "organize_files", "summarize_page", "page_summary", "explain_error", "study", "lecture",
         "generate_requirements", "scaffold_project", "dependency_doctor", "env_doctor", "training", "kaggle_gpu"}
ROUND_TOKEN_CAP = 40000  # a round stops here; the rest is run next time (--failed)
PER_ROUND = 25
PER_TOOL = 3


def owner_style(n: int = 25) -> list[str]:
    """Real messages the owner typed or said (style examples; no paths, links or long pastes)."""
    db = ROOT / "data" / "traces.db"
    rows = sqlite3.connect(db).execute("SELECT text FROM traces WHERE channel != 'telegram'").fetchall()
    good = [r[0].strip() for r in rows if r[0] and 8 <= len(r[0]) <= 70 and not re.search(r"https?://|/home/|/media/|\n", r[0])]
    random.Random(7).shuffle(good)
    return list(dict.fromkeys(good))[:n]


def pick_tools(round_no: int) -> list:
    from jarvis.core import registry
    registry.REGISTRY._ensure()
    done = set()
    for f in OUT.glob("round*.json"):  # tools already tried in earlier rounds go last; failed ones come back
        d = json.loads(f.read_text())
        failed = {q["tool"] for q in d.get("rows", []) if not q["ok"]}
        done |= {q["tool"] for q in d.get("rows", [])} - failed
    by_group: dict[str, list] = defaultdict(list)
    for t in registry.REGISTRY.tools.values():
        g = registry.group_of(t)
        if g not in SKIP_GROUPS and t.description and t.name not in HEAVY:
            by_group[g].append(t)
    rnd = random.Random(1000 + round_no)
    picked = []
    groups = list(by_group)
    rnd.shuffle(groups)
    for g in groups:  # one per area, untried tools first
        tools = sorted(by_group[g], key=lambda t: (t.name in done, rnd.random()))
        picked.append(tools[0])
    rnd.shuffle(picked)
    return picked[:PER_ROUND]


def make_questions(tools: list, style: list[str]) -> list[dict]:
    from jarvis.core import llm
    out = []
    for i in range(0, len(tools), 5):
        batch = tools[i:i + 5]
        spec = "\n".join(f"- {t.name}: {t.description[:220]}" for t in batch)
        prompt = (
            "You write test requests for a voice/text assistant on a laptop, EXACTLY in this user's style. "
            "Real messages from the user (copy their style: short, lowercase often, small spelling mistakes, "
            "loose grammar, words like 'bro', '..', 'pls', sometimes Nepali/Hindi words in English letters):\n"
            + "\n".join(f'  "{s}"' for s in style)
            + f"\n\nFor each tool below write {PER_TOOL} different requests a normal user would really say to get "
            "that tool used (simple everyday wording, NOT the tool's name, vary the wording, 1-2 with a typo). "
            "Reply with JSON only: {\"tool_name\": [\"request 1\", \"request 2\", \"request 3\"], ...}\n\nTools:\n" + spec)
        reply = llm.chat([{"role": "user", "content": prompt}], tier="fast", purpose="test_questions", max_tokens=900)
        m = re.search(r"\{.*\}", str(reply), re.S)
        try:
            data = json.loads(m.group(0)) if m else {}
        except ValueError:
            data = {}
        for t in batch:
            for q in (data.get(t.name) or [])[:PER_TOOL]:
                if isinstance(q, str) and q.strip():
                    out.append({"tool": t.name, "text": q.strip()})
        time.sleep(3)
    return out


def budget_left() -> bool:
    """KURAMA's own daily budget is a soft limit (it says "trying anyway" and Groq still answers); only Groq's real
    refusals stop a round. (Round 1's 'something went wrong' answers were the AI calling an action as a tool.)"""
    return True


# --real: these READ-ONLY tools really run (real data, real results); everything that changes the laptop, the screen,
# files or sends something stays fake (recorded, never done): Wi-Fi off, Telegram sends, closing apps...
READ_ONLY = {"get_time", "weather", "live_search", "web_search", "wikipedia", "git_info", "list_folder", "find_files",
             "recall", "recall_session", "ask_knowledge", "search_knowledge", "daily_digest", "token_usage",
             "battery_status", "laptop_doctor", "status_now", "watchdog_status", "calculate", "page_summary",
             "read_webpage", "make_chart", "list_windows", "resource_status", "where_was_i", "time_machine",
             "find_capability", "about_me", "list_skills", "dictionary", "overview", "training", "code_nav",
             "convert_units", "nepali_date", "ports"}


def run(questions: list[dict], pace_s: float = 3.0, real_tools: bool = False) -> list[dict]:
    from types import SimpleNamespace

    from tests.eval import harness
    if not real_tools:
        harness._isolated_store()
    from jarvis.core import agent, fastpath, jobs, registry, safety, semantic, store
    from jarvis.core.registry import ToolResult
    from jarvis.tools.core._hub import underlying
    registry.REGISTRY._ensure()
    semantic.ensure_ready()
    calls: list[tuple[str, dict]] = []

    real_exec = safety.execute

    def fake_execute(name, args=None, confirm=None, reg=None, ctx=None):
        a = args if isinstance(args, dict) else {}
        calls.append((name, a))
        tool, targs = underlying(name, a)
        if real_tools and registry.REGISTRY.resolve(tool, targs)[0] in READ_ONLY:
            return real_exec(tool, targs, confirm=lambda p: False, reg=reg, ctx=ctx)  # really runs; never says yes
        return ToolResult(True, "done")

    def fake_job(text, lang="en"):
        calls.append(("write_document", {"text": text}))
        return SimpleNamespace(id=0, title=text[:40], kind="write")

    def fake_internal(intent):
        calls.append((intent.tool, dict(intent.args)))
        return True, "done"
    real = safety.execute, jobs.start_task, fastpath._internal
    safety.execute, jobs.start_task, fastpath._internal = fake_execute, fake_job, fake_internal
    rows = []
    try:
        for q in questions:
            if sum(r["tokens"] for r in rows) > ROUND_TOKEN_CAP:
                print(f"  stopped at the round's cap ({ROUND_TOKEN_CAP} tokens); the rest runs next time (--failed)")
                break
            if not budget_left():
                print("  stopped: today's Groq budget is used up; run the same round again tomorrow (questions are kept)")
                break
            calls.clear()
            t0, ts0 = time.monotonic(), time.time()
            bot = agent.Agent(confirm=lambda p: True, persist=False, summarize_async=False)
            try:
                answer = bot.run(q["text"], mode="text")
            except Exception as e:  # noqa: BLE001 - a crash is a failure, keep going
                answer = f"ERROR {type(e).__name__}: {e}"
            ran = [underlying(n, a) for n, a in calls if n not in ("request_tools", "_say")]
            names = [registry.REGISTRY.resolve(n, a)[0] for n, a in ran]  # a retired name ('mic_mute') = its tool
            want = q["tool"]
            want_group = registry.group_of(registry.REGISTRY.get(want))
            groups = {registry.group_of(registry.REGISTRY.get(n)) for n in names if registry.REGISTRY.get(n)}
            used = sum(int(r["total_tokens"] or 0) for r in store._exec(
                "SELECT total_tokens FROM llm_calls WHERE ts>=? AND purpose NOT IN ('stt','test_questions')", (ts0 - 0.5,)))
            last = bot.last or {}
            row = {**q, "got": names, "args": [a for _, a in ran][:2], "ok": want in names,
                   "area_ok": want_group in groups, "path": "fastpath" if last.get("fastpath") else "ai",
                   "tokens": used, "ms": int((time.monotonic() - t0) * 1000), "answer": str(answer)[:160]}
            if row["path"] == "ai" and re.match(r"(?:ERROR|Sorry, something went wrong|Sorry, my AI service is busy)",
                                                row["answer"]):
                row["infra"] = True  # Groq refused (limit / outage): not a KURAMA mistake, retried next run
            rows.append(row)
            print(f"  {'✓' if row['ok'] else ('~' if row['area_ok'] else '✗')} {want:<20} {row['path']:<8} "
                  f"got {','.join(names[:2]) or '-':<26} {used:>5} tok  {q['text'][:55]}", flush=True)
            if row["path"] == "ai":  # Groq free tier ~8k tokens a minute: wait in proportion to what was used
                time.sleep(max(pace_s, used / 8000 * 60))
    finally:
        safety.execute, jobs.start_task, fastpath._internal = real
    return rows


def report(rows: list[dict]) -> str:
    infra = [r for r in rows if r.get("infra")]
    rows = [r for r in rows if not r.get("infra")]
    n = len(rows)
    ok = sum(r["ok"] for r in rows)
    lines = [f"{ok}/{n} right tool ({ok * 100 // max(1, n)}%), {sum(r['area_ok'] for r in rows)} right area, "
             f"{sum(r['path'] == 'fastpath' for r in rows)} instant, {sum(r['tokens'] for r in rows)} Groq tokens"
             + (f"; {len(infra)} not judged (Groq limit / errors)" if infra else "")]
    kinds = {"no tool (AI answered in words)": [r for r in rows if not r["ok"] and not r["got"]],
             "wrong area": [r for r in rows if not r["ok"] and r["got"] and not r["area_ok"]],
             "right area, wrong tool": [r for r in rows if not r["ok"] and r["area_ok"]]}
    for k, rs in kinds.items():
        if rs:
            lines.append(f"\n{k}: {len(rs)}")
            lines += [f"  [{r['tool']}] {r['text'][:70]!r} -> {','.join(r['got'][:2]) or r['answer'][:70]!r}" for r in rs]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--failed", action="store_true", help="run again only what failed / wasn't judged")
    ap.add_argument("--real", action="store_true", help="read-only tools really run (real data); others stay fake")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"round{a.round}.json"
    if a.report:
        print(report(json.loads(path.read_text())["rows"]))
        return 0
    qfile = OUT / f"round{a.round}_questions.json"
    if qfile.exists():
        questions = json.loads(qfile.read_text())
        if a.failed and path.exists():  # only what failed or couldn't be judged last time; the rest is kept
            old = json.loads(path.read_text())["rows"]
            keep = [r for r in old if r["ok"] and not r.get("infra")]
            done = {r["text"] for r in keep}
            questions = [q for q in questions if q["text"] not in done]
    else:
        tools = pick_tools(a.round)
        questions = make_questions(tools, owner_style())
        qfile.write_text(json.dumps(questions, ensure_ascii=False, indent=1))
    print(f"round {a.round}: {len(questions)} questions for {len({q['tool'] for q in questions})} tools")
    rows = run(questions, real_tools=a.real)
    if a.failed and path.exists():
        rows = keep + rows
    path.write_text(json.dumps({"round": a.round, "when": time.strftime("%F %T"), "rows": rows}, ensure_ascii=False, indent=1))
    print("\n" + report(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
