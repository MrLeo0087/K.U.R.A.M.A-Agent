"""Read-mostly panels: health, status (+SSE stream), jobs, alerts, profile facts, tools.

LAPTOP-LOCAL: /status and /status/stream describe the machine the API runs on (CPU, RAM, processes)
and the jobs/alerts/workers in its local data/ folder. In a server split these move to the laptop agent.
"""
from __future__ import annotations

import asyncio
import json
import time

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


@router.get("/status", summary="Laptop + Jarvis status snapshot (laptop-local)")
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
