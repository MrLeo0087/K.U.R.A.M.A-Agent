"""KURAMA test-set scorer (v2 phase 2). Three levels, each on the same cases (tests/eval/cases.jsonl):

  shortcut  the zero-token fast path: what share it handles, and whether what it handles is RIGHT (0 tokens, offline)
  route     the router: does it offer the tool group the right action lives in (0 tokens; the AI classifier is off)
  ai        the whole agent with a real Groq model but FAKE tools (nothing really happens on the laptop): the first
            action it takes is compared with the expected intent; tokens and time are measured (costs tokens: opt-in)

Tools are named by INTENT ("todo.add", "open.site", ...) so the scores stay comparable while the tools are rebuilt:
intent_of() is the one place that maps today's tools to intents. Results go to data/eval/ and the last run is shown
next to the new one.

    venv/bin/python -m tests.eval.harness                # shortcut + route (free, ~10 s)
    venv/bin/python -m tests.eval.harness --ai           # + the full agent on every case (tokens; paced for Groq)
    venv/bin/python -m tests.eval.harness --ai --limit 40
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = Path(__file__).with_name("cases.jsonl")
OUT_DIR = ROOT / "data" / "eval"

# today's tool -> intent (tools whose intent depends on an argument are handled in intent_of)
TOOL_INTENT = {
    "video_download": "media.download", "cleanup": "system.cleanup", "code_nav": "code.find",
    "code_to_file": "code.to_file",
    "get_time": "time", "get_date": "date", "weather": "weather",
    "add_reminder": "reminder.add", "set_alarm": "alarm.set", "set_timer": "timer.set", "stopwatch": "stopwatch",
    "open_app": "open.app", "open_url": "open.site", "open_folder": "open.folder", "close_app": "close.app",
    "kill_app": "kill.app", "window": "window",
    "send_message_telegram": "telegram.message", "send_file_telegram": "telegram.file",
    "find_and_send": "telegram.find_send", "send_last_result": "telegram.result",
    "list_folder": "files.list", "find_files": "files.find", "make_folder": "files.mkdir",
    "organize_files": "files.organize", "tidy_downloads": "files.organize", "delete_to_trash": "files.delete",
    "music": "media.play", "media_control": "media.control", "youtube": "media.control",
    "audio": "volume", "brightness": "brightness", "screenshot": "screenshot", "read_text": "screen.read",
    "read_webpage": "web.read", "page_summary": "web.read", "laptop_toggle": "laptop.toggle",
    "night_light": "night_light", "set_theme": "theme", "set_wallpaper": "wallpaper",
    "suspend_computer": "power.sleep", "lock_screen": "power.lock", "battery_status": "battery",
    "laptop_doctor": "system.status", "status_now": "system.status", "internet_doctor": "system.internet",
    "disk_cleaner": "system.disk", "live_search": "web.live", "web_search": "web.search", "wikipedia": "web.search",
    "generate_image": "image.generate", "write_document": "writing.job", "jobs": "writing.job",
    "make_audio": "audio.make", "make_chart": "chart.make", "text_assist": "text.selected",
    "fix_error": "code.fix", "where_was_i": "code.where", "time_machine": "code.changes", "git_info": "code.git",
    "git_change": "code.git", "clipboard": "clipboard", "dictate": "dictate", "recall": "memory.recall",
    "remember": "memory.remember", "forget": "memory.forget", "recall_session": "memory.session",
    "contacts": "contacts", "expenses": "money", "habits": "habits", "goals": "goals", "saved_links": "links",
    "find_my_phone": "phone.find", "location_history": "phone.location", "laptop_guard": "laptop.location",
    "remote_desktop": "remote", "gesture_control": "gesture", "training": "training", "daily_digest": "day.summary",
    "token_usage": "tokens", "calculate": "calculate", "about_me": "self.about", "find_capability": "self.about",
    "volume": "volume", "_say": "chat", "mute_audio": "volume", "do_not_disturb": "dnd",
}
CORE = ("apps", "laptop", "files", "telegram", "schedule", "media", "web", "info", "memory", "create", "text", "code",
        "life", "kurama", "run_command", "run_python")
SLASH = {"control": "remote", "screen": "screenshot", "todo": "todo.list", "weather": "weather", "time": "time"}
# intents that count as the same thing for scoring ("what's on today" may show the day or the to-do list)
SAME = {"day.today": {"day.today", "todo.list"}, "web.news": {"web.news", "web.live", "web.search"},
        "web.live": {"web.live", "web.search"}, "clarify": {"clarify", "chat"}, "self.about": {"self.about", "chat"},
        "media.play": {"media.play", "media.control"}, "telegram.result": {"telegram.result", "telegram.file"},
        "telegram.find_send": {"telegram.find_send", "telegram.file"}, "files.find": {"files.find", "files.list"},
        "volume": {"volume"}, "system.status": {"system.status"}, "power.sleep": {"power.sleep"},
        "timer.set": {"timer.set", "alarm.set"}}


def _real_args(tool: str | None, args: dict) -> dict:
    """A general tool's call scored by the arguments its specialised tool gets."""
    if tool not in CORE:
        return args
    from jarvis.tools.core._hub import underlying
    return underlying(tool, args)[1]


def intent_of(tool: str | None, args: dict | None = None) -> str:
    """The intent of one action (None tool = a plain answer = 'chat')."""
    a = args or {}
    if not tool:
        return "chat"
    if tool in CORE:  # v2 general tool: score what it would run
        from jarvis.tools.core._hub import underlying
        if tool in ("run_command", "run_python"):
            return f"run.{tool.split('_')[1]}"
        tool, a = underlying(tool, a)
        if tool in CORE:
            return f"tool:{tool}"
    if tool == "todo":
        act = a.get("action", "list")
        return {"today": "day.today", "delete": "todo.delete", "clear": "todo.clear"}.get(act, f"todo.{act}")
    if tool == "schedules":
        return "reminder.cancel" if a.get("action") in ("cancel", "move", "rename") else "reminder.list"
    if tool == "power_off":
        return {"restart": "power.restart", "logout": "power.logout"}.get(a.get("action"), "power.shutdown")
    if tool == "read_later":
        act = a.get("action", "list")
        return "readlater.add" if act == "add" else "readlater.list" if act in ("list", "last") else f"readlater.{act}"
    if tool == "generate_image":
        return "image.generate"
    if tool == "_cmd":  # a slash command ('/control laptop')
        return SLASH.get(str(a.get("cmd", "")), f"slash:{a.get('cmd')}")
    return TOOL_INTENT.get(tool, f"tool:{tool}")


def ok(expect: str, got: str) -> bool:
    return got in SAME.get(expect, {expect})


def args_ok(want: dict, got: dict) -> bool:
    """Every expected argument matches (loosely: case-insensitive, a want value inside the got value)."""
    for k, v in (want or {}).items():
        g = (got or {}).get(k)
        if isinstance(v, bool):
            if bool(g) != v:
                return False
        elif str(v).lower() not in str(g or "").lower():
            return False
    return True


def load() -> list[dict]:
    return [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]


def _isolated_store() -> None:
    """Score on an empty throwaway database: never the owner's real data (and no side effects)."""
    from jarvis.core import context, rewrite, store
    store.init(Path(tempfile.mkdtemp(prefix="kurama-eval-")) / "eval.db")
    # ...and never the owner's live desktop: a file open in VS Code / a highlight made the selection shortcut take
    # requests (4 false "text.selected" mistakes) and the score depended on what happened to be open
    rewrite.peek = lambda *a, **k: ""
    context.snapshot = lambda *a, **k: {"file": None, "selection": None, "browser": None}


# --- level 1: shortcut ---
def run_shortcut(cases: list[dict]) -> dict:
    from jarvis.core import config, fastpath, planner
    config.FASTPATH = True
    handled = right = 0
    wrong, rows = [], []
    for c in cases:
        if c["expect"].startswith("route."):  # a routing-only case (no shortcut is expected or judged)
            continue
        it = None if planner.is_multi(c["text"]) else fastpath.match(c["text"])  # like the agent: several tasks -> planner
        if it is None:
            rows.append({"id": c["id"], "level": "shortcut", "got": None})
            continue
        handled += 1
        got = intent_of(it.tool, it.args)
        good = False if c["expect"] == "multi" else ok(c["expect"], got) and args_ok(c["args"], it.args)
        right += good
        if not good:
            wrong.append({"id": c["id"], "text": c["text"], "expect": c["expect"], "got": got, "args": it.args})
        rows.append({"id": c["id"], "level": "shortcut", "got": got, "ok": good})
    return {"cases": len(cases), "handled": handled, "right": right, "wrong": wrong, "rows": rows}


# --- level 2: route ---
def _group_of(intent: str) -> set[str]:
    """Tool groups that hold the expected intent's tools (from the live registry)."""
    from jarvis.core import registry
    groups = set()
    for name, t in registry.REGISTRY.tools.items():
        for probe in ({}, {"action": "add"}, {"action": "list"}, {"action": "today"}, {"action": "done"},
                      {"action": "delete"}, {"action": "clear"}, {"action": "restart"}, {"action": "cancel"}):
            if ok(intent, intent_of(name, probe)):
                g = registry.group_of(t)
                from jarvis.core import config
                groups |= set(config.CORE_COVERS.get(name, ())) if g == "core" else {g}
    return groups


def run_route(cases: list[dict]) -> dict:
    from jarvis.core import config, llm, registry, router
    registry.REGISTRY._ensure()

    def no_llm(*a, **k):
        raise llm.LLMError("eval: classifier off")
    real_chat, llm.chat = llm.chat, no_llm
    try:
        right = total = 0
        misses = []
        for c in cases:
            if c["expect"] in ("chat", "clarify"):
                continue
            total += 1
            r = router.route(c["text"], log_it=False)
            if c.get("context") == "selection" and "clipboard" not in r.groups:  # like agent._route_node: something
                r = router.Route(["clipboard", *r.groups][:config.ROUTER_MAX_GROUPS], r.method)  # is highlighted
            parts = c.get("all") or [c["expect"]]
            wants = [set(c["groups"])] if c.get("groups") else [_group_of(p) for p in parts]  # "groups": the areas
            want = set().union(*wants)
            good = all(w & set(r.groups) for w in wants)
            right += good
            if not good:
                misses.append({"id": c["id"], "text": c["text"], "expect": c["expect"], "want": sorted(want),
                               "got": r.groups})
        return {"cases": total, "right": right, "misses": misses}
    finally:
        llm.chat = real_chat


# --- level 3: the whole agent, real AI, fake tools ---
def run_ai(cases: list[dict], pace_s: float = 2.5) -> dict:
    from jarvis.core import agent, registry, safety, store
    from jarvis.core.registry import ToolResult
    registry.REGISTRY._ensure()
    calls: list[tuple[str, dict]] = []

    def fake_execute(name, args=None, confirm=None, reg=None, ctx=None):
        calls.append((name, args if isinstance(args, dict) else {}))
        return ToolResult(True, "done")
    from types import SimpleNamespace

    from jarvis.core import jobs

    def fake_job(text, lang="en"):  # long jobs (essays...) never really start during a test
        calls.append(("write_document", {"text": text}))
        return SimpleNamespace(id=0, title=text[:40], kind="write")
    from jarvis.core import fastpath

    def fake_internal(intent):  # shortcut-only actions (slash commands, greetings): recorded, never run
        calls.append((intent.tool, dict(intent.args)))
        return True, "done"
    real, real_job, real_internal = safety.execute, jobs.start_task, fastpath._internal
    safety.execute, jobs.start_task, fastpath._internal = fake_execute, fake_job, fake_internal
    right, rows, tokens, ms = 0, [], [], []
    try:
        for c in cases:
            calls.clear()
            t0, ts0 = time.monotonic(), time.time()
            bot = agent.Agent(confirm=lambda p: True, persist=False, summarize_async=False)
            try:
                answer = bot.run(c["text"], mode="voice" if c["channel"] == "voice" else "text")
            except Exception as e:  # count a crash as wrong, keep going
                answer = f"ERROR {type(e).__name__}: {e}"
            real_calls = [(n, a) for n, a in calls if n not in ("request_tools", "_say")]
            first = real_calls[0] if real_calls else (None, {})
            got = intent_of(*first) if first[0] else "chat"
            if c["expect"] == "multi":
                did = {intent_of(n, a) for n, a in real_calls}
                good = all(any(ok(p, d) for d in did) for p in c["all"])
                got = "+".join(sorted(did)) or "chat"
            else:
                good = ok(c["expect"], got) and args_ok(c["args"], _real_args(*first))  # a general tool: its real args
            right += good
            used = sum(int(r["total_tokens"] or 0) for r in store._exec(
                "SELECT total_tokens FROM llm_calls WHERE ts>=? AND purpose!='stt'", (ts0 - 0.5,)))
            tokens.append(used)
            ms.append(int((time.monotonic() - t0) * 1000))
            rows.append({"id": c["id"], "text": c["text"], "expect": c["expect"], "got": got, "ok": good,
                         "tokens": used, "ms": ms[-1], "answer": str(answer)[:120]})
            print(f"  {'✓' if good else '✗'} {c['id']:>3} {c['expect']:<18} got {got:<18} {used:>5} tok  {c['text'][:60]}",
                  flush=True)
            time.sleep(pace_s)  # Groq free tier: tokens per minute
    finally:
        safety.execute, jobs.start_task, fastpath._internal = real, real_job, real_internal
    return {"cases": len(cases), "right": right, "rows": rows, "tokens_avg": round(sum(tokens) / max(1, len(tokens))),
            "ms_avg": round(sum(ms) / max(1, len(ms)))}


# --- scorecard ---
def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.0f}%" if b else "–"


def last_card() -> dict | None:
    cards = sorted(OUT_DIR.glob("scorecard-*.json")) if OUT_DIR.is_dir() else []
    return json.loads(cards[-1].read_text()) if cards else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Score KURAMA on the test set")
    ap.add_argument("--ai", action="store_true", help="also run the full agent with the real AI (costs tokens)")
    ap.add_argument("--limit", type=int, default=0, help="only the first N cases (for --ai)")
    ap.add_argument("--cold", action="store_true", help="score before the meaning model is loaded (word rules decide)")
    a = ap.parse_args(argv)
    _isolated_store()
    if not a.cold:  # all-day use: the meaning model is loaded, so shortcuts and routing go by meaning
        from jarvis.core import semantic
        semantic.scores("open youtube")
    cases = load()
    prev = last_card()
    t0 = time.monotonic()
    sc = run_shortcut(cases)
    rt = run_route(cases)
    card = {"when": time.strftime("%Y-%m-%d %H:%M"), "cases": len(cases),
            "shortcut": {"coverage": sc["handled"] / max(1, sum(not c["expect"].startswith("route.") for c in cases)),
                         "precision": sc["right"] / max(1, sc["handled"]),
                         "handled": sc["handled"], "wrong": sc["wrong"]},
            "route": {"recall": rt["right"] / max(1, rt["cases"]), "cases": rt["cases"], "misses": rt["misses"]}}
    if a.ai:
        sub = cases[: a.limit] if a.limit else cases
        print(f"Full agent on {len(sub)} cases (real AI, fake tools)…")
        ai = run_ai(sub)
        card["ai"] = {"accuracy": ai["right"] / max(1, ai["cases"]), "cases": ai["cases"], "tokens_avg": ai["tokens_avg"],
                      "ms_avg": ai["ms_avg"], "rows": ai["rows"]}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"scorecard-{time.strftime('%Y%m%d-%H%M%S')}.json").write_text(json.dumps(card, ensure_ascii=False, indent=1))

    def was(path: list[str]) -> str:
        v = prev
        for k in path:
            v = (v or {}).get(k)
        return f"  (was {v:.0%})" if isinstance(v, float) else ""
    print(f"\nKURAMA scorecard · {card['when']} · {len(cases)} real requests · {time.monotonic() - t0:.0f} s")
    print(f"  Instant shortcuts handle {card['shortcut']['coverage']:.0%} of requests{was(['shortcut', 'coverage'])}; "
          f"right when they do: {card['shortcut']['precision']:.0%}{was(['shortcut', 'precision'])}")
    print(f"  Router offers the right tools: {card['route']['recall']:.0%}{was(['route', 'recall'])}")
    if "ai" in card:
        print(f"  Full agent right: {card['ai']['accuracy']:.0%}{was(['ai', 'accuracy'])} · "
              f"{card['ai']['tokens_avg']} tokens and {card['ai']['ms_avg']} ms per request on average")
    if sc["wrong"]:
        print(f"\n  Shortcut mistakes ({len(sc['wrong'])}):")
        for w in sc["wrong"]:
            print(f"    #{w['id']} {w['text'][:60]!r}: expected {w['expect']}, did {w['got']} {w['args']}")
    fams = Counter(m["expect"].split(".")[0] for m in rt["misses"])
    if fams:
        print("\n  Router misses by area: " + ", ".join(f"{k} {n}" for k, n in fams.most_common()))
    if "ai" in card:
        bad = defaultdict(list)
        for r in card["ai"]["rows"]:
            if not r["ok"]:
                bad[r["expect"].split(".")[0]].append(r)
        if bad:
            print("\n  Full-agent mistakes:")
            for k, rs in sorted(bad.items(), key=lambda kv: -len(kv[1])):
                for r in rs:
                    print(f"    #{r['id']} {r['text'][:55]!r}: expected {r['expect']}, did {r['got']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
