"""Auto dark/light logic (not a tool), shared by the auto_theme tool and worker.

Times: sunrise/sunset for the home city (Open-Meteo, cached per day in memory and kv) when
config.AUTO_THEME_SOURCE == "sun", else (or on any error) config.AUTO_THEME_TIMES.
Only transitions act: the key of the latest passed transition ("2026-10-23:sunset") is stored in kv;
a manual theme change is left alone until the next transition changes that key.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time as dtime, timedelta

from jarvis.core import config, store

KV_ENABLED = "auto_theme"
KV_LAST = "auto_theme_last"
KV_SUN = "auto_theme_sun"
_sun: dict[str, tuple[dtime, dtime]] = {}


def enabled() -> bool:
    v = store.kv_get(KV_ENABLED)
    return config.AUTO_THEME if v is None else v == "on"


def set_enabled(on: bool) -> None:
    store.kv_set(KV_ENABLED, "on" if on else "off")
    if not on:
        store.kv_set(KV_LAST, "")


def _hm(s: str) -> dtime:
    hh, mm = (int(x) for x in s.strip().split(":")[:2])
    return dtime(hh, mm)


def fixed_times() -> tuple[dtime, dtime]:
    try:
        return _hm(config.AUTO_THEME_TIMES[0]), _hm(config.AUTO_THEME_TIMES[1])
    except (ValueError, IndexError, TypeError):
        return dtime(7, 0), dtime(18, 30)


def fetch_sun(day: date) -> tuple[dtime, dtime]:
    """Home-city sunrise/sunset (local clock of that city) via Open-Meteo; raises on failure."""
    from jarvis.core import profile
    from jarvis.tools.general import _geo

    geo = _geo.geocode(profile.home_place())
    if not geo:
        raise LookupError("home city not found")
    data = _geo.get_json("https://api.open-meteo.com/v1/forecast", {
        "latitude": geo["lat"], "longitude": geo["lon"], "daily": "sunrise,sunset",
        "timezone": "auto", "start_date": day.isoformat(), "end_date": day.isoformat()})
    d = data["daily"]
    return (datetime.fromisoformat(d["sunrise"][0]).time().replace(second=0, microsecond=0),
            datetime.fromisoformat(d["sunset"][0]).time().replace(second=0, microsecond=0))


def times_for(day: date) -> tuple[dtime, dtime]:
    if config.AUTO_THEME_SOURCE != "sun":
        return fixed_times()
    key = day.isoformat()
    if key in _sun:
        return _sun[key]
    try:
        cached = json.loads(store.kv_get(KV_SUN) or "{}")
        if cached.get("date") == key:
            t = (_hm(cached["sunrise"]), _hm(cached["sunset"]))
        else:
            t = fetch_sun(day)
            store.kv_set(KV_SUN, json.dumps({"date": key, "sunrise": t[0].strftime("%H:%M"),
                                             "sunset": t[1].strftime("%H:%M")}))
    except Exception:
        t = fixed_times()  # offline: fixed times today, retry the network tomorrow
    _sun.clear()
    _sun[key] = t
    return t


def period(now: datetime, times: tuple[dtime, dtime] | None = None) -> tuple[str, str]:
    """(mode wanted now, key of the latest passed transition)."""
    sunrise, sunset = times or times_for(now.date())
    t = now.time()
    if t < sunrise:
        return "dark", f"{(now.date() - timedelta(days=1)).isoformat()}:sunset"
    if t < sunset:
        return "light", f"{now.date().isoformat()}:sunrise"
    return "dark", f"{now.date().isoformat()}:sunset"


def _switch(mode: str) -> str:
    from jarvis.tools.general.set_theme import set_theme  # lazy: only on a transition
    return set_theme(mode)


def check(now: datetime | None = None, switch=None) -> str | None:
    """One tick: switch the theme if a new transition has passed. Returns the result text or None."""
    if not enabled():
        return None
    now = now or datetime.now()
    mode, key = period(now)
    if store.kv_get(KV_LAST) == key:
        return None
    out = (switch or _switch)(mode)
    if not str(out).lower().startswith("error"):
        store.kv_set(KV_LAST, key)
    return out
