"""Every plugin keeps its contract (tools, memory sources, agents), and one broken plugin never stops the others.
These run over EVERY plugin found, so a new tool / memory / agent is checked with no test of its own to write."""
from __future__ import annotations

import sys

import pytest

from jarvis import agents
from jarvis.core import memories, plugins, registry


def test_every_tool_keeps_the_contract():
    registry.REGISTRY.discover()
    bad = []
    for name, t in registry.REGISTRY.tools.items():
        desc = (t.description or "").strip()
        if not desc:
            bad.append(f"{name}: no description")
        if registry.safety_of(t) not in registry.SAFETY_LEVELS:
            bad.append(f"{name}: safety {registry.safety_of(t)!r}")
        if not registry.group_of(t):
            bad.append(f"{name}: no group")
        try:
            schema = registry.schema_of(t)["function"]
            assert schema["name"] == name and schema["parameters"]["type"] == "object"
        except Exception as e:  # noqa: BLE001
            bad.append(f"{name}: schema {type(e).__name__}: {e}")
    assert not bad, "\n".join(bad)
    assert len(registry.REGISTRY.tools) > 50


def test_every_memory_source_keeps_the_contract():
    srcs = memories.sources()
    assert {"notes", "profile", "links", "documents"} <= set(srcs)
    for name, s in srcs.items():
        assert s.name == name and s.description.strip() and callable(s.search)
        if not s.heavy:
            hits = s.search("anything at all", 3)  # an empty test database: a list, never an error
            assert isinstance(hits, list)


def test_memory_search_fuses_and_isolates(monkeypatch):
    def good(q, k):
        return [memories.Hit("the locker code is 42", ref="n1")]

    def broken(q, k):
        raise RuntimeError("disk gone")
    monkeypatch.setattr(memories, "_cache", {
        "a": memories.MemorySource("a", "A", good),
        "b": memories.MemorySource("b", "B", broken),
        "c": memories.MemorySource("c", "C", lambda q, k: [memories.Hit("big index")], heavy=True)})
    hits = memories.search("locker", 5)
    assert [h.text for h in hits] == ["the locker code is 42"] and hits[0].source == "a"
    assert [h.text for h in memories.search("x", 5, heavy=True)][-1] == "big index"
    assert memories.search("", 5) == []


def test_every_agent_keeps_the_contract():
    assert "coding" in agents.AGENTS
    for name in agents.AGENTS:
        sp = agents.spec(name)
        assert sp is not None and sp.name == name and sp.title and sp.groups
        assert all(g in agents.groups() for g in sp.groups)
    assert agents._alias("coder") == "coding" and agents._alias("off") == "general"
    assert "jarvis.agents.coding.tools" in agents.tool_modules()


def test_a_broken_plugin_is_skipped(tmp_path, monkeypatch):
    pkg = tmp_path / "fakeplugs"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "good.py").write_text("THING = 1\n")
    (pkg / "bad.py").write_text("raise ImportError('missing library')\n")
    (pkg / "_private.py").write_text("THING = 2\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        assert plugins.names("fakeplugs") == ["bad", "good"]
        assert plugins.load("fakeplugs", "THING") == {"good": 1}
        assert "fakeplugs.bad" in plugins.broken()
    finally:
        for m in [m for m in sys.modules if m.startswith("fakeplugs")]:
            del sys.modules[m]


@pytest.mark.parametrize("kind", ["tool", "memory", "agent"])
def test_scaffold_writes_working_plugins(kind, tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("new_plugin", registry.__file__.replace("jarvis/core/registry.py",
                                                                                       "scripts/new_plugin.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["new_plugin.py", kind, "demo_thing"])
    mod.main()
    written = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*.py"))
    assert written and all(compile(p.read_text(), str(p), "exec") for p in tmp_path.rglob("*.py"))
    with pytest.raises(SystemExit):  # never overwrites
        mod.main()


def test_recall_falls_back_to_other_memories():
    from jarvis.core import profile
    profile.save("home_city", "Pokhara")
    out = registry.call("recall", {"which": "search", "query": "Pokhara"}).output
    assert out.startswith("I have no notes about 'Pokhara', but I found:") and "lives in Pokhara (profile)" in out
    assert registry.call("recall", {"which": "search", "query": "zzqx"}).output == "I have no notes about 'zzqx'."
