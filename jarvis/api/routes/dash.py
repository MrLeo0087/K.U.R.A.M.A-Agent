"""Dashboard panels (laptop-local): one cheap summary for the cards, details when a card is clicked, a fuller
forecast, and a few direct actions (open in VS Code, show in folder, send to phone, quick switches).

Everything heavier (free RAM, stop a process, stop training, clean the disk, install...) is NOT here: the page sends
those as normal chat requests, so they go through the same tools, confirmations and logs as when you ask by voice.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1", tags=["dashboard"])
_cache: dict[str, tuple[float, dict]] = {}


def _cached(key: str, ttl: float, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def _ago(t: float | None) -> str:
    if not t:
        return ""
    d = max(0, time.time() - float(t))
    return "now" if d < 60 else f"{int(d // 60)}m" if d < 3600 else f"{int(d // 3600)}h" if d < 86400 else f"{int(d // 86400)}d"


# ---------------------------------------------------------------- summary pieces
def _apps() -> dict:
    from jarvis.core import doctor
    apps = doctor.memory_by_app(6)
    ks = doctor.idle_kernels()
    return {"apps": [{"name": a, "bytes": b, "procs": n} for a, b, n in apps],
            "idle_kernels": {"count": len(ks), "mb": round(sum(k[1] for k in ks))}}


def _coding() -> dict:
    from jarvis.core import store, timemachine as tm
    try:
        p = tm.resolve("")
    except tm.TMError:
        return {}
    out: dict = {"project": p.name, "path": str(p)}
    git = lambda *a: subprocess.run(["git", "-C", str(p), *a], capture_output=True, text=True, timeout=10).stdout  # noqa: E731
    if (p / ".git").exists():
        out["branch"] = git("rev-parse", "--abbrev-ref", "HEAD").strip()
        out["changed"] = len([ln for ln in git("status", "--porcelain").splitlines() if ln.strip()])
        m = re.findall(r"(\d+) (insertion|deletion)", git("diff", "HEAD", "--shortstat"))
        out["ins"] = int(next((n for n, k in m if k == "insertion"), 0))
        out["dels"] = int(next((n for n, k in m if k == "deletion"), 0))
        files = []
        for ln in git("diff", "HEAD", "--numstat").splitlines():
            a, d, f = (ln.split("\t") + ["", "", ""])[:3]
            files.append({"file": f, "ins": a, "dels": d})
        files += [{"file": f, "ins": "new", "dels": ""} for f in git("ls-files", "--others", "--exclude-standard").splitlines()]
        out["files"] = sorted(files, key=lambda x: -(int(x["ins"]) if x["ins"].isdigit() else 0))[:6]
        ct = git("log", "-1", "--format=%ct").strip()
        out["last_commit"] = _ago(float(ct)) if ct else ""
    out["snapshot"] = _ago(float(store.kv_get(f"tm_last:{p}") or 0))
    rows = store._exec("SELECT error, where_, count, fix, last_seen FROM errors ORDER BY last_seen DESC LIMIT 1")
    if rows and time.time() - rows[0]["last_seen"] < 3 * 86400:
        r = rows[0]
        out["error"] = {"text": r["error"][:140], "where": r["where_"], "count": r["count"], "fix": r["fix"],
                        "ago": _ago(r["last_seen"])}
    return out


def _now() -> list[dict]:
    from jarvis.core import store, training
    items: list[dict] = []
    for w in store.watches_list(("active",)):
        st = w["state"]
        if w["kind"] in training.KINDS:
            m = st.get("metrics") or {}
            frac = (m.get("epoch") or 0) / m["epochs"] if m.get("epochs") else None
            items.append({"kind": "train", "id": w["id"], "title": w["label"] + (" (Colab)" if w["kind"] == "colab" else ""),
                          "sub": training.progress_text(st) or "running", "progress": frac,
                          "right": training.eta_text(st).replace("~", "").replace(" left", "") or _ago(st.get("started"))})
        elif w["kind"] == "dl":
            path = Path(st.get("path") or Path(st["folder"]) / w["label"])
            mb = path.stat().st_size / 1e6 if path.exists() else 0
            started = bool(st.get("pid"))
            items.append({"kind": "download", "id": w["id"], "title": w["label"],
                          "sub": f"{mb:.0f} MB so far" if started else time.strftime("starts %H:%M", time.localtime(st["start_at"])),
                          "right": ""})
        elif w["kind"] == "web":
            items.append({"kind": "web", "id": w["id"], "title": f"Watching {w['label']}",
                          "sub": f"{st.get('changes', 0)} change(s)", "right": f"{float(st.get('every', 3600)) / 60:.0f} min"})
    for j in store.jobs_list(4, ("queued", "running")):
        items.append({"kind": "job", "id": j["id"], "title": j["title"][:60], "sub": j.get("progress") or j["status"],
                      "right": f"#{j['id']}"})
    from jarvis.core import guard, lecture
    if lecture.recording():
        stt = lecture.state()
        items.append({"kind": "record", "title": f"Recording: {stt['title']}", "sub": "say 'stop the recording'",
                      "right": f"{int((time.time() - stt['start']) / 60)} min"})
    if guard.armed():
        items.append({"kind": "guard", "title": "Laptop guard on", "sub": "photo + location if someone uses it", "right": ""})
    return items


def _today_chips() -> list[dict]:
    from datetime import datetime
    from jarvis.core import study
    now = datetime.now()
    chips = []
    for c in study.day_list(now):
        chips.append({"time": c["start"], "text": c["subject"], "kind": "class",
                      "next": datetime.combine(now.date(), datetime.strptime(c["start"], "%H:%M").time()) > now})
    # (today's reminders, alarms and timers come from /schedule on the page: it has their ids for live countdowns)
    chips.sort(key=lambda c: c["time"])
    seen_next = False
    for c in chips:  # only the first upcoming one is highlighted
        c["next"], seen_next = bool(c["next"] and not seen_next), seen_next or bool(c["next"])
    return chips[:6]


def _kurama() -> dict:
    from jarvis.core import store
    start = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
    tok = store._exec("SELECT COALESCE(SUM(total_tokens),0) t, COUNT(*) n FROM llm_calls WHERE ts >= ? AND purpose != 'stt'",
                      (start,))[0]
    fast = store._exec("SELECT COUNT(*) FROM routing WHERE ts >= ? AND method = 'fastpath'", (start,))[0][0]
    turns = store._exec("SELECT COUNT(*) FROM messages WHERE ts >= ? AND role = 'user'", (start,))[0][0]
    try:
        from jarvis.workers import status
        ws = (status.read() or {}).get("workers") or {}
        running = sum(1 for w in ws.values() if w.get("state") == "running")
        total = len(ws)
    except Exception:
        running, total = 0, 0
    return {"tokens_today": int(tok["t"]), "calls_today": int(tok["n"]),
            "free_pct": round(100 * fast / turns) if turns else None, "workers": [running, total]}


def _switches() -> dict:
    from jarvis.core import guard
    from jarvis.tools.general import _desk

    def run(*a):
        try:
            return subprocess.run(list(a), capture_output=True, text=True, timeout=3).stdout
        except (OSError, subprocess.SubprocessError):
            return ""
    rf = run("rfkill", "list", "bluetooth")
    mode = run("powerprofilesctl", "get").strip()
    return {"wifi": run("nmcli", "radio", "wifi").strip() == "enabled",
            "bluetooth": bool(rf) and "Soft blocked: no" in rf,
            "dnd": _desk.gs_get(_desk.NOTIF, "show-banners") == "false",
            "night": _desk.gs_get(_desk.COLOR, "night-light-enabled") == "true",
            "guard": guard.armed(), "saver": mode == "power-saver", "power_mode": mode or "unknown"}


def _todo_rows() -> list[dict]:
    from jarvis.core import todos
    todos.ensure_migrated()
    return [{"id": r["id"], "title": r["title"][:120], "due": r["due_text"], "late": r["due_text"].startswith("overdue"),
             "priority": r["priority"], "tag": r["tag"], "bell": bool(r["reminder_id"])} for r in todos.items()]


def _reminder_rows() -> list[dict]:
    from jarvis.core import store, when
    return [{"id": s["id"], "kind": s.get("kind") or "reminder", "text": s["text"][:120],
             "when": when.describe(s["next_run"], s.get("repeat") or "none")}
            for s in store.schedules_list(enabled_only=True, limit=50) if s.get("kind") in ("reminder", "alarm")]


def _work() -> dict:
    """Goals + the to-do list (tasks) + counts of reminders and the reading list, for the Work card."""
    from jarvis.core import goals, readlater, todos
    rows = _todo_rows()
    c = todos.summary_counts()
    nxt = next((r for r in rows if r["due"]), None)
    return {"goals": goals.cards(), "items": rows[:6],
            "list": {"todo": c["open"], "today": c["today"], "overdue": c["overdue"], "reminders": len(_reminder_rows()),
                     "read": len(readlater.ordered()), "next": {"title": nxt["title"][:60], "due": nxt["due"]} if nxt else None}}


def _tracker() -> dict:
    """Money & habits card: this month's money and every habit's week."""
    from jarvis.core import expenses, habits
    return {"money": expenses.dashboard(), "habits": habits.overview()}


def summary() -> dict:
    def safe(fn, default):
        try:
            return fn()
        except Exception as e:
            return {**(default if isinstance(default, dict) else {}), "error": type(e).__name__} \
                if isinstance(default, dict) else default
    return {"apps": safe(_apps, {}), "coding": safe(_coding, {}), "work": _cached("work", 20, lambda: safe(_work, {})), "now": safe(_now, []), "today": safe(_today_chips, []),
            "kurama": safe(_kurama, {}), "switches": _cached("switches", 15, lambda: safe(_switches, {})),
            "tracker": _cached("tracker", 30, lambda: safe(_tracker, {}))}


class TodoIn(BaseModel):
    action: str  # done | remove
    type: str = "todo"  # todo | reminder | read
    id: int = 0  # to-do / reminder id
    title: str = ""  # reading-list links (the sheet has no ids)


@router.post("/todo", summary="Card buttons: finish or delete a to-do, cancel a reminder, mark a link read (0 tokens)")
async def todo_action(body: TodoIn):
    from jarvis.core import readlater, store, todos

    def run() -> dict:
        if body.type == "reminder":
            s = store.schedule_get(body.id)
            if not s or not s.get("enabled"):
                return {"ok": False, "text": "That reminder isn't pending any more."}
            store.schedule_update(body.id, enabled=0, note="cancelled")
            text = f"Cancelled: {s['text']}"
        elif body.type == "read":
            r = next((x for x in readlater.ordered() if x["title"] == body.title), None)
            if r is None:
                return {"ok": False, "text": "It's not in your reading list any more."}
            readlater._drop(r)
            text = f"Removed: {r['title']}"
        else:
            r = todos.by_id(body.id)
            if r is None:
                return {"ok": False, "text": "It's not on your to-do list any more."}
            text = todos.done("", r) if body.action == "done" else todos.remove("", r)
        _cache.pop("summary", None)
        _cache.pop("work", None)
        return {"ok": True, "text": text}
    return await run_in_threadpool(run)


@router.get("/dashboard", summary="Everything the dashboard cards show (cached 8 s; ?fresh=1 right after a chat turn)")
async def dashboard(fresh: bool = False):
    if fresh:  # the turn may have changed the to-do list / long tasks / reminders: never show the old ones
        for k in ("summary", "work", "tracker"):
            _cache.pop(k, None)
    return await run_in_threadpool(lambda: _cached("summary", 8, summary))


# ---------------------------------------------------------------- details (click a card)
def detail(panel: str) -> dict:
    from jarvis.core import store
    if panel == "apps":
        from jarvis.core import doctor
        r = doctor.check()
        return {"apps": [{"name": a, "bytes": b, "procs": n} for a, b, n in doctor.memory_by_app(10)],
                "findings": r.findings, "facts": r.facts,
                "ports": [{"port": p, "pid": pid, "name": n} for p, pid, n in doctor.listeners()[:12]],
                "kernels": [{"pid": k[0], "mb": round(k[1])} for k in doctor.idle_kernels()]}
    if panel == "work":  # the Work sheet: goals + to-do + reminders + reading list + coding
        from jarvis.core import readlater
        w = _work()
        w["items"] = _todo_rows()
        w["reminders"] = _reminder_rows()
        w["reads"] = [{k: r.get(k, "") for k in ("title", "link", "tag", "due")} for r in readlater.ordered()[:30]]
        try:
            w["coding"] = detail("coding")
        except Exception as e:
            w["coding"] = {"error": type(e).__name__}
        return w
    if panel == "coding":
        from jarvis.core import timemachine as tm
        c = _coding()
        if not c:
            return {}
        p = Path(c["path"])
        files = []
        if (p / ".git").exists():
            num = subprocess.run(["git", "-C", str(p), "diff", "HEAD", "--numstat"], capture_output=True, text=True,
                                 timeout=10).stdout
            for ln in num.splitlines()[:40]:
                a, d, f = (ln.split("\t") + ["", "", ""])[:3]
                files.append({"file": f, "ins": a, "dels": d})
            new = subprocess.run(["git", "-C", str(p), "ls-files", "--others", "--exclude-standard"], capture_output=True,
                                 text=True, timeout=10).stdout.splitlines()
            files += [{"file": f, "ins": "new", "dels": ""} for f in new[:20]]
        snaps = []
        try:
            snaps = tm.history(p, n=8).split("\n")[1:]
        except tm.TMError:
            pass
        errs = [dict(r) for r in store._exec("SELECT error, where_, count, fix, last_seen FROM errors ORDER BY last_seen "
                                             "DESC LIMIT 6")]
        for e in errs:
            e["ago"] = _ago(e.pop("last_seen"))
        return {**c, "files": files, "snapshots": snaps, "errors": errs,
                "projects": [{"name": q.name, "path": str(q)} for q in tm.projects()][:20]}
    if panel == "now":
        from jarvis.core import overview
        return {"now": _now(), "today": _today_chips(), "text": overview.status_all()}
    if panel == "system":
        from jarvis.core import config, diskclean
        disks = []
        for mount in ("/", *[str(Path(x).expanduser()) for x in config.SEARCH_ROOTS]):
            try:
                du = shutil.disk_usage(mount)
                disks.append({"mount": mount, "used": du.used, "total": du.total})
            except OSError:
                continue
        return {"kurama": _kurama(), "disks": disks, "can_free": None, "trash": diskclean.gb(
            sum(diskclean.size_of(x) for x in diskclean.find("trash")))}
    if panel == "laptop":
        from jarvis.api import device
        return {**device.info(), "switches": _switches()}
    return {}


@router.get("/dashboard/detail/{panel}", summary="Details for one card")
async def dashboard_detail(panel: str):
    return await run_in_threadpool(lambda: _cached(f"detail:{panel}", 5, lambda: detail(panel)))


class LocationFix(BaseModel):
    lat: float
    lon: float
    accuracy: float = 0.0


class ResetIn(BaseModel):
    level: str = "chat"  # chat | recent | all


@router.post("/reset", summary="Clear the chat, or chat+reminders, or everything (keeps password + settings)")
async def reset_endpoint(body: ResetIn, request: Request):
    from jarvis.core import reset
    agent = None
    try:
        agent = request.app.state.engine.agent()
    except Exception:
        agent = None
    fn = {"all": reset.reset_all, "recent": reset.clear_recent}.get(body.level, reset.clear_chat)
    msg = await run_in_threadpool(fn, agent)
    return {"ok": True, "message": msg}


@router.post("/location", summary="The browser's accurate position (Geolocation API) for the laptop")
async def location_fix(body: LocationFix):
    from jarvis.core import geolocate, locationlog
    await run_in_threadpool(geolocate.set_browser_fix, body.lat, body.lon, body.accuracy)
    # also feed the movement history, so the trail is accurate
    await run_in_threadpool(lambda: locationlog.record("laptop", body.lat, body.lon, int(body.accuracy or 0), "gps",
                                                       geolocate.place_name(body.lat, body.lon, int(body.accuracy or 0))))
    return {"ok": True}


# ---------------------------------------------------------------- fuller forecast for the weather card
def forecast(place: str) -> dict:
    from jarvis.tools.general import _geo
    geo = _geo.geocode(place)
    if not geo:
        return {"error": "not found"}
    d = _geo.get_json("https://api.open-meteo.com/v1/forecast", {
        "latitude": geo["lat"], "longitude": geo["lon"], "timezone": "auto", "forecast_days": 6,
        "hourly": "temperature_2m,precipitation_probability,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code,sunrise,sunset"})
    h, dl = d.get("hourly") or {}, d.get("daily") or {}
    now = time.strftime("%Y-%m-%dT%H:00")
    times = h.get("time") or []
    i0 = next((i for i, t in enumerate(times) if t >= now), 0)
    hours = [{"t": times[i][11:16], "temp": h["temperature_2m"][i], "rain": h["precipitation_probability"][i],
              "code": h["weather_code"][i]} for i in range(i0, min(i0 + 24, len(times)))]
    days = [{"day": dl["time"][i], "max": dl["temperature_2m_max"][i], "min": dl["temperature_2m_min"][i],
             "rain": dl["precipitation_probability_max"][i], "code": dl["weather_code"][i],
             "desc": _geo.describe(dl["weather_code"][i])} for i in range(len(dl.get("time") or []))]
    sun = {"rise": (dl.get("sunrise") or [""])[0][11:16], "set": (dl.get("sunset") or [""])[0][11:16]}
    return {"place": place.split(",")[0], "hours": hours, "days": days, "sun": sun}


@router.post("/context/tab", summary="The browser extension: the tab open right now (url, title)")
async def context_tab(request: Request):
    from jarvis.core import browsertab
    d = await request.json()
    url = str(d.get("url") or "")
    if url and not url.startswith(("http://", "https://")):  # brave://, file://, new tab: no page to talk about
        url = ""
    await run_in_threadpool(browsertab.put, url, str(d.get("title") or ""), str(d.get("browser") or ""))
    return {"ok": True}


@router.get("/agent", summary="The agent that is on (general = none) and the agents there are")
async def agent_get():
    from jarvis import agents
    return await run_in_threadpool(agents.status)


@router.post("/agent", summary="Turn an agent on ({'name': 'coding'}) or off ({'name': 'general'})")
async def agent_set(request: Request):
    from jarvis import agents
    d = await request.json()
    text = await run_in_threadpool(agents.switch, str(d.get("name") or "general"))
    return {**agents.status(), "text": text}


@router.post("/coding/terminal", summary="The VS Code extension: a command failed in the terminal (coding agent on)")
async def coding_terminal(request: Request):
    from jarvis import agents
    if agents.current() != "coding":
        return {"ok": False, "reason": "the coding agent is off"}
    from jarvis.agents.coding import terminal
    d = await request.json()
    code = d.get("exit_code")
    ev = await run_in_threadpool(terminal.record, str(d.get("command") or ""), str(d.get("cwd") or ""),
                                 code if isinstance(code, int) else None, str(d.get("output") or ""))
    return {"ok": True, "event": ev}


@router.post("/context/selection", summary="The browser extension: the text highlighted on the page (memory only)")
async def context_selection(request: Request):
    from jarvis.core import browsertab
    d = await request.json()
    browsertab.put_selection(str(d.get("text") or ""), str(d.get("url") or ""), str(d.get("title") or ""),
                             editable=d.get("editable") is True)
    return {"ok": True}


@router.post("/downloads/{wid}/{action}", summary="Download bar buttons: pause, resume or delete (0 tokens)")
async def download_control(wid: int, action: str):
    from jarvis.core import ytdl
    if action not in ("pause", "resume", "delete"):
        raise HTTPException(400, "action must be pause, resume or delete")
    out = await run_in_threadpool(ytdl.control, wid, action)
    if out.startswith("error"):
        raise HTTPException(400, out[7:])
    return {"ok": True, "text": out}


@router.get("/videos", summary="Downloaded videos/audio (newest first, with a day label) for the downloads library")
async def videos():
    from jarvis.core import ytdl
    items = await run_in_threadpool(ytdl.library)
    return {"items": items, "folder": str(ytdl.out_dir()), "total": sum(i["size"] for i in items)}


@router.post("/videos/open", summary="Play a downloaded video ({name}) or open the downloads folder ({folder: true})")
async def videos_open(request: Request):
    from jarvis.core import ytdl
    d = await request.json()
    out = await run_in_threadpool(ytdl.open_item, str(d.get("name") or ""), bool(d.get("folder")))
    if out.startswith("error"):
        raise HTTPException(404, out[7:])
    return {"ok": True}


@router.post("/videos/remove", summary="Take videos off the list (files stay): {names: [...]} or {all: true}")
async def videos_remove(request: Request):
    from jarvis.core import ytdl
    d = await request.json()
    names = None if d.get("all") is True else [str(n) for n in d.get("names") or []]
    if names == []:
        raise HTTPException(400, "give names or all: true")
    return {"ok": True, "text": await run_in_threadpool(ytdl.remove, names)}


@router.get("/alerts/new", summary="Alerts newer than ?after=<id> (mini KURAMA shows them beside its button)")
async def alerts_new(after: int = 0):
    from jarvis.core import store
    rows = await run_in_threadpool(store.alerts_recent, 5)
    if after <= 0:  # first call: just learn where the list is
        return {"last": rows[0]["id"] if rows else 0, "items": []}
    items = [{k: r[k] for k in ("id", "title", "text", "level", "source")} for r in reversed(rows)
             if r["id"] > after and "desktop" in (r.get("channels") or "")]  # phone-only ones (guard) stay off
    return {"last": max([after, *(i["id"] for i in items)]), "items": items}


@router.get("/downloads", summary="Running downloads (videos and files) with progress, for the download bars")
async def downloads():
    from jarvis.core import automation
    return {"items": await run_in_threadpool(automation.live_downloads)}


@router.get("/weather/full", summary="Hourly + 6-day forecast and sun times for the weather card")
async def weather_full(place: str = ""):
    from jarvis.core import config
    p = place.strip() or list(config.UI_WEATHER_PLACES)[0]
    try:
        return await run_in_threadpool(lambda: _cached(f"wx:{p.lower()}", 900, lambda: forecast(p)))
    except Exception as e:
        return {"error": type(e).__name__}


# ---------------------------------------------------------------- direct actions (safe ones only)
class ActionIn(BaseModel):
    name: str
    path: str = ""
    setting: str = ""
    state: str = ""


def _allowed(path: str) -> Path | None:
    """Only real files/folders inside the outputs folder, the project roots or home (never system paths)."""
    from jarvis.core import config
    try:
        p = Path(path).expanduser().resolve()
    except (OSError, RuntimeError):
        return None
    if not p.exists():
        return None
    roots = [Path(config.OUTPUTS_DIR).resolve(), Path.home().resolve(),
             *[Path(r).expanduser().resolve() for r in config.SEARCH_ROOTS]]
    return p if any(p == r or r in p.parents for r in roots) else None


def act(a: ActionIn) -> dict:
    from jarvis.core import config
    if a.name in ("open_vscode", "show_folder", "open", "send_phone"):
        path = a.path
        if path and not path.startswith(("/", "~")):
            path = str(Path(config.OUTPUTS_DIR) / path)  # a workspace item (relative to data/outputs)
        p = _allowed(path)
        if p is None:
            return {"ok": False, "text": "That file isn't available."}
        if a.name == "open_vscode":
            if not shutil.which("code"):
                return {"ok": False, "text": "VS Code (code) isn't installed."}
            subprocess.Popen(["code", "-g", str(p)] if p.is_file() else ["code", str(p)], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"ok": True, "text": f"Opening {p.name} in VS Code."}
        if a.name == "show_folder":
            if p.is_file() and shutil.which("nautilus"):
                subprocess.Popen(["nautilus", "--select", str(p)], start_new_session=True, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(["xdg-open", str(p if p.is_dir() else p.parent)], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"ok": True, "text": f"Showing {p.name} in Files."}
        if a.name == "open":
            subprocess.Popen(["xdg-open", str(p)], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"ok": True, "text": f"Opening {p.name}."}
        if not config.TELEGRAM_BOT_TOKEN:
            return {"ok": False, "text": "Telegram isn't set up."}
        from jarvis.tools.general.send_file_telegram import deliver
        out = deliver(p, f"From KURAMA: {p.name}")
        return {"ok": not out.startswith("error"), "text": out}
    if a.name == "toggle":
        from jarvis.core import safety
        s, on = a.setting, a.state == "on"
        call = {"wifi": ("laptop_toggle", {"setting": "wifi", "state": a.state}),
                "bluetooth": ("laptop_toggle", {"setting": "bluetooth", "state": a.state}),
                "saver": ("laptop_toggle", {"setting": "power_mode", "state": "saver" if on else "balanced"}),
                "dnd": ("do_not_disturb", {"action": a.state}), "night": ("night_light", {"action": a.state}),
                "guard": ("laptop_guard", {"action": a.state})}.get(s)
        if call is None or a.state not in ("on", "off"):
            return {"ok": False, "text": "Unknown switch."}
        res = safety.execute(call[0], call[1], ctx={"user_text": f"dashboard: {s} {a.state}"})
        _cache.pop("switches", None)
        _cache.pop("summary", None)
        return {"ok": res.ok and not res.output.startswith("error"), "text": res.output}
    return {"ok": False, "text": "Unknown action."}


@router.post("/action", summary="Direct dashboard actions: open_vscode, show_folder, open, send_phone, toggle")
async def action(body: ActionIn):
    res = await run_in_threadpool(lambda: act(body))
    return res if res.get("ok") else JSONResponse(res, status_code=400)
