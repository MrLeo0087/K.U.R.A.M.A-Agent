"""Read-mostly panels: health, status (+SSE stream), jobs, alerts, profile facts, tools.

LAPTOP-LOCAL: /status and /status/stream describe the machine the API runs on (CPU, RAM, processes)
and the jobs/alerts/workers in its local data/ folder. In a server split these move to the laptop agent.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import Any

from pydantic import BaseModel, Field
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from jarvis.api.routes.chat import SSE_HEADERS

router = APIRouter(prefix="/api/v1", tags=["info"])
API_VERSION = "1"


@router.get("/health", summary="Liveness (never needs the token)")
async def health(request: Request):
    st = request.app.state
    return {"ok": True, "version": API_VERSION, "auth": bool(st.settings.token),
            "agent_ready": st.engine.ready, "ts": time.time()}


@router.get("/status", summary="Laptop + KURAMA status snapshot (laptop-local)")
async def status(request: Request, percpu: bool = Query(False, description="include per-core CPU %")):
    return await run_in_threadpool(request.app.state.status.snapshot, percpu)


@router.get("/status/stream", summary="Status snapshots as Server-Sent Events (laptop-local)",
            description="One `data:` JSON snapshot every JARVIS_API_STATUS_INTERVAL seconds (default 2). "
                        "EventSource cannot send headers: pass ?token= when a token is set.")
async def status_stream(request: Request):
    st = request.app.state
    interval = st.settings.status_interval_s

    async def events():
        while not await request.is_disconnected():
            snap = await run_in_threadpool(st.status.snapshot)
            yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"
            await asyncio.sleep(interval)

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/slash", summary="Slash commands for the chat box suggestions (0 tokens)")
async def slash_commands():
    from jarvis.core import slash
    return {"commands": slash.catalog()}


@router.get("/jobs", summary="Background jobs (newest first)")
async def jobs(limit: int = Query(20, ge=1, le=200), status: str | None = Query(None, description="e.g. running")):
    from jarvis.core import store
    statuses = tuple(x.strip() for x in status.split(",") if x.strip()) if status else None
    rows = await run_in_threadpool(store.jobs_list, limit, statuses)
    keys = ("id", "title", "kind", "status", "progress", "created", "finished", "output_path", "error", "tokens")
    return {"jobs": [{k: r.get(k) for k in keys if k in r} for r in rows]}


@router.post("/jobs/{job_id}/cancel", summary="Cancel a background job running in this process")
async def job_cancel(job_id: int):
    from jarvis.core import jobs as jobs_mod
    job = await run_in_threadpool(jobs_mod.get_manager().cancel, job_id)
    if job is None:
        return JSONResponse({"ok": False, "error": "no such job"}, status_code=404)
    return {"ok": True, "id": job_id, "status": getattr(job, "status", None)}


@router.get("/alerts", summary="Recent alerts (newest first) + unread count")
async def alerts(limit: int = Query(20, ge=1, le=200)):
    from jarvis.core import store
    recent = await run_in_threadpool(store.alerts_recent, limit)
    unread = await run_in_threadpool(store.alerts_pending, 200)
    return {"unread": len(unread), "alerts": recent}


@router.post("/alerts/read", summary="Mark every alert as read")
async def alerts_read():
    from jarvis.core import store
    await run_in_threadpool(store.alerts_mark_announced, None, time.time() + 1)
    return {"ok": True}


@router.get("/profile", summary="Remembered personal facts")
async def profile():
    from jarvis.core import store
    rows = await run_in_threadpool(store.profile_all)
    return {"facts": [{k: r.get(k) for k in ("key", "value", "source", "updated")} for r in rows]}


def _tools() -> dict:
    from jarvis.core import registry
    reg = registry.REGISTRY
    out = []
    for g in reg.groups():
        items = [{"name": getattr(t, "name", "?"), "safety": registry.safety_of(t),
                  "description": (getattr(t, "description", "") or "").split("\n")[0][:160]}
                 for t in reg.schemas_for([g])]
        out.append({"group": g, "tools": sorted(items, key=lambda x: x["name"])})
    return {"groups": out, "count": sum(len(g["tools"]) for g in out)}


@router.get("/tools", summary="Tool groups -> tools -> safety level (info panel)",
            description="First call imports every tool module (a few hundred ms).")
async def tools():
    return await run_in_threadpool(_tools)


_wx_cache: dict = {}


def _weather_now(place: str) -> dict:
    """Current conditions for one place (Open-Meteo, free; cached WEATHER_CACHE_S)."""
    from jarvis.core import config
    from jarvis.tools.general import _geo

    hit = _wx_cache.get(place.lower())
    if hit and time.time() - hit[0] < config.WEATHER_CACHE_S:
        return hit[1]
    geo = _geo.geocode(place)
    if not geo:
        return {"place": place, "error": "not found"}
    cur = _geo.get_json("https://api.open-meteo.com/v1/forecast", {
        "latitude": geo["lat"], "longitude": geo["lon"], "timezone": "auto", "wind_speed_unit": "kmh",
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day",
    }).get("current", {})
    out = {"place": place.split(",")[0].strip(), "temp_c": cur.get("temperature_2m"),
           "feels_c": cur.get("apparent_temperature"), "humidity": cur.get("relative_humidity_2m"),
           "wind_kmh": cur.get("wind_speed_10m"), "code": cur.get("weather_code"),
           "desc": _geo.describe(cur.get("weather_code")), "is_day": bool(cur.get("is_day", 1))}
    _wx_cache[place.lower()] = (time.time(), out)
    return out


@router.get("/weather", summary="Current weather for the UI card (default: config.UI_WEATHER_PLACES)")
async def weather_now(place: str = Query("", description="city, e.g. 'Nepalgunj, Nepal'")):
    from jarvis.core import config

    places = [place] if place.strip() else list(config.UI_WEATHER_PLACES)

    def run():
        res = []
        for p in places:
            try:
                res.append(_weather_now(p.strip()))
            except Exception as e:  # network down: the card just shows "--"
                res.append({"place": p.split(",")[0].strip(), "error": type(e).__name__})
        return res
    return {"items": await run_in_threadpool(run)}


# ---------- workspace: finished outputs (essays, poems, code, images) under data/outputs ----------
_IMG = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_TXT = {".md", ".txt", ".py", ".json", ".csv", ".html", ".js", ".sh"}
_AUDIO = {".mp3", ".wav", ".ogg", ".m4a"}
_VIDEO = {".mp4", ".webm"}


def _outputs_dir():
    from jarvis.core import config
    return config.OUTPUTS_DIR.resolve()


@router.get("/outputs", summary="Newest finished outputs for the workspace panel")
async def outputs(limit: int = Query(12, ge=1, le=100)):
    def run():
        root = _outputs_dir()
        if not root.is_dir():
            return []
        files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in _IMG | _TXT | _AUDIO | _VIDEO
                 and not p.name.startswith((".", "bench-"))]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        def kind(p):
            x = p.suffix.lower()
            return "image" if x in _IMG else "audio" if x in _AUDIO else "video" if x in _VIDEO else "text"
        return [{"name": str(p.relative_to(root)), "kind": kind(p),
                 "mtime": p.stat().st_mtime, "size": p.stat().st_size} for p in files[:limit]]
    return {"items": await run_in_threadpool(run)}


def _trash(p, root) -> None:
    """Desktop trash (restorable), else data/outputs_trash/<time>/ - never a hard delete."""
    import shutil
    import subprocess
    import time as _t
    gio = shutil.which("gio")
    if gio and subprocess.run([gio, "trash", str(p)], capture_output=True, timeout=30).returncode == 0:
        return
    dest = root.parent / "outputs_trash" / _t.strftime("%Y%m%d-%H%M%S")
    dest.mkdir(parents=True, exist_ok=True)
    shutil.move(str(p), str(dest / p.name))


@router.post("/outputs/clear", summary="Clean the workspace: move every output to the trash (restorable)")
async def outputs_clear():
    def run():
        root = _outputs_dir()
        if not root.is_dir():
            return 0
        items = [p for p in root.iterdir() if not p.name.startswith(".")]
        for p in items:
            _trash(p, root)
        return len(items)
    n = await run_in_threadpool(run)
    return {"ok": True, "moved": n}


# ---------- memory: what KURAMA's parts use, and the switch for the local understanding model ----------
def _kurama_parts() -> list[dict]:
    """Memory (MB) and CPU (% of one core, measured over 0.4 s) for each part of KURAMA."""
    import time as _t
    import psutil
    names = (("jarvis.server", "Server (backend)"), ("jarvis.workers", "Background workers"),
             ("jarvis.core.memory", "Understanding model"), ("kurama_wallpaper", "Screen (dashboard / mini)"),
             ("WebKitWebProcess", "Screen pages"), ("WebKitNetworkProcess", "Screen pages"),
             ("wifi_share_server", "Wi-Fi share"), ("yt_dlp", "Video download"), ("dbus-monitor", "Message watcher"))
    procs: list[tuple[str, psutil.Process]] = []
    for p in psutil.process_iter(["cmdline"]):
        argv = p.info.get("cmdline") or []
        if not argv or "-c" in argv or argv[0].endswith(("bash", "sh", "zsh")):  # shells / one-off scripts quoting a name
            continue
        cmd = " ".join(argv)
        for key, label in names:
            if key in cmd:
                procs.append((label, p))
                with contextlib.suppress(psutil.Error):
                    p.cpu_percent(None)  # start the measurement
                break
    _t.sleep(0.4)
    cores = psutil.cpu_count() or 1
    parts: dict[str, dict] = {}
    for label, p in procs:
        with contextlib.suppress(psutil.Error):
            d = parts.setdefault(label, {"name": label, "mb": 0, "cpu": 0.0, "procs": 0})
            d["mb"] += round(_pss(p) / 1048576)
            # % of the WHOLE laptop (all cores), not of one core: 117 % of one core = ~10 % of 12 cores
            d["cpu"] = round(d["cpu"] + p.cpu_percent(None) / cores, 1)
            d["procs"] += 1
    return sorted(parts.values(), key=lambda d: -d["mb"])


def _pss(p) -> int:
    """Proportional memory: shared libraries are split between the processes using them (RSS counts them in
    full for every process, which made KURAMA look ~30 % bigger than it is)."""
    try:
        with open(f"/proc/{p.pid}/smaps_rollup") as f:
            for line in f:
                if line.startswith("Pss:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return p.memory_info().rss


@router.get("/resources", summary="Memory used by KURAMA's parts + the understanding model's mode")
async def resources():
    from jarvis.core import semantic
    import psutil
    parts = await run_in_threadpool(_kurama_parts)
    total = sum(p["mb"] for p in parts)
    ram = psutil.virtual_memory().total / 1048576
    return {"parts": parts, "total_mb": total, "total_cpu": round(sum(p["cpu"] for p in parts), 1),
            "ram_share": round(100 * total / ram, 1), "semantic": semantic.status()}


class ResourceMode(BaseModel):
    semantic_mode: str = Field(..., description="always | auto | off")


@router.post("/resources", summary="Choose how the local understanding model runs (always / auto / off)")
async def resources_set(body: ResourceMode):
    from jarvis.core import modes, semantic
    try:
        if body.semantic_mode not in semantic.MODES:
            raise ValueError(f"mode must be one of {semantic.MODES}")
        modes.set_switch("model", body.semantic_mode)  # part of the power mode
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    return {"ok": True, "semantic": semantic.status()}


@router.post("/resources/free", summary="Free the understanding model's memory now (it reloads when needed)")
async def resources_free():
    from jarvis.core import semantic
    await run_in_threadpool(semantic.free_now)
    return {"ok": True, "semantic": semantic.status()}


class OutputName(BaseModel):
    name: str = Field(..., max_length=300)


@router.post("/outputs/delete", summary="Remove ONE workspace item (to the trash, restorable)")
async def outputs_delete(body: OutputName):
    root = _outputs_dir()
    p = (root / body.name).resolve()
    if root not in p.parents or not p.is_file():
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    await run_in_threadpool(_trash, p, root)
    return {"ok": True}


@router.get("/outputs/file", summary="One output file (text or image); only paths inside data/outputs")
async def output_file(name: str = Query(..., max_length=300)):
    from fastapi.responses import FileResponse

    root = _outputs_dir()
    p = (root / name).resolve()
    if root not in p.parents or not p.is_file() or p.suffix.lower() not in _IMG | _TXT | _AUDIO | _VIDEO:
        return JSONResponse({"error": "not found"}, status_code=404)
    media = "text/plain; charset=utf-8" if p.suffix.lower() in _TXT else None  # images/audio/video: by extension
    return FileResponse(p, media_type=media, headers={"Cache-Control": "no-cache"})


# ---------- desktop wallpaper: the UI draws it behind the dashboard (the KURAMA window covers the real desktop) ----------
def _wallpaper_path():
    from jarvis.tools.general import set_wallpaper
    p = set_wallpaper.current()
    return p if p and p.is_file() and p.suffix.lower() in _IMG else None


@router.get("/wallpaper/info", summary="Current desktop wallpaper (mtime changes when it changes)")
async def wallpaper_info():
    p = await run_in_threadpool(_wallpaper_path)
    ours = bool(p) and _outputs_dir() in p.resolve().parents  # a picture KURAMA made: the UI shows it behind the panels
    return {"set": bool(p), "kurama": ours, "name": p.name if p else "", "mtime": p.stat().st_mtime if p else 0}


@router.get("/wallpaper", summary="The current desktop wallpaper image")
async def wallpaper():
    from fastapi.responses import FileResponse
    p = await run_in_threadpool(_wallpaper_path)
    if not p:
        return JSONResponse({"error": "no wallpaper image"}, status_code=404)
    return FileResponse(p, headers={"Cache-Control": "max-age=86400"})


def _real_wallpaper():
    """The user's OWN desktop picture (saved by the screen app before it shows its snapshot there), else the current one."""
    import json as _json
    from pathlib import Path as _P
    try:
        d = _json.loads((_P.home() / ".local/share/kurama/real-wallpaper.json").read_text(encoding="utf-8"))
        uri = d.get("picture-uri-dark") or d.get("picture-uri") or ""
        q = _P(uri.removeprefix("file://")) if uri.startswith("file://") else None
        if q and q.is_file() and "kurama" not in str(q):
            return q
    except (OSError, ValueError):
        pass
    return _wallpaper_path()


@router.get("/wallpaper/real", summary="The user's own desktop picture (the dashboard background)")
async def wallpaper_real():
    from fastapi.responses import FileResponse
    p = await run_in_threadpool(_real_wallpaper)
    if not p:
        return JSONResponse({"error": "no wallpaper image"}, status_code=404)
    head = p.open("rb").read(12)
    kind = "image/png" if head.startswith(b"\x89PNG") else "image/webp" if head[8:12] == b"WEBP" else "image/jpeg"
    return FileResponse(p, media_type=kind, headers={"Cache-Control": "max-age=3600"})


# ---------- this laptop (dashboard card): Wi-Fi, volume, brightness, battery health, next reminder ----------
@router.get("/device", summary="This laptop at a glance (cached 15 s)")
async def device_info():
    from jarvis.api import device
    return await run_in_threadpool(device.info)


# ---------- "Today" card: reminders, alarms, timers and the stopwatch ----------
@router.get("/schedule", summary="Upcoming reminders, alarms, timers + the stopwatch (dashboard 'Today' card)")
async def schedule():
    def build() -> dict:
        import json as _json
        from datetime import datetime

        from jarvis.core import store, when
        now = datetime.now()
        items = []
        for r in store.schedules_list(enabled_only=True, limit=60):
            if not r.get("next_run"):
                continue
            d = datetime.fromtimestamp(r["next_run"])
            days = (d.date() - now.date()).days
            items.append({"id": r["id"], "kind": r.get("kind") or "reminder", "text": r["text"], "at": r["next_run"],
                          "repeat": r.get("repeat") or "none", "day": "today" if days <= 0 else "tomorrow" if days == 1 else "later",
                          "desc": when.describe(r["next_run"], r.get("repeat") or "none", now)})
        sw = _json.loads(store.kv_get("stopwatch", "") or "{}") or {}
        return {"now": now.timestamp(), "items": items,
                "stopwatch": {"running_since": sw.get("run"), "elapsed": sw.get("acc", 0.0), "laps": sw.get("laps", [])}}
    return await run_in_threadpool(build)


@router.delete("/schedule/{sched_id}", summary="Cancel a reminder / alarm / timer")
async def schedule_cancel(sched_id: int):
    from jarvis.core import store
    ok = await run_in_threadpool(store.schedule_delete, sched_id)
    return {"ok": bool(ok)} if ok else JSONResponse({"ok": False, "error": "no such item"}, status_code=404)


@router.post("/stopwatch/{action}", summary="Stopwatch: start / stop / lap / reset")
async def stopwatch_action(action: str):
    from jarvis.tools.general.stopwatch import stopwatch
    if action not in ("start", "stop", "lap", "reset", "status"):
        return JSONResponse({"error": "unknown action"}, status_code=400)
    return {"text": await run_in_threadpool(stopwatch, action)}


# ---------- greeting: the first dashboard load after KURAMA starts says hello (once per start) ----------
_greeted = {"done": False}


@router.get("/greeting", summary="A spoken hello, only on the first call after KURAMA starts")
async def greeting():
    if _greeted["done"]:
        return {"text": ""}
    _greeted["done"] = True
    from jarvis.core import brief
    if brief.due():  # the first screen of the day: the morning brief instead of a plain hello
        text = await run_in_threadpool(brief.deliver, "screen")
        if text:
            brief.take_pending()
            return {"text": text, "brief": True}

    def build() -> str:  # short and natural: a different hello each time (jarvis/core/phrases.py)
        from jarvis.core import phrases
        return phrases.greeting()
    try:
        return {"text": await run_in_threadpool(build)}
    except Exception as e:  # a greeting must never break the page
        return {"text": "", "error": str(e)[:120]}


@router.get("/brief", summary="The morning brief waiting to be spoken (once), '' if none")
async def brief_pending():
    from jarvis.core import brief
    return {"text": await run_in_threadpool(brief.take_pending)}


@router.get("/money", summary="Numbers for the Money card")
async def money_card():
    from jarvis.core import expenses
    return await run_in_threadpool(expenses.dashboard)


class Duck(BaseModel):
    on: bool


@router.post("/music/duck", summary="Lower KURAMA's music while it listens or speaks (back up with on=false)")
async def music_duck(body: Duck):
    from jarvis.core import music
    return {"ok": await run_in_threadpool(music.duck, body.on)}


@router.get("/suggest", summary="Random suggestions for the chat box, weighted by what you're doing (0 tokens)")
async def suggestions(n: int = Query(4, ge=1, le=8)):
    from jarvis.core import suggest
    return {"items": await run_in_threadpool(suggest.pick, n)}


@router.get("/money/range", summary="Money window: rows + totals from one date to another (YYYY-MM-DD)")
async def money_range(start: str = Query(..., max_length=10), end: str = Query("", max_length=10),
                      category: str = Query("", max_length=30)):
    from jarvis.core import expenses
    try:
        return await run_in_threadpool(expenses.range_data, start, end, category)
    except ValueError:
        return JSONResponse({"error": "dates must look like 2026-10-27"}, status_code=400)


@router.get("/habits", summary="Habits with today's progress, streaks and the last 7 days")
async def habits_card():
    from jarvis.core import habits
    return {"habits": await run_in_threadpool(habits.overview)}


class Tracked(BaseModel):
    kind: str = Field(..., description="expense_delete | habit_done | habit_undo")
    ref: str = Field("", description="row number or habit name")


@router.post("/tracker", summary="Dashboard buttons: delete an expense row, check in / undo a habit (0 tokens)")
async def tracker_action(body: Tracked):
    from jarvis.core import expenses, habits
    fn = {"expense_delete": lambda: expenses.delete(body.ref),
          "habit_done": lambda: habits.check_in(body.ref) or f"No habit called {body.ref!r}.",
          "habit_undo": lambda: habits.undo(body.ref)}.get(body.kind)
    if fn is None:
        return JSONResponse({"ok": False, "error": "unknown kind"}, status_code=400)
    text = await run_in_threadpool(fn)
    from jarvis.api.routes import dash
    for k in ("summary", "tracker"):
        dash._cache.pop(k, None)
    return {"ok": True, "text": text}


# ---------- power switch: stop every KURAMA process (scripts/kurama-power.sh; Super+K turns it back on) ----------
@router.post("/power/off", summary="Turn KURAMA off completely (0 RAM / 0 CPU until turned on again)")
async def power_off():
    import subprocess

    from jarvis.api.settings import ROOT
    # detached and a moment later, so this reply gets out before the server itself is stopped
    subprocess.Popen(["bash", "-c", "sleep 0.6; exec scripts/kurama-power.sh off"], cwd=str(ROOT),
                     start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
    return {"ok": True, "message": "KURAMA is turning off. Press Super+K or click the KURAMA app to turn it on."}


# ---------- assistant name (default KURAMA; the user can change it) ----------
@router.get("/identity", summary="The assistant's current name")
async def identity_get():
    from jarvis.core import identity
    return {"name": await run_in_threadpool(identity.name)}


@router.post("/identity", summary="Rename the assistant (it answers to the new name from now on)")
async def identity_set(request: Request):
    from jarvis.core import identity
    body = await request.json()
    new = await run_in_threadpool(identity.set_name, str(body.get("name", "")))
    if not new:
        return JSONResponse({"ok": False, "error": "use 2-24 letters, one or two words"}, status_code=400)
    return {"ok": True, "name": new}


# ---------- power modes: how much of KURAMA runs (RAM / CPU / tokens) ----------
class PowerMode(BaseModel):
    mode: str | None = Field(None, description="a preset: full | smart | balanced | basic | light | laptop | noai")
    key: str | None = Field(None, description="one switch instead: workers | model | ai | wake | screen")
    value: Any = Field(None, description="the switch's value (workers: {name: true/false})")


@router.get("/modes", summary="KURAMA power modes: the current switches, the presets, the helpers")
async def modes_get():
    from jarvis.core import modes
    return modes.summary()


@router.post("/modes", summary="Choose a power mode, or change one switch (the mode becomes custom)")
async def modes_set(body: PowerMode):
    from jarvis.core import modes
    try:
        if body.mode:
            await run_in_threadpool(modes.set_mode, body.mode)
        elif body.key:
            await run_in_threadpool(modes.set_switch, body.key, body.value)
        else:
            raise ValueError("send a mode or a key + value")
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    return {"ok": True, **modes.summary()}
