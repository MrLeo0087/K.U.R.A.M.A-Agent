"""Settings the owner can change by voice or text ("make the speed test 30 seconds"). A fixed, safe list: each one
has a plain name, what it does, the allowed range and its default. Nothing outside this list can be changed this way,
so KURAMA can never break itself by a request.

    data/user_settings.json   {"values": {CONFIG_KEY: value}, "history": [[name, old, new, ts], ...]}

config.py applies the saved values when it loads (every process); set() also changes the running process at once.
A setting marked restart=True is read once at start-up (the key watcher): it applies after a restart.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field

from jarvis.core import config

_lock = threading.Lock()


@dataclass(frozen=True)
class Setting:
    name: str  # what the owner says (spaces ok): "speed test seconds"
    key: str  # the config.py name it changes
    what: str  # one line: what it changes, in plain words
    unit: str = ""  # shown unit: seconds | minutes | ms | % | KB | px | tokens | turns | hours | time | rate
    lo: float = 0.0
    hi: float = 0.0
    scale: float = 1.0  # config value = shown value * scale (minutes shown, seconds stored: 60)
    kind: str = "number"  # number | time (HH:MM) | rate (+15%)
    restart: bool = False
    examples: tuple[str, ...] = field(default=())  # other ways to say it (meaning search)


SETTINGS: tuple[Setting, ...] = (
    Setting("speed test seconds", "SPEEDTEST_SECONDS", "how long the internet speed test runs in total", "seconds",
            5, 60, examples=("internet speed test time", "make the speed test longer", "speed check duration")),
    Setting("weather cache minutes", "WEATHER_CACHE_S", "how long a weather answer is reused before asking again",
            "minutes", 0, 120, 60, examples=("weather refresh time", "how often weather updates")),
    Setting("reply length", "AGENT_MAX_TOKENS", "how long the AI's answers may be (more = longer answers, more tokens)",
            "tokens", 150, 1500, examples=("longer answers", "shorter replies", "answer length")),
    Setting("chat memory turns", "HISTORY_TURNS", "how many recent turns of the chat the AI sees (more = more tokens)",
            "turns", 2, 12, examples=("remember more of the conversation", "history length")),
    Setting("background after seconds", "TOOL_BACKGROUND_AFTER_S",
            "how long a slow action may run before it continues in the background", "seconds", 1, 30,
            examples=("wait longer before background", "background job delay")),
    Setting("telegram photo size", "TELEGRAM_PHOTO_TARGET_KB", "how small photos are made before sending to Telegram",
            "KB", 60, 1000, examples=("telegram photo quality", "send bigger photos", "screenshot quality on telegram")),
    Setting("telegram photo width", "TELEGRAM_PHOTO_PX", "the width photos are resized to for Telegram", "px", 640,
            2560, examples=("telegram photo resolution",)),
    Setting("ram alert percent", "RAM_ALERT_PCT", "RAM use that triggers a warning", "%", 50, 99,
            examples=("ram warning level", "memory alert threshold")),
    Setting("hold to talk minimum", "PTT_MIN_HOLD_S", "how long Alt must be held to count as talking", "seconds",
            0.1, 2, restart=True, examples=("alt hold time", "push to talk minimum hold")),
    Setting("hold to talk delay", "PTT_START_DELAY_S", "how long Alt is held alone before listening starts", "seconds",
            0.1, 1.5, restart=True, examples=("alt key delay", "talk key start delay")),
    Setting("end of speech wait", "VAD_SILENCE_MS", "how long I wait after you stop talking before I answer", "ms",
            300, 3000, examples=("wait longer after I stop speaking", "silence before reply", "don't cut me off")),
    Setting("longest voice request", "VAD_MAX_UTTERANCE_S", "the longest one spoken request may be", "seconds", 5,
            60, examples=("speak longer", "voice message length")),
    Setting("wake sleep seconds", "WAKE_IDLE_S", "how long I stay awake after the wake word without hearing you",
            "seconds", 10, 600, examples=("stay awake longer", "wake word timeout")),
    Setting("speaking speed", "TTS_RATE", "how fast I speak (+0% = normal)", "rate", -50, 100, kind="rate",
            examples=("talk faster", "speak slower", "voice speed")),
    Setting("daily summary time", "DIGEST_TIME", "when the daily summary is sent", "time", kind="time",
            examples=("digest time", "day summary at")),
    Setting("link name wait", "LINK_NAME_TTL_S", "how long 'what should I call this link?' waits for the name",
            "seconds", 30, 1800),
    Setting("colab progress seconds", "COLAB_PROGRESS_EVERY_S", "how often a Colab/Kaggle run sends progress inside "
            "an epoch (new notebooks)", "seconds", 10, 600, examples=("training update interval",)),
    Setting("clipboard history hours", "CLIPBOARD_KEEP_H", "how long copied text is kept in the copy history",
            "hours", 1, 168, examples=("keep clipboard longer",)),
    Setting("meaning model idle seconds", "EMBED_IDLE_UNLOAD_S", "how long the local meaning model stays loaded when "
            "unused (longer = faster, more RAM)", "seconds", 30, 1800),
    Setting("coding agent idle minutes", "AGENT_IDLE_OFF_S", "how long the coding agent stays on without being used",
            "minutes", 5, 240, 60),
)
BY_NAME = {s.name: s for s in SETTINGS}


def _path():
    return config.DATA_DIR / "user_settings.json"


def _load() -> dict:
    try:
        d = json.loads(_path().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d: dict) -> None:
    _path().parent.mkdir(parents=True, exist_ok=True)
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_path())


def default(s: Setting):
    return config.SETTING_DEFAULTS.get(s.key, getattr(config, s.key))


def shown(s: Setting, value=None) -> str:
    v = getattr(config, s.key) if value is None else value
    if s.kind in ("time", "rate"):
        return str(v)
    n = float(v) / s.scale
    n = int(n) if n == int(n) else round(n, 2)
    return f"{n} {s.unit}".strip()


def find(name: str) -> Setting | None:
    """A setting by its name, a close name, or its meaning (local model, 0 tokens)."""
    q = " ".join(re.sub(r"[^\w\s]", " ", (name or "").lower()).split())
    if not q:
        return None
    if q in BY_NAME:
        return BY_NAME[q]
    words = set(q.split())
    best = max(SETTINGS, key=lambda s: len(words & set(s.name.split())))
    if len(words & set(best.name.split())) >= max(2, len(best.name.split()) - 1):
        return best
    try:
        from jarvis.core import semantic
        if semantic.ready() and (b := semantic.best_of(q, "user_settings", {s.name: (s.name, s.what, *s.examples)
                                                                            for s in SETTINGS})) and b[1] >= 0.72:
            return BY_NAME[b[0]]
    except Exception:  # noqa: BLE001
        pass
    return None


_UNITS = {"ms": 0.001, "millisecond": 0.001, "milliseconds": 0.001, "s": 1, "sec": 1, "secs": 1, "second": 1,
          "seconds": 1, "min": 60, "mins": 60, "minute": 60, "minutes": 60, "h": 3600, "hour": 3600, "hours": 3600}
_SHOWN_SECONDS = {"seconds": 1, "minutes": 60, "ms": 0.001, "hours": 3600}


def parse(s: Setting, text: str):
    """The config value for what the owner said ('30 seconds', '2 minutes', '10 PM', '+20%'), or raise ValueError."""
    t = (text or "").strip().lower()
    if s.kind == "time":
        m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?", t)
        if not m:
            raise ValueError("say a time like 21:30 or 9 PM")
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if m.group(3) and m.group(3).startswith("p") and h < 12:
            h += 12
        if m.group(3) and m.group(3).startswith("a") and h == 12:
            h = 0
        if not (0 <= h < 24 and 0 <= mi < 60):
            raise ValueError("that isn't a time of day")
        return f"{h:02d}:{mi:02d}"
    m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*(%|[a-z]+)?", t)
    if not m:
        raise ValueError(f"say a number ({s.unit})")
    n, unit = float(m.group(1)), (m.group(2) or "")
    if s.kind == "rate":
        if not s.lo <= n <= s.hi:
            raise ValueError(f"the speaking speed goes from {int(s.lo)}% to +{int(s.hi)}%")
        return f"{'+' if n >= 0 else ''}{int(n)}%"
    if unit in _UNITS and s.unit in _SHOWN_SECONDS:  # '2 minutes' for a setting shown in seconds
        n = n * _UNITS[unit] / _SHOWN_SECONDS[s.unit]
    if not s.lo <= n <= s.hi:
        raise ValueError(f"{s.name} goes from {s.lo:g} to {s.hi:g} {s.unit}")
    v = n * s.scale
    cur = getattr(config, s.key)
    return int(round(v)) if isinstance(cur, int) and not isinstance(cur, bool) else float(v)


def set_value(name: str, text: str) -> str:
    s = find(name)
    if s is None:
        return f"error: '{name}' isn't a setting I can change. Say 'what settings can I change?'"
    try:
        v = parse(s, text)
    except ValueError as e:
        return f"error: {e}"
    with _lock:
        d = _load()
        old = getattr(config, s.key)
        config.SETTING_DEFAULTS.setdefault(s.key, old)  # first change in this process: the old value is the default
        d.setdefault("values", {})[s.key] = v
        d.setdefault("history", []).append([s.name, old, v, time.time()])
        d["history"] = d["history"][-50:]
        _save(d)
        setattr(config, s.key, v)
    note = " It applies after a restart." if s.restart else ""
    return f"Done: {s.name} is now {shown(s, v)} (was {shown(s, old)}).{note} Say 'undo that setting' to go back."


def reset(name: str = "") -> str:
    with _lock:
        d = _load()
        vals = d.setdefault("values", {})
        targets = SETTINGS if (name or "").strip().lower() in ("", "all", "everything") else [find(name)]
        if targets == [None]:
            return f"error: '{name}' isn't a setting I can change."
        done = []
        for s in targets:
            if s is not None and s.key in vals:
                vals.pop(s.key)
                setattr(config, s.key, default(s))
                done.append(s.name)
        _save(d)
    return f"Back to default: {', '.join(done)}." if done else "Nothing to reset: those settings are at their defaults."


def undo() -> str:
    with _lock:
        d = _load()
        hist = d.get("history") or []
        if not hist:
            return "There's no setting change to undo."
        name, old, _new, _ts = hist.pop()
        s = BY_NAME.get(name)
        if s is None:
            return "There's no setting change to undo."
        d.setdefault("values", {})[s.key] = old
        _save(d)
        setattr(config, s.key, old)
    return f"Undone: {s.name} is {shown(s, old)} again."


def get(name: str) -> str:
    s = find(name)
    if s is None:
        return f"error: '{name}' isn't a setting I know."
    changed = "" if getattr(config, s.key) == default(s) else f" (default {shown(s, default(s))})"
    rng = f"; allowed {s.lo:g} to {s.hi:g} {s.unit}" if s.kind == "number" else ""
    return f"{s.name}: {shown(s)}{changed}. It is {s.what}{rng}."


def listing() -> str:
    lines = [f"- {s.name}: {shown(s)}" + ("" if getattr(config, s.key) == default(s) else " (changed)") + f" — {s.what}"
             for s in SETTINGS]
    return ("Settings you can change (say e.g. 'set speed test seconds to 30', 'undo that setting', 'reset all "
            "settings'):\n" + "\n".join(lines))


def related(source: str) -> list[Setting]:
    """The settings a piece of code reads (its source mentions config.<KEY>)."""
    return [s for s in SETTINGS if f"config.{s.key}" in (source or "")]
