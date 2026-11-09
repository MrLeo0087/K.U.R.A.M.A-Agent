"""Plan 11-09 phase 2: every recording's loudness is logged (and a silent one kept) to find why holds came back as
silence; one chat across KURAMA's windows (a hold-to-talk turn in the hidden mini chat shows in the main window)."""
import array
import io
import wave

from fastapi.testclient import TestClient

from jarvis.core import stt


def _wav(samples):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
        w.writeframes(array.array("h", samples).tobytes())
    return buf.getvalue()


def test_the_loudness_of_a_recording():
    assert stt.level_of(_wav([0] * 1600)) == (0, 0)
    peak, rms = stt.level_of(_wav([8000, -8000] * 800))
    assert peak == 8000 and rms == 8000


def test_a_turn_from_one_window_is_shown_in_the_others():
    from jarvis.api.routes import chat
    chat._FEED.clear()
    chat._feed_add("mini1", "what time is it", "It's 7 PM.", "voice")
    chat._feed_add("main1", "hello", "Hello!", "text")
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(chat.router)
    c = TestClient(app)
    r = c.get("/api/v1/chat/feed", params={"after": 0, "origin": "main1"}).json()
    assert [t["user"] for t in r["turns"]] == ["what time is it"] and r["last"] >= 2  # not its own turn
    assert c.get("/api/v1/chat/feed", params={"after": r["last"], "origin": "main1"}).json()["turns"] == []
