from jarvis.core import semantic


class FakeEmb:
    def __init__(self):
        self.idle_s, self.loaded, self.unloads, self.armed = None, True, 0, 0

    def unload(self):
        self.unloads += 1
        self.loaded = False

    def _arm(self):
        self.armed += 1


def test_modes(monkeypatch):
    fake = FakeEmb()
    monkeypatch.setattr(semantic, "_embedder", fake)
    semantic.set_mode("always")
    assert semantic.mode() == "always" and fake.idle_s == 0.0  # never unloads
    semantic.set_mode("auto")
    assert fake.idle_s == semantic.config.SEMANTIC_AUTO_IDLE_S and fake.armed == 2
    semantic.set_mode("off")
    assert fake.unloads == 1 and semantic.scores("enable speech to text mode") == []
    semantic.free_now()
    assert fake.unloads == 2
    try:
        semantic.set_mode("turbo")
        raise AssertionError
    except ValueError:
        pass


def test_resources_api():
    import asyncio
    from jarvis.api.routes import info
    r = asyncio.run(info.resources())
    assert "total_mb" in r and r["semantic"]["mode"] in semantic.MODES


def test_resources_has_cpu_and_share():
    import asyncio
    from jarvis.api.routes import info
    r = asyncio.run(info.resources())
    assert {"total_cpu", "ram_share", "parts"} <= set(r) and all({"mb", "cpu", "procs"} <= set(p) for p in r["parts"])
