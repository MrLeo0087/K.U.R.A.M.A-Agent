"""KURAMA power modes: how much of KURAMA runs, so it fits next to big tasks on an 8 GB laptop.

A mode is a set of switches, each one a real RAM / CPU / token cost:
  workers  which background helpers run (reminders, Telegram, training watch ...); they live in the server process
  model    the local understanding model (bge-small ONNX, ~120-250 MB while loaded): always / auto / off
  ai       best (the smart model for everything) / normal (smart only for hard tasks) / fast (small model only)
           / off (0 tokens: only built-in commands)
  wake     listen for "KURAMA" / "wake up" (mic + a Whisper call per speech burst)
  screen   full (dashboard with effects) / calm (no animation) / mini (big dashboard freed: only the floating button)
Presets: full, smart (best AI), normal (default), basic, lowram, laptop (only), noai.
Choosing a preset sets every switch; changing one switch makes the mode "custom". Stored in kv 'power_mode'.
"""
from __future__ import annotations

import json
import time

from jarvis.core import config

WORKERS = {  # name -> (label, what it does); order = how the UI lists them
    "scheduler": ("Reminders & alarms", "fires reminders, alarms, timers and scheduled commands"),
    "telegram_bot": ("Telegram", "control KURAMA from your phone"),
    "clipboard_watch": ("Copy history", "remembers what you copy for 24 h (only on this laptop)"),
    "process_watch": ("Training watch", "watches training runs and long commands, alerts when done"),
    "resource_guard": ("RAM / disk alerts", "warns when RAM, CPU or disk get too full"),
    "crash_watchdog": ("Server watchdog", "restarts the dev servers you asked it to keep alive"),
    "guard": ("Laptop guard", "photo + location to Telegram on wrong password (only while armed)"),
    "timemachine": ("Time machine", "snapshots your protected projects"),
    "daily_digest": ("Daily digest", "a summary once a day"),
    "location_tracker": ("Location history", "records where the laptop is"),
}
ALL = tuple(WORKERS)
ESSENTIAL = ("scheduler", "telegram_bot", "clipboard_watch", "process_watch", "resource_guard", "crash_watchdog", "guard")

PRESETS: dict[str, dict] = {
    "full": {"name": "Full power", "desc": "Everything on and always ready: fastest answers, most RAM.",
             "workers": list(ALL), "model": "always", "ai": "normal", "wake": True, "screen": "full"},
    "smart": {"name": "Best AI", "desc": "The best AI model answers everything: slower and uses more tokens.",
              "workers": list(ALL), "model": "auto", "ai": "best", "wake": True, "screen": "full"},
    "normal": {"name": "Normal", "desc": "The normal KURAMA: everything on, the model loads when needed.",
                 "workers": list(ALL), "model": "auto", "ai": "normal", "wake": True, "screen": "full"},
    "basic": {"name": "Basic", "desc": "Only the important helpers, calm screen. Good for everyday work.",
              "workers": list(ESSENTIAL), "model": "auto", "ai": "normal", "wake": True, "screen": "calm"},
    "lowram": {"name": "Low RAM", "desc": "Laptop is busy: small dashboard, no wake word, small AI. Reminders "
                                       "and Telegram still work.",
              "workers": ["scheduler", "telegram_bot"], "model": "off", "ai": "fast", "wake": False, "screen": "mini"},
    "laptop": {"name": "Laptop only", "desc": "No background helpers at all (no Telegram, reminders wait). "
                                              "KURAMA only does what you type or say.",
               "workers": [], "model": "off", "ai": "fast", "wake": False, "screen": "mini"},
    "noai": {"name": "No AI", "desc": "0 tokens: only built-in commands (open apps, volume, files, reminders...). "
                                      "Works when Groq is down or the limit is used up.",
             "workers": ["scheduler", "telegram_bot"], "model": "off", "ai": "off", "wake": False, "screen": "calm"},
}
DEFAULT = "normal"
AI_LEVELS = ("best", "normal", "fast", "off")
MODEL_MODES = ("always", "auto", "off")
SCREENS = ("full", "calm", "mini")
KEYS = ("workers", "model", "ai", "wake", "screen")

_cache: tuple[float, dict] = (0.0, {})


def current() -> dict:
    """{'mode': id, 'workers': [...], 'model', 'ai', 'wake', 'screen'} (cached 3 s: read on every LLM call)."""
    global _cache
    if time.monotonic() - _cache[0] < 3 and _cache[1]:
        return _cache[1]
    try:
        from jarvis.core import store
        raw = json.loads(store.kv_get("power_mode") or "{}")
    except Exception:  # noqa: BLE001 - no DB yet: the default mode
        raw = {}
    st = _clean(raw)
    _cache = (time.monotonic(), st)
    return st


def _clean(raw: dict) -> dict:
    mode = raw.get("mode") if raw.get("mode") in PRESETS or raw.get("mode") == "custom" else DEFAULT
    base = PRESETS.get(mode, PRESETS[DEFAULT])
    st = {"mode": mode}
    for k in KEYS:
        st[k] = raw.get(k, base[k]) if mode == "custom" else base[k]  # a preset is always its current definition
    st["workers"] = [w for w in st["workers"] if w in WORKERS]
    st["model"] = st["model"] if st["model"] in MODEL_MODES else "auto"
    st["ai"] = st["ai"] if st["ai"] in AI_LEVELS else "normal"
    st["screen"] = st["screen"] if st["screen"] in SCREENS else "full"
    st["wake"] = bool(st["wake"])
    return st


def _save(st: dict) -> dict:
    global _cache
    from jarvis.core import store
    st = _clean(st)
    store.kv_set("power_mode", json.dumps(st))
    _cache = (0.0, {})
    _apply(st)
    return st


def set_mode(mode: str) -> dict:
    if mode not in PRESETS:
        raise ValueError(f"mode must be one of {', '.join(PRESETS)}")
    return _save({"mode": mode, **{k: PRESETS[mode][k] for k in KEYS}})


def set_switch(key: str, value) -> dict:
    """Change one switch (workers: {'name': bool} or the full list); the mode becomes 'custom'."""
    st = dict(current())
    if key == "workers" and isinstance(value, dict):
        on = set(st["workers"])
        for name, want in value.items():
            if name not in WORKERS:
                raise ValueError(f"unknown helper {name!r}")
            (on.add if want else on.discard)(name)
        value = [w for w in ALL if w in on]
    elif key not in KEYS:
        raise ValueError(f"unknown switch {key!r}")
    st[key] = value
    st["mode"] = "custom"
    for pid, p in PRESETS.items():  # back on a preset's exact settings: show its name again
        if all(sorted(p[k]) == sorted(st[k]) if k == "workers" else p[k] == st[k] for k in KEYS):
            st["mode"] = pid
            break
    return _save(st)


def _apply(st: dict) -> None:
    """Make the running process match: the model's mode, the workers (picked up by the in-server supervisor
    within a heartbeat), the wake listener."""
    from jarvis.core import semantic
    semantic.set_mode(st["model"])
    if not st["wake"]:
        try:
            from jarvis.api.routes import wake
            wake.SERVICE.stop()
        except Exception:  # noqa: BLE001 - not inside the server
            pass
    try:
        from jarvis.workers import inproc
        inproc.reconcile_soon()
    except Exception:  # noqa: BLE001
        pass


def ai_level() -> str:
    return current()["ai"]


def wake_allowed() -> bool:
    return current()["wake"]


def desired_workers() -> list[str]:
    """The helpers that should run now: the mode's list, limited by JARVIS_WORKERS (the env still wins)."""
    return [w for w in current()["workers"] if w in config.WORKERS_ENABLED]


def name(st: dict | None = None) -> str:
    st = st or current()
    return PRESETS[st["mode"]]["name"] if st["mode"] in PRESETS else "Custom"


# rough idle RAM (MB, PSS) of each part, measured on this laptop: the UI shows a mode's estimate with them
RAM_SERVER, RAM_DASHBOARD, RAM_MINI, RAM_MODEL, RAM_WORKER = 100, 145, 55, 130, 1


def estimate(st: dict) -> int:
    """About how much RAM KURAMA uses idle with these switches (the model counts only when kept loaded)."""
    screen = RAM_MINI if st["screen"] == "mini" else RAM_DASHBOARD
    return RAM_SERVER + screen + (RAM_MODEL if st["model"] == "always" else 0) + RAM_WORKER * len(st["workers"])


def summary() -> dict:
    """Everything the UI needs: the current switches, the presets, the helpers' labels."""
    cur = current()
    return {"current": {**cur, "name": name(cur), "est_mb": estimate(cur)}, "name": name(cur),
            "presets": [{"id": k, "name": v["name"], "desc": v["desc"], **{x: v[x] for x in KEYS},
                         "est_mb": estimate(v)} for k, v in PRESETS.items()],
            "workers": [{"id": k, "name": v[0], "desc": v[1], "available": k in config.WORKERS_ENABLED}
                        for k, v in WORKERS.items()]}


NO_AI = ("AI answers are off (No AI mode), so I can only do built-in commands, like 'open youtube', 'volume 40', "
         "'remind me at 5 to call mom', 'find my resume', 'battery'. Switch the mode on the dashboard for full answers.")
