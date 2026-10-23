"""Daily digest (P7): a zero-LLM template of the day's activity.

Conversations + topics (session summaries / user messages), jobs done (titles + output paths),
alerts, notes added, token usage, git commits in config.MEMORY_ROOTS repos and a weather one-liner.
config.DIGEST_USE_LLM=True adds ONE fast-tier call to polish it (default off). The first line is a
voice-friendly summary. Delivered by jarvis/workers/daily_digest.py and the daily_digest tool.
"""
from __future__ import annotations

import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Callable

from jarvis.core import config, episodes, store, usage

log = logging.getLogger("jarvis.digest")


def _n(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _short_path(path: str) -> str:
    try:
        return Path(path).resolve().relative_to(Path(config.ROOT).resolve()).as_posix()
    except (ValueError, OSError):
        return path.replace(str(Path.home()), "~")


def git_activity(t0: float, t1: float, roots: list[Path] | None = None) -> list[dict]:
    """[{repo, commits, last}] for git repos among roots with commits in [t0, t1)."""
    out = []
    for root in roots if roots is not None else config.MEMORY_ROOTS:
        root = Path(root)
        if not (root / ".git").exists():
            continue
        try:
            res = subprocess.run(["git", "-C", str(root), "log", f"--since=@{int(t0)}", f"--until=@{int(t1)}",
                                  "--pretty=%s"], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.info("git log failed for %s: %s", root, e)
            continue
        subjects = [s for s in res.stdout.splitlines() if s.strip()] if res.returncode == 0 else []
        if subjects:
            out.append({"repo": root.name, "commits": len(subjects), "last": subjects[0][:70]})
    return out


def _weather(weather_fn: Callable[[str], str] | None) -> str:
    if weather_fn is not None:
        from jarvis.core import greeting
        return greeting.weather_line(weather_fn)
    from jarvis.core import profile
    from jarvis.tools.general import _geo  # plain HTTP: keeps LangChain out of the workers process

    return _geo.current_line(profile.home_place())


def build_digest(date: str = "today", now: datetime | None = None, use_llm: bool | None = None,
                 weather_fn: Callable[[str], str] | None = None, with_weather: bool = True) -> str:
    now = now or datetime.now()
    day = episodes.parse_day(date or "today", now) or episodes.parse_day("today", now)
    t0, t1, label = day  # type: ignore[misc]
    day_name = datetime.fromtimestamp(t0).strftime("%A %d %b")
    sessions = store.sessions_between(t0, t1)
    msgs = store.messages_between(t0, t1, limit=5000)
    convs = len(sessions) or (1 if msgs else 0)
    tops = episodes.topics(t0, t1)
    jobs = store.jobs_finished_between(t0, t1)
    alerts = store.alerts_between(t0, t1)
    notes = store.notes_between(t0, t1)
    use = usage.summary(t0=t0, t1=t1, label=label)
    git = git_activity(t0, t1)
    commits = sum(g["commits"] for g in git)

    head = [_n(convs, "conversation"), _n(len(jobs), "job") + " done", _n(len(alerts), "alert")]
    if commits:
        head.append(_n(commits, "commit"))
    head.append(f"{use['tokens']:,} tokens")
    lines = [f"{label.capitalize() if label in ('today', 'yesterday') else day_name}: " + ", ".join(head) + "."]
    lines.append(f"Daily digest for {day_name}.")
    if convs:
        lines.append(f"Conversations: {convs} ({len(msgs)} messages)" + (f"; topics: {', '.join(tops)}." if tops else "."))
    if jobs:
        items = [f'"{j["title"][:50]}"' + (f" ({_short_path(j['output_path'])})" if j.get("output_path") else "")
                 for j in jobs[-5:]]
        lines.append("Jobs done: " + "; ".join(items) + ".")
    if alerts:
        lines.append("Alerts: " + "; ".join(a["title"] for a in alerts[-5:]) + ".")
    if notes:
        lines.append("Notes added: " + "; ".join(f'"{n["text"][:60]}"' for n in notes[-5:]) + ".")
    tok = f"Tokens: {use['tokens']:,} in {use['calls']} calls"
    if label == "today" and use["budget_pct_today"]:
        tok += f" ({max(use['budget_pct_today'].values()):g}% of the busiest model's daily budget)"
    if use["fastpath_hits"]:
        tok += f"; fast path saved ~{use['tokens_saved_est']:,}"
    lines.append(tok + ".")
    if git:
        lines.append("Git: " + "; ".join(f"{g['repo']} {_n(g['commits'], 'commit')} (last: \"{g['last']}\")"
                                         for g in git) + ".")
    if with_weather and label == "today" and (w := _weather(weather_fn)):
        lines.append("Weather: " + w)
    text = "\n".join(lines)
    if config.DIGEST_USE_LLM if use_llm is None else use_llm:
        text = polish(text)
    return text


POLISH_PROMPT = ("Rewrite this daily digest as a friendly summary: one spoken first sentence, then at most "
                 "4 short plain lines. Keep every number, title and path. No markdown.")


def polish(text: str) -> str:
    """One fast-tier call; the template on any failure."""
    from jarvis.core import llm

    try:
        out = str(llm.chat([{"role": "system", "content": POLISH_PROMPT}, {"role": "user", "content": text}],
                           tier="fast", purpose="digest", max_tokens=300)).strip()
        return out or text
    except Exception as e:
        log.info("digest polish skipped: %s", e)
        return text
