"""Dashboard API: summary, details, safe direct actions (paths fenced in, switches through the tools)."""
from types import SimpleNamespace

import pytest

from jarvis.api.routes import dash
from jarvis.core import config, safety
from tests.test_api import make  # noqa: F401  (fixture)


@pytest.fixture
def api(make, monkeypatch):  # noqa: F811
    dash._cache.clear()
    return make()


def test_summary_shape_and_cache(api, monkeypatch):
    calls = []
    monkeypatch.setattr(dash, "_apps", lambda: calls.append(1) or {"apps": [{"name": "Brave", "bytes": 2e9, "procs": 9}]})
    monkeypatch.setattr(dash, "_coding", lambda: {"project": "KURAMA", "branch": "master", "changed": 3})
    monkeypatch.setattr(dash, "_switches", lambda: {"wifi": True, "bluetooth": False})
    r = api.get("/api/v1/dashboard").json()
    assert r["apps"]["apps"][0]["name"] == "Brave" and r["coding"]["changed"] == 3 and r["switches"]["wifi"] is True
    assert set(r) == {"apps", "coding", "now", "today", "kurama", "switches"}
    api.get("/api/v1/dashboard")
    assert len(calls) == 1  # cached
    monkeypatch.setattr(dash, "_coding", lambda: (_ for _ in ()).throw(RuntimeError("git broke")))
    dash._cache.clear()
    assert api.get("/api/v1/dashboard").json()["coding"]["error"] == "RuntimeError"  # one broken piece never breaks the rest


def test_actions_are_fenced_in(api, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path / "out")
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "calc.py").write_text("print(1)")
    monkeypatch.setattr(dash.shutil, "which", lambda b: "/usr/bin/" + b)
    started = []
    monkeypatch.setattr(dash.subprocess, "Popen", lambda args, **k: started.append(args))
    r = api.post("/api/v1/action", json={"name": "open_vscode", "path": "calc.py"})
    assert r.status_code == 200 and started[-1] == ["code", "-g", str(tmp_path / "out" / "calc.py")]
    assert api.post("/api/v1/action", json={"name": "open_vscode", "path": "/etc/passwd"}).status_code == 400
    assert api.post("/api/v1/action", json={"name": "open_vscode", "path": "../../etc/passwd"}).status_code == 400
    assert api.post("/api/v1/action", json={"name": "rm_rf", "path": "calc.py"}).status_code == 400
    r = api.post("/api/v1/action", json={"name": "show_folder", "path": "calc.py"})
    assert r.status_code == 200 and started[-1][0] in ("nautilus", "xdg-open")


def test_toggle_goes_through_the_tools(api, monkeypatch):
    seen = []
    monkeypatch.setattr(safety, "execute", lambda name, args, **k: seen.append((name, args)) or SimpleNamespace(ok=True, output="ok"))
    assert api.post("/api/v1/action", json={"name": "toggle", "setting": "bluetooth", "state": "on"}).status_code == 200
    assert api.post("/api/v1/action", json={"name": "toggle", "setting": "saver", "state": "on"}).status_code == 200
    assert api.post("/api/v1/action", json={"name": "toggle", "setting": "night", "state": "off"}).status_code == 200
    assert seen == [("laptop_toggle", {"setting": "bluetooth", "state": "on"}),
                    ("laptop_toggle", {"setting": "power_mode", "state": "saver"}), ("night_light", {"action": "off"})]
    assert api.post("/api/v1/action", json={"name": "toggle", "setting": "reactor", "state": "on"}).status_code == 400
    assert api.post("/api/v1/action", json={"name": "toggle", "setting": "wifi", "state": "maybe"}).status_code == 400


def test_detail_unknown_panel_is_empty(api):
    assert api.get("/api/v1/dashboard/detail/nope").json() == {}
