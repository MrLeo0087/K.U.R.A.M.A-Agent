"""Startup greeting for voice mode: time of day + a weather one-liner + running jobs / saved notes.
A template only (zero LLM tokens); built and spoken in a background thread so the hotkey is ready
at once. Disable with config.GREETING=False (env JARVIS_GREETING=0)."""
from __future__ import annotations

import logging
import re
import threading
from datetime import datetime
from typing import Callable

from jarvis.core import config

log = logging.getLogger("jarvis.greeting")

_WEATHER = re.compile(r"^(?P<where>[^:,]+)[^:]*: (?P<t>-?\d+)°C(?:, feels like [^,]+,| and) (?P<desc>[^.]+)\.")


def part_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "Good morning"
    if 12 <= hour < 17:
        return "Good afternoon"
    if 17 <= hour < 22:
        return "Good evening"
    return "Hello, working late"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def weather_line(weather_fn: Callable[[str], str] | None = None) -> str:
    """'It's 24°C and partly cloudy in Kathmandu.' or '' on any failure."""
    try:
        if weather_fn is None:
            from jarvis.tools.general.weather import weather as weather_fn  # noqa: N813
        out = weather_fn("")
    except Exception as e:  # offline etc.: just skip the weather
        log.info("greeting weather skipped: %s", e)
        return ""
    m = _WEATHER.match(out or "")
    if not m:
        return ""
    return f"It's {m.group('t')}°C and {m.group('desc')} in {m.group('where').strip()}."


def counts() -> tuple[int, int]:
    """(running/queued jobs, saved notes); zeros on error."""
    jobs_n = notes_n = 0
    try:
        from jarvis.core import jobs
        jobs_n = len(jobs.get_manager().active())
    except Exception as e:
        log.info("greeting jobs count skipped: %s", e)
    try:
        from jarvis.core import store
        notes_n = store.notes_count()
    except Exception as e:
        log.info("greeting notes count skipped: %s", e)
    return jobs_n, notes_n


def build(now: datetime | None = None, weather_fn: Callable[[str], str] | None = None,
          jobs_n: int | None = None, notes_n: int | None = None) -> str:
    now = now or datetime.now()
    name = ""
    try:
        from jarvis.core import profile
        name = profile.user_name()
    except Exception as e:  # the greeting must never fail
        log.info("greeting name skipped: %s", e)
    hello = f"{part_of_day(now.hour)}, {name}" if name else part_of_day(now.hour)
    parts = [f"{hello}, it's {now.strftime('%I:%M %p').lstrip('0')}."]
    if config.GREETING_WEATHER and (w := weather_line(weather_fn)):
        parts.append(w)
    if jobs_n is None or notes_n is None:
        j, n = counts()
        jobs_n = j if jobs_n is None else jobs_n
        notes_n = n if notes_n is None else notes_n
    extra = []
    if jobs_n:
        extra.append(f"{_plural(jobs_n, 'job')} running")
    if notes_n:
        extra.append(f"{_plural(notes_n, 'saved note')}")
    if extra:
        parts.append("You have " + " and ".join(extra) + ".")
    parts.append("Ready when you are.")
    return " ".join(parts)


def start(say: Callable[[str], None], **build_kw) -> threading.Thread | None:
    """Build and speak the greeting in a daemon thread (never blocks startup)."""
    if not config.GREETING:
        return None

    def run() -> None:
        try:
            say(build(**build_kw))
        except Exception as e:  # a greeting failure must never break voice mode
            log.warning("greeting failed: %s", e)

    t = threading.Thread(target=run, name="greeting", daemon=True)
    t.start()
    return t
