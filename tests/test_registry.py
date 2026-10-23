from __future__ import annotations

from typing import Literal, Optional

from jarvis.core import config, registry


def make_registry():
    reg = registry.Registry(packages=())
    reg._discovered = True

    @reg.tool(group="media", description="Set the volume.")
    def set_volume(level: int, unit: Literal["percent", "db"] = "percent", mute: bool = False,
                   scale: float = 1.0, devices: list[str] | None = None,
                   note: Optional[str] = None) -> str:
        """Ignored summary.

        Args:
            level: Target level,
                from 0 to 100.
            devices (list[str]): Output devices.
        """
        return f"{level}{unit} mute={mute} scale={scale} devices={devices}"

    @reg.tool(group="misc", safety="confirm")
    def long_output() -> str:
        """Return a very long string."""
        return "x" * 5000

    return reg


def test_schema_from_hints_defaults_and_docstring():
    reg = make_registry()
    s = reg.get("set_volume").schema
    assert s["type"] == "function"
    f = s["function"]
    assert f["name"] == "set_volume" and f["description"] == "Set the volume."
    p = f["parameters"]
    assert p["required"] == ["level"]
    props = p["properties"]
    assert props["level"] == {"type": "integer", "description": "Target level, from 0 to 100."}
    assert props["unit"] == {"enum": ["percent", "db"], "type": "string"}
    assert props["mute"] == {"type": "boolean"} and props["scale"] == {"type": "number"}
    assert props["devices"] == {"type": "array", "items": {"type": "string"},
                                "description": "Output devices."}
    assert props["note"] == {"type": "string"}
    t = reg.get("long_output")
    assert t.description == "Return a very long string." and t.safety == "confirm"
    assert t.parameters == {"type": "object", "properties": {}}


def test_groups_schemas_and_call():
    reg = make_registry()
    assert reg.groups() == ["media", "misc"]
    assert [s["function"]["name"] for s in reg.schemas_for(["media"])] == ["set_volume"]
    r = reg.call("set_volume", '{"level": "40", "mute": "true", "bogus": 1}')
    assert r.ok and r.output == "40percent mute=True scale=1.0 devices=None"
    assert not reg.call("set_volume", {}).ok  # missing required
    assert not reg.call("set_volume", "{not json").ok
    assert not reg.call("nope").ok
    out = reg.call("long_output").output
    assert len(out) <= config.TOOL_OUTPUT_MAX_CHARS and out.endswith("[truncated]")


def test_tool_exception_becomes_error_result():
    reg = make_registry()

    @reg.tool
    def boom() -> str:
        """Fail."""
        raise RuntimeError("kaput")

    r = reg.call("boom")
    assert not r.ok and "kaput" in r.output


def test_bad_safety_level_rejected():
    import pytest

    with pytest.raises(ValueError):
        registry.Registry().tool(safety="maybe")


def test_discovery_imports_tool_files():
    mods = registry.REGISTRY.discover()
    assert "jarvis.tools.general.echo_time" in mods
    assert registry.get("get_time").safety == "safe"
    assert registry.get("dummy_delete").safety == "confirm"
    assert {"general", "files"} <= set(registry.groups())
    names = [s["function"]["name"] for s in registry.schemas_for(["general"])]
    assert "get_time" in names and "dummy_delete" not in names
    assert registry.call("get_time").ok
