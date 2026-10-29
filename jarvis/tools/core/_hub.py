"""v2 general tools: the ONLY tools the AI sees (about 17 instead of 133). Each takes an `action` and a few plain
arguments and hands the work to the existing specialised tool through safety.execute, so every confirmation
(delete, shutdown, run a command...) and every log line still happens exactly as before.

    resolve(table, args) -> (tool, tool_args)   pure: what WOULD run (the test harness uses it)
    run(table, args)                            does it, inside the caller's tool context

A table maps action -> Act(tool, args_fn). args_fn gets the general tool's arguments (only the non-empty ones) and
returns the specialised tool's arguments; a callable instead of Act decides the tool at run time (e.g. "open"
chooses app / website / folder from the name).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from jarvis.core import safety


@dataclass
class Act:
    tool: str
    args: Callable[[dict], dict] = field(default=lambda a: {})


Table = dict[str, "Act | Callable[[dict], tuple[str, dict]]"]


def clean(a: dict) -> dict:
    return {k: v for k, v in a.items() if v not in (None, "", [], {}) and v is not False}  # False = the default


def resolve(table: Table, args: dict) -> tuple[str, dict]:
    a = clean(dict(args))
    action = a.pop("action", None) or next(iter(table))
    act = table.get(action)
    if act is None:
        raise ValueError(f"unknown action {action!r}; choose from {', '.join(table)}")
    if isinstance(act, Act):
        return act.tool, clean(act.args(a))
    tool, targs = act(a)
    return tool, clean(targs)


def run(table: Table, args: dict) -> str:
    try:
        tool, targs = resolve(table, args)
    except ValueError as e:
        return f"error: {e}"
    ctx = dict(safety.context())
    res = safety.execute(tool, targs, confirm=ctx.pop("confirm", None), ctx=ctx)
    return res.output


# --- small parsers shared by the tools ---
_UNITS = {"h": 3600, "hr": 3600, "hour": 3600, "m": 60, "min": 60, "minute": 60, "s": 1, "sec": 1, "second": 1}


def duration(text: str) -> dict:
    """'5 minutes' / '1 hour 20 min' / '90 sec' / '10' (minutes) -> set_timer arguments."""
    t = (text or "").lower()
    total = 0.0
    for n, u in re.findall(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b", t):
        total += float(n) * _UNITS[u.rstrip("s") if u not in ("s", "hrs") else ("s" if u == "s" else "hr")]
    if not total and (m := re.search(r"\d+(?:\.\d+)?", t)):
        total = float(m.group(0)) * 60
    return {"seconds": total} if total else {}


def onoff(v: Any, default: str = "toggle") -> str:
    s = str(v or "").lower().strip()
    return "on" if s in ("on", "enable", "enabled", "true", "yes", "start") else \
        "off" if s in ("off", "disable", "disabled", "false", "no", "stop") else \
        "status" if s in ("status", "check", "get", "?") else default


def underlying(name: str, args: dict | None) -> tuple[str, dict]:
    """The specialised tool (and its arguments) a general tool call would run; (name, args) for any other tool.
    Used for the template replies (no second AI call for simple actions) and by the test harness."""
    import importlib
    try:
        mod = importlib.import_module(f"jarvis.tools.core.{name}")
    except ImportError:
        return name, dict(args or {})
    table = getattr(mod, "TABLE", None)
    if not table:
        return name, dict(args or {})
    try:
        a = dict(args or {})
        if name == "apps" and a.get("action") == "open":  # several sites: the first one decides
            a["target"] = re.split(r",|\band\b", a.get("target") or "")[0].strip()
        if name == "telegram" and a.get("action") == "file":
            a.setdefault("file", a.get("file", ""))
        return resolve(table, a)
    except Exception:
        return name, dict(args or {})
