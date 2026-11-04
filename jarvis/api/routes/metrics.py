"""GET /api/v1/metrics: Prometheus text format (scrape it, or read it with `make metrics`)."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from starlette.concurrency import run_in_threadpool

from jarvis.core import metrics

router = APIRouter(prefix="/api/v1", tags=["info"])


@router.get("/metrics", summary="Prometheus metrics: LLM tokens, tool calls, routing, jobs, RAM (last 24 h)",
            response_class=PlainTextResponse)
async def get_metrics() -> PlainTextResponse:
    text = await run_in_threadpool(metrics.render)
    return PlainTextResponse(text, media_type="text/plain; version=0.0.4; charset=utf-8")
