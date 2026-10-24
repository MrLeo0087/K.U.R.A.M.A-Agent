"""stopwatch: start / stop / lap / reset / status, kept in the database so it survives restarts. Safe."""
from __future__ import annotations

import json
import time
from typing import Literal

from jarvis.core import store
from jarvis.core.registry import tool

KEY = "stopwatch"


def fmt(s: float) -> str:
    s = int(round(s))
    h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return (f"{h} hour{'s' * (h != 1)} " if h else "") + (f"{m} minute{'s' * (m != 1)} " if m else "") + \
        f"{sec} second{'s' * (sec != 1)}"


@tool(group="clock", safety="safe", description="Stopwatch: start, stop, lap, reset or check the time.")
def stopwatch(action: Literal["start", "stop", "lap", "reset", "status"] = "status") -> str:
    """Control the stopwatch.

    Args:
        action: start, stop (pause), lap, reset or status.
    """
    st = json.loads(store.kv_get(KEY, "") or "{}") or {"run": None, "acc": 0.0, "laps": []}
    now = time.time()
    total = st["acc"] + (now - st["run"] if st["run"] else 0)
    if action == "start":
        if st["run"]:
            return f"The stopwatch is already running: {fmt(total)}."
        st["run"] = now
        msg = "Stopwatch started." if not st["acc"] else f"Stopwatch resumed at {fmt(total)}."
    elif action == "stop":
        if not st["run"]:
            return f"The stopwatch isn't running ({fmt(total)} so far)."
        st["acc"], st["run"] = total, None
        msg = f"Stopped at {fmt(total)}."
    elif action == "lap":
        st["laps"].append(total)
        msg = f"Lap {len(st['laps'])}: {fmt(total)}."
    elif action == "reset":
        st = {"run": None, "acc": 0.0, "laps": []}
        msg = "Stopwatch reset."
    else:
        state = "running" if st["run"] else "stopped" if total else "not started"
        laps = f" Laps: {', '.join(fmt(x) for x in st['laps'][-3:])}." if st["laps"] else ""
        return f"Stopwatch {state}: {fmt(total)}.{laps}"
    store.kv_set(KEY, json.dumps(st))
    return msg
