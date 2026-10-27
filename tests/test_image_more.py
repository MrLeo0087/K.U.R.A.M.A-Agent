import json

from jarvis.core import config, fastpath, jobs, store
from jarvis.tools.general import generate_image as gi


def _fake(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    calls = []
    monkeypatch.setattr(gi, "fetch_image", lambda p, w, h, **k: calls.append((p, w, h, k)) or b"\x89PNG....")

    class Mgr:
        n = 0

        def submit(self, title, kind, fn, request="", lang="en"):
            Mgr.n += 1
            fn(type("C", (), {"progress": lambda self, _: None})())
            return type("J", (), {"id": Mgr.n})()
    monkeypatch.setattr(jobs, "get_manager", lambda: Mgr())
    return calls


def test_versions_sizes_and_changes(monkeypatch, tmp_path):
    calls = _fake(monkeypatch, tmp_path)
    out = gi.generate_image("a red fox", count=4)
    assert "4 versions" in out and len(calls) == 4 and len({c[3]["seed"] for c in calls}) == 4
    assert all(c[3]["exact"] for c in calls) and len(list((tmp_path / "images").iterdir())) == 4
    calls.clear()
    assert "(1080x1920)" in gi.generate_image("a tiger phone wallpaper")
    assert calls[0][1:3] == (1080, 1920)
    calls.clear()
    gi.generate_image("a castle", width=800, height=600)
    seed = json.loads(store.kv_get(gi.LAST_KEY))["seed"]
    gi.generate_image("at night", change_last=True)  # same picture (same seed + size), with the change
    assert calls[-1][0].startswith("a castle, at night") and calls[-1][3]["seed"] == seed and calls[-1][1:3] == (800, 600)
    gi.generate_image("another version", change_last=True)
    assert calls[-1][0].startswith("a castle, at night") and calls[-1][3]["seed"] != seed
    gi.generate_image("a lake", detailed=True)
    assert calls[-1][3]["enhance"] is True
    store.kv_set(gi.LAST_KEY, "")
    assert gi.generate_image("at night", change_last=True).startswith("error")


def test_routes(monkeypatch):
    m = fastpath.match
    assert m("make 4 versions of a red fox").args == {"prompt": "a red fox", "count": 4}
    assert m("same picture but at night").args == {"prompt": "at night", "change_last": True}
    assert m("create an HD image of a castle").args == {"prompt": "a castle", "detailed": True}
    assert m("make it more colorful") is None  # no picture made recently
    store.kv_set(gi.LAST_KEY, json.dumps({"prompt": "a fox", "at": __import__("time").time()}))
    assert m("make it more colorful").args == {"prompt": "more colorful", "change_last": True}
    assert m("make another one").args["change_last"]
