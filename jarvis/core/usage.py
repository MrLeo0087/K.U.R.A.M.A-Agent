"""Token usage / API cost report (P7) from the llm_calls and routing logs. Zero LLM tokens.

summary(period) -> dict, report(period) -> text whose FIRST line is a voice-friendly sentence.
period: today | week (last 7 days) | month (since the 1st). Cost is $0.00 on the Groq free tier;
with config.MODEL_PRICES set it also shows what the same usage would cost at paid prices.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from jarvis.core import config, store

PERIODS = ("today", "week", "month")


def bounds(period: str, now: datetime | None = None) -> tuple[float, float, str]:
    now = now or datetime.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    p = (period or "today").lower().strip()
    if p in ("week", "this week", "last 7 days", "7d"):
        return (midnight - timedelta(days=6)).timestamp(), now.timestamp() + 1, "the last 7 days"
    if p in ("month", "this month", "30d"):
        return midnight.replace(day=1).timestamp(), now.timestamp() + 1, "this month"
    return midnight.timestamp(), now.timestamp() + 1, "today"


def short(model: str) -> str:
    return (model or "?").split("/")[-1]


def _purpose_group(p: str) -> str:
    p = p or "other"
    if re.match(r"job\d+:", p):
        return "jobs"
    return p.split(":")[0]


def _injected(t0: float, t1: float) -> int:
    total, d = 0, datetime.fromtimestamp(t0)
    while d.timestamp() < t1:
        total += int(store.kv_get(f"profile_inject_tokens:{d.strftime('%Y-%m-%d')}", "0") or 0)
        d += timedelta(days=1)
    return total


def cost(models: dict[str, dict]) -> float | None:
    """USD at config.MODEL_PRICES (per 1M tokens / per audio hour); None when no prices are set."""
    if not config.MODEL_PRICES:
        return None
    usd = 0.0
    for m, row in models.items():
        price = config.MODEL_PRICES.get(m) or {}
        usd += row["prompt"] / 1e6 * price.get("in", 0.0) + row["completion"] / 1e6 * price.get("out", 0.0)
        usd += row["audio_s"] / 3600 * price.get("audio_hour", 0.0)
    return usd


def summary(period: str = "today", now: datetime | None = None, t0: float | None = None,
            t1: float | None = None, label: str | None = None) -> dict:
    if t0 is None or t1 is None:
        t0, t1, label = bounds(period, now)
    rows = store.llm_usage_between(t0, t1)
    models: dict[str, dict] = {}
    purposes: dict[str, int] = {}
    stt = {"calls": 0, "audio_s": 0.0}
    for r in rows:
        if r["purpose"] == "stt":
            stt["calls"] += r["ok_calls"] or 0
            stt["audio_s"] += r["audio_s"] or 0.0
        m = models.setdefault(r["model"], {"calls": 0, "errors": 0, "prompt": 0, "completion": 0, "total": 0,
                                           "audio_s": 0.0})
        m["calls"] += r["ok_calls"] or 0
        m["errors"] += (r["calls"] or 0) - (r["ok_calls"] or 0)
        for k in ("prompt", "completion", "total", "audio_s"):
            m[k] += r[k] or 0
        if r["total"]:
            g = _purpose_group(r["purpose"])
            purposes[g] = purposes.get(g, 0) + int(r["total"])
    fast_hits = store.routing_count("fastpath", t0, t1)
    today_used = store.tokens_by_model_today()
    budget = {m: round(100.0 * today_used.get(m, 0) / cap, 1) for m, cap in config.DAILY_TOKEN_BUDGET.items() if cap}
    tokens = sum(m["total"] for m in models.values())
    return {"label": label, "t0": t0, "t1": t1, "tokens": tokens,
            "calls": sum(m["calls"] for k, m in models.items() if k not in _stt_models(rows)),
            "models": models, "purposes": dict(sorted(purposes.items(), key=lambda kv: -kv[1])),
            "fastpath_hits": fast_hits, "tokens_saved_est": fast_hits * config.FASTPATH_TOKENS_SAVED_EST,
            "stt": stt, "budget_pct_today": budget, "profile_injected": _injected(t0, t1),
            "cost_usd": cost(models)}


def _stt_models(rows: list[dict]) -> set[str]:
    return {r["model"] for r in rows if r["purpose"] == "stt"}


def first_line(s: dict) -> str:
    label = s["label"]
    head = label[0].upper() + label[1:]
    line = f"{head} you used {s['tokens']:,} tokens in {s['calls']} LLM call{'s' if s['calls'] != 1 else ''}"
    if s["budget_pct_today"]:
        m, pct = max(s["budget_pct_today"].items(), key=lambda kv: kv[1])
        line += f"; the busiest model is at {'under 1' if pct < 1 else f'{pct:g}'}% of today's budget"
    if s["fastpath_hits"]:
        line += f"; the fast path answered {s['fastpath_hits']} requests for free (~{s['tokens_saved_est']:,} tokens saved)"
    return line + "."


def report(period: str = "today", now: datetime | None = None) -> str:
    s = summary(period, now)
    lines = [first_line(s)]
    llm_models = {m: r for m, r in s["models"].items() if r["total"] or not r["audio_s"]}
    if llm_models:
        parts = []
        for m, r in sorted(llm_models.items(), key=lambda kv: -kv[1]["total"]):
            pct = s["budget_pct_today"].get(m)
            extra = f", {pct:g}% of daily" if pct is not None and s["label"] == "today" else ""
            parts.append(f"{short(m)} {r['total']:,} ({r['calls']} calls{extra})")
        lines.append("By model: " + "; ".join(parts) + ".")
    if s["purposes"]:
        lines.append("Top uses: " + "; ".join(f"{p} {n:,}" for p, n in list(s["purposes"].items())[:5]) + ".")
    if s["stt"]["calls"]:
        pct = 100.0 * s["stt"]["audio_s"] / config.STT_DAILY_AUDIO_SECONDS if s["label"] == "today" else None
        lines.append(f"Speech-to-text: {s['stt']['calls']} clips, {s['stt']['audio_s']:.0f} s of audio"
                     + (f" ({pct:.1f}% of the daily {config.STT_DAILY_AUDIO_SECONDS:,} s)." if pct is not None else "."))
    if s["profile_injected"]:
        lines.append(f"Profile memory added ~{s['profile_injected']:,} prompt tokens.")
    c = s["cost_usd"]
    lines.append("Cost: $0.00 (Groq free tier)." + (f" At paid prices it would be ${c:.4f}." if c is not None
                                                    else " Paid-tier estimate off (config.MODEL_PRICES is empty)."))
    return "\n".join(lines)
