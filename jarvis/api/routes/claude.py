"""Claude Code watch, laptop side: the hook (scripts/claude_hook.py) posts Claude Code's events here and waits for
the owner's answer to a permission question (jarvis/core/claudewatch.py)."""
from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from jarvis.core import claudewatch, config

router = APIRouter(prefix="/api/v1/claude", tags=["claude"])


@router.post("/event", summary="One Claude Code hook event (only kept while the watch is on)")
async def claude_event(request: Request) -> dict:
    try:
        data = await request.json()
    except ValueError:
        return {}
    out = await run_in_threadpool(claudewatch.event, data if isinstance(data, dict) else {})
    if out.get("wait"):
        out["wait_s"] = config.CLAUDE_ANSWER_WAIT_S
    return out


@router.get("/decision", summary="The owner's answer to a permission question: allow / deny / '' (waiting)")
async def claude_decision(id: str = "") -> dict:
    return {"answer": claudewatch.decision(id)}
