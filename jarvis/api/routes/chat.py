"""POST /api/v1/chat (SSE) and POST /api/v1/confirm.

Portable: these only need the agent. NOTE for a future server split: the agent's desktop-control
tools (volume, apps, windows, screenshots...) act on the machine the API runs on, so on a server
those tool groups must be forwarded to a small "laptop agent" instead.
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from jarvis.api.settings import LANGS
from jarvis.api.turns import Turn

router = APIRouter(prefix="/api/v1", tags=["chat"])


class ChatIn(BaseModel):
    text: str = Field("", description="User message")
    mode: str | None = Field("text", description="'text' or 'voice' (voice = short spoken-style replies)")
    lang: str | None = Field(None, description="Language hint: en | ne | hi (omit for auto)")
    ambient: bool = Field(False, description="voice heard while nobody was talking to KURAMA (room talk/TV): "
                                             "answered only when it is clearly a command or names KURAMA")


class FeedbackIn(BaseModel):
    trace: str = Field(..., description="The reply's trace id (the done event's 'trace')")
    vote: int = Field(..., description="1 = 👍 good reply, -1 = 👎 bad reply")
    note: str = Field("", description="Optional: what the user wanted instead")


class ConfirmIn(BaseModel):
    id: str
    yes: bool = False
    via: str = ""  # who answered on the page (button / typed / voice / sleep): logged, to trace wrong answers


def norm_lang(v: object) -> str | None:
    return v if isinstance(v, str) and v in LANGS else None


SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
_FLUSH = ":" + " " * 4096 + "\n\n"  # SSE comment (ignored by the page), big enough to leave WebKit's buffer


@router.post("/chat", summary="Chat turn, streamed as Server-Sent Events",
             description="Events: delta{text}, tool{name,ok,ms}, confirm{id,prompt}, confirm_timeout{id}, "
                         "error{text}, done{text,route,tier,tokens,ms,lang}.")
async def chat(body: ChatIn, request: Request):
    st = request.app.state
    text = (body.text or "").strip()[: st.settings.max_text_chars]
    if not text:
        return JSONResponse({"error": "empty text"}, status_code=400)
    mode: Literal["text", "voice"] = "voice" if body.mode == "voice" else "text"
    engine = st.engine
    turn = Turn(asyncio.get_running_loop(), asyncio.Queue())
    threading.Thread(target=engine.run_turn, args=(turn, text, mode, norm_lang(body.lang), body.ambient is True),
                     name="jarvis-turn", daemon=True).start()

    async def events():
        try:
            while True:
                ev = await turn.queue.get()
                if ev is None:
                    break
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                if ev.get("type") in ("confirm", "confirm_timeout"):  # WebKit holds back small chunks of a stream
                    yield _FLUSH  # that then waits (a yes/no): an SSE comment pushes the question out at once
        finally:
            turn.closed = True
            engine.deny_pending(turn)

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/confirm/pending", summary="Yes/no questions waiting for an answer (the page asks when its stream is quiet)")
async def confirm_pending(request: Request):
    engine = request.app.state.engine
    return {"pending": [{"type": "confirm", "id": cid, "prompt": p.prompt}
                        for cid, p in list(engine.pending.items()) if not p.event.is_set()]}


@router.post("/confirm", summary="Answer a pending confirmation (yes/no)")
async def confirm(body: ConfirmIn, request: Request):
    import logging
    logging.getLogger("jarvis.confirm").warning("confirm %s answered %s via %r", body.id, body.yes is True, body.via[:60])
    if not request.app.state.engine.answer(body.id, body.yes is True):
        return JSONResponse({"ok": False, "error": "unknown or expired confirmation"}, status_code=404)
    return {"ok": True, "yes": body.yes is True}


@router.post("/feedback", summary="👍 / 👎 on a reply: KURAMA learns 0-token shortcuts from it (or forgets a bad one)")
async def feedback(body: FeedbackIn):
    from fastapi.concurrency import run_in_threadpool
    from jarvis.core import recipes
    if body.vote not in (1, -1):
        return JSONResponse({"ok": False, "error": "vote must be 1 or -1"}, status_code=400)
    out = await run_in_threadpool(recipes.feedback, body.trace, body.vote, body.note)
    return JSONResponse(out, status_code=200 if out.get("ok") else 404)
