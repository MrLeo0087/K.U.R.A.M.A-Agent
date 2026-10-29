"""POST /api/v1/stt (recording -> text) and POST /api/v1/tts (text -> streamed mp3).

Portable: both run anywhere (ffmpeg + Groq Whisper + edge-tts); the browser records and plays audio.
"""
from __future__ import annotations

import subprocess

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from jarvis.api.audio import TTSStream, to_wav16k
from jarvis.api.routes.chat import norm_lang
from jarvis.api.turns import reply_lang

router = APIRouter(prefix="/api/v1", tags=["voice"])


class TTSIn(BaseModel):
    text: str = Field(..., description="Text to speak (markdown/code is cleaned before synthesis)")
    lang: str | None = Field(None, description="en | ne | hi (omit: detected from the text)")


@router.post("/stt", summary="Transcribe a recording",
             description="Raw audio body (audio/webm, audio/ogg or audio/wav; any rate). Optional ?lang=en|ne|hi. "
                         "Returns {text, lang}.",
             openapi_extra={"requestBody": {"content": {"audio/*": {"schema": {"type": "string", "format": "binary"}}},
                                            "required": True}})
async def stt_endpoint(request: Request):
    s = request.app.state.settings
    data = await request.body()
    if not data:
        return JSONResponse({"error": "no audio"}, status_code=400)
    if len(data) > s.max_audio_bytes:
        return JSONResponse({"error": "audio too large"}, status_code=413)
    try:
        wav = await run_in_threadpool(to_wav16k, data, s)
    except (ValueError, OSError, subprocess.SubprocessError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    from jarvis.core import dictation, stt
    if dictation.active():
        # dictation is already listening to the same mic and typing it: a second Whisper call per phrase only
        # doubled the requests (Groq ~20/min) and made everything lag
        return {"text": "", "lang": "en", "dictation": True}
    try:
        tr = await run_in_threadpool(stt.transcribe, wav, norm_lang(request.query_params.get("lang")))
    except Exception as e:
        return JSONResponse({"error": f"transcription failed: {str(e)[:200]}"}, status_code=502)
    return {"text": getattr(tr, "text", str(tr)), "lang": getattr(tr, "lang", None) or "en"}


@router.post("/tts", summary="Speak text: streamed audio/mpeg",
             description="Sentence-chunked edge-tts: the first sentence's audio is sent as soon as it is ready.",
             response_class=StreamingResponse,
             responses={200: {"content": {"audio/mpeg": {}}}, 502: {"description": "synthesis failed"}})
async def tts_endpoint(body: TTSIn, request: Request):
    text = (body.text or "").strip()[: request.app.state.settings.max_text_chars]
    if not text:
        return JSONResponse({"error": "empty text"}, status_code=400)
    lang = norm_lang(body.lang) or await run_in_threadpool(reply_lang, text, None)
    stream = await run_in_threadpool(TTSStream, text, lang)
    first = await run_in_threadpool(stream.next_chunk)  # fail cleanly (502) before any byte is sent
    if first is None:
        err = stream.error
        return JSONResponse({"error": f"speech synthesis failed: {str(err)[:200] if err else 'no audio'}"},
                            status_code=502)
    return StreamingResponse(stream.iterate(first), media_type="audio/mpeg",
                             headers={"Cache-Control": "no-store", "X-Voice": stream.voice})


class DeviceSoundIn(BaseModel):
    hear: bool = Field(..., description="true: KURAMA hears device sound too; false: only you (echo canceller on)")


@router.get("/voice/device-sound", summary="Does KURAMA hear the laptop's own sound?")
async def device_sound_get():
    from jarvis.core import devaudio
    return await run_in_threadpool(devaudio.status)


@router.post("/voice/device-sound", summary="Hear device sound on/off (off = the laptop's own sound is removed from the mic)")
async def device_sound_set(body: DeviceSoundIn):
    from jarvis.core import devaudio
    return await run_in_threadpool(devaudio.set_hear, body.hear)


class MicUseIn(BaseModel):
    on: bool = Field(..., description="the page starts (true) / stops (false) recording the mic")
    id: str = Field("page", max_length=40, description="which page (main, mini...)")


@router.post("/voice/mic", summary="A page records the mic: the echo canceller runs only meanwhile")
async def mic_use(body: MicUseIn):
    from jarvis.core import devaudio
    return await run_in_threadpool(devaudio.mic_use, body.on, body.id)


class VoiceSettingsIn(BaseModel):
    mic_volume: int | None = Field(None, ge=10, le=150, description="laptop microphone volume %")
    wake: str | None = Field(None, description="wake word sensitivity: low | normal | high")


@router.get("/voice/settings", summary="Microphone volume + wake word sensitivity")
async def voice_settings_get():
    from jarvis.core import voicecfg
    return await run_in_threadpool(voicecfg.status)


@router.post("/voice/settings", summary="Change the microphone volume and/or the wake word sensitivity")
async def voice_settings_set(body: VoiceSettingsIn):
    from jarvis.core import voicecfg
    try:
        if body.mic_volume is not None:
            await run_in_threadpool(voicecfg.set_mic_volume, body.mic_volume)
        if body.wake:
            voicecfg.set_wake_level(body.wake)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    return {"ok": True, **(await run_in_threadpool(voicecfg.status))}
