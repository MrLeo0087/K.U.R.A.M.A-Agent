import time

import pytest

from jarvis.core import config, fastpath, llm, modes
from jarvis.workers import supervisor


@pytest.fixture(autouse=True)
def no_apply(monkeypatch):
    applied = []
    monkeypatch.setattr(modes, "_apply", applied.append)  # never touch the real model / wake listener
    return applied


def test_default_presets_and_custom(no_apply):
    assert modes.current()["mode"] == "normal" and modes.current()["ai"] == "normal"
    st = modes.set_mode("lowram")
    assert st["workers"] == ["scheduler", "telegram_bot"] and st["model"] == "off" and st["screen"] == "mini"
    assert modes.current()["mode"] == "lowram" and no_apply
    st = modes.set_switch("workers", {"guard": True})
    assert st["mode"] == "custom" and "guard" in st["workers"] and modes.name() == "Custom"
    st = modes.set_switch("workers", {"guard": False})
    assert st["mode"] == "lowram"  # back on the preset's exact switches: its name again
    with pytest.raises(ValueError):
        modes.set_mode("turbo")
    with pytest.raises(ValueError):
        modes.set_switch("workers", {"nope": True})


def test_estimates_order():
    est = {p["id"]: p["est_mb"] for p in modes.summary()["presets"]}
    assert est["full"] > est["normal"] > est["lowram"] >= est["laptop"]


def test_ai_level_reaches_the_llm_layer():
    modes.set_mode("noai")
    with pytest.raises(llm.LLMError):
        llm._chain("fast")
    modes.set_mode("laptop")  # small model only
    assert llm._chain("smart")[0] == config.LLM_FAST
    modes.set_mode("normal")
    assert llm._chain("smart")[0] == config.LLM_DEFAULT


def test_no_ai_mode_answers_without_the_llm(monkeypatch):
    from jarvis.core import agent
    modes.set_mode("noai")
    a = agent.Agent()
    assert a.run("write me a poem about the moon") == modes.NO_AI


def test_desired_workers_respect_env(monkeypatch):
    monkeypatch.setattr(config, "WORKERS_ENABLED", ("scheduler",))
    modes.set_mode("full")
    assert modes.desired_workers() == ["scheduler"]


def test_supervisor_sync_starts_and_stops_live(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "WORKERS_STATUS_PATH", str(tmp_path / "workers.json"), raising=False)
    events = []

    class Fake:
        def __init__(self, name):
            self.name, self.alive = name, False
            import threading
            self._stop = threading.Event()
            self.log = __import__("logging").getLogger("t")

        def available(self):
            return "no token" if self.name == "telegram_bot" else None

        def start(self):
            self.alive = True
            events.append(("start", self.name))

        def stop(self, timeout=0):
            self.alive = False
            events.append(("stop", self.name))

        def status(self):
            return {"state": "running" if self.alive else "stopped"}

    monkeypatch.setattr(supervisor, "load", Fake)
    sup = supervisor.Supervisor(["scheduler", "telegram_bot", "guard"])
    sup.start()
    assert set(sup.workers) == {"scheduler", "guard"} and "telegram_bot" in sup.skipped
    sup.sync(["scheduler"])
    assert set(sup.workers) == {"scheduler"} and ("stop", "guard") in events and not sup.skipped
    n = len(events)
    sup.sync(["scheduler"])
    assert len(events) == n  # nothing restarted
    sup.shutdown()


def test_power_mode_routing(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    cases = {"switch to low ram mode": "lowram", "full power mode": "full", "turn on no ai mode": "noai",
             "go to laptop only mode": "laptop", "use best ai mode": "smart", "normal mode": "normal",
             "enable basic mode": "basic", "what mode are you in": "status", "save ram": "lowram"}
    for text, mode in cases.items():
        i = fastpath.match(text)
        assert i and i.tool == "power_mode" and i.args == {"mode": mode}, text
    assert fastpath.match("switch to light mode").tool == "set_theme"  # the theme, not a power mode
    assert fastpath.match("power saver mode").tool == "laptop_toggle"


def test_power_mode_tool():
    from jarvis.tools.general.power_mode import power_mode
    out = power_mode(mode="lowram")
    assert out.startswith("Low RAM mode on") and "MB" in out
    assert power_mode(mode="status").startswith("Low RAM mode is on")


def test_a_saved_preset_follows_its_current_definition():
    import json
    from jarvis.core import store
    store.kv_set("power_mode", json.dumps({"mode": "normal", "workers": ["scheduler"], "model": "off"}))
    modes._cache = (0.0, {})
    st = modes.current()
    assert st["workers"] == list(modes.ALL) and st["model"] == "auto"  # new helpers join the preset
