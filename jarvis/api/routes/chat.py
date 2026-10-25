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


class ConfirmIn(BaseModel):
    id: str
    yes: bool = False


def norm_lang(v: object) -> str | None:
    return v if isinstance(v, str) and v in LANGS else None


SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


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
        finally:
            turn.closed = True
            engine.deny_pending(turn)

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/confirm", summary="Answer a pending confirmation (yes/no)")
async def confirm(body: ConfirmIn, request: Request):
    if not request.app.state.engine.answer(body.id, body.yes is True):
        return JSONResponse({"ok": False, "error": "unknown or expired confirmation"}, status_code=404)
    return {"ok": True, "yes": body.yes is True}
