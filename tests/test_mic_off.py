"""Mic off (mute / text mode): KURAMA holds no microphone; the wake listener refuses to start (owner: the camera
and other sites couldn't use the mic while KURAMA had it)."""
import pytest

from jarvis.api.routes import wake
from tests.test_api import make  # noqa: F401  (fixture)


@pytest.fixture
def api(make, monkeypatch):  # noqa: F811
    started = []
    monkeypatch.setattr(wake.SERVICE, "start", lambda: started.append(1))
    monkeypatch.setattr(wake.SERVICE, "stop", lambda: started.clear())
    return make(), started


def test_mic_off_blocks_the_wake_listener(api):
    c, started = api
    assert c.post("/api/v1/wake/sleep", json={}).json()["listening"] is True and started
    assert c.post("/api/v1/wake/mic", json={"off": True}).json() == {"mic_off": True}
    assert not started  # stopped at once
    r = c.post("/api/v1/wake/sleep", json={}).json()
    assert r["listening"] is False and "mic is off" in r["reason"] and not started
    assert c.get("/api/v1/wake/status").json()["mic_off"] is True
    c.post("/api/v1/wake/mic", json={"off": False})
    assert c.post("/api/v1/wake/sleep", json={}).json()["listening"] is True
