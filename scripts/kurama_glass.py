#!/usr/bin/python3
"""KURAMA glass: the blur behind the mini chat panel, done by GNOME's Blur my Shell extension (0 KURAMA RAM/CPU).

Run with the SYSTEM python3 (needs PyGObject):  /usr/bin/python3 scripts/kurama_glass.py [get | set <blur 0-100>]
- makes sure the extension blurs the panel (window class KURAMA-mini in its application whitelist),
- keeps a pipeline of our own ("KURAMA glass": dual Kawase blur) and points application blur at it,
- `set N` changes the blur strength (0 = clear glass, 100 = heavy frost). Prints JSON.
Note: the extension's application settings are shared by every whitelisted app (e.g. the terminal).
Found 2026-10-31: the migrated pipeline it used had brightness 0, so the "blur" was a black box.
"""
from __future__ import annotations

import json
import os
import sys

UUID = "blur-my-shell@aunetx"
BASE = "org.gnome.shell.extensions.blur-my-shell"
PIPE = "pipeline_kurama_glass"  # used only when no pipeline below exists
# Blur my Shell fully sets up (incl. round corners) only pipelines it knew when GNOME Shell started; one added at
# runtime blurred with SQUARE corners (tested 2026-10-31). So reuse a pipeline that existed at login: the unused
# "Default rounded - duplicate" on this laptop. A new id works after the next login.
REUSE = ("pipeline_75755336945823",)
CLASS = "KURAMA-mini"
MAX_RADIUS = 100  # strength = blur radius in px (above ~50 the extension adds a pass that smears its round corners square; tested)
BRIGHTNESS = 0.9  # the panel's own tint does the darkening


def _settings(schema: str):
    from gi.repository import Gio
    for d in (os.path.expanduser(f"~/.local/share/gnome-shell/extensions/{UUID}/schemas"),
              f"/usr/share/gnome-shell/extensions/{UUID}/schemas"):
        if os.path.isdir(d):
            src = Gio.SettingsSchemaSource.new_from_directory(d, Gio.SettingsSchemaSource.get_default(), False)
            found = src.lookup(schema, False)
            if found is not None:
                return Gio.Settings.new_full(found, None, None)
    return None


def _v(x):
    from gi.repository import GLib
    if isinstance(x, bool):
        return GLib.Variant("b", x)
    if isinstance(x, int):
        return GLib.Variant("i", x)
    if isinstance(x, float):
        return GLib.Variant("d", x)
    if isinstance(x, str):
        return GLib.Variant("s", x)
    if isinstance(x, list):
        return GLib.Variant("av", [_v(i) for i in x])
    if isinstance(x, dict):
        return GLib.Variant("a{sv}", {k: _v(i) for k, i in x.items()})
    raise TypeError(type(x))


def _strength(radius: float) -> int:
    return max(0, min(100, round(radius * 100 / MAX_RADIUS)))


def state() -> dict:
    g, apps = _settings(BASE), _settings(BASE + ".applications")
    if g is None or apps is None:
        return {"ok": False, "error": "Blur my Shell is not installed"}
    pipes = g.get_value("pipelines").unpack()
    eff = (pipes.get(_pipe(pipes, apps)) or {}).get("effects") or [{}]
    radius = float((eff[0].get("params") or {}).get("unscaled_radius", 40))
    return {"ok": True, "blur": _strength(radius), "radius": radius, "pipeline": apps.get_string("pipeline"),
            "listed": CLASS in apps.get_strv("whitelist"), "on": apps.get_boolean("blur"),
            "corner": apps.get_int("corner-radius"),
            "light": round(100 * float((eff[0].get("params") or {}).get("brightness", BRIGHTNESS)))}


def _pipe(pipes: dict, apps) -> str:
    """Our pipeline id: the one already in use if it's ours, else a reusable one from login time, else our own."""
    cur = apps.get_string("pipeline")
    if cur == PIPE or (pipes.get(cur) or {}).get("name") == "KURAMA glass":
        return cur
    used = set()
    for k in ("panel", "dash-to-dock", "overview", "appfolder", "lockscreen", "screenshot", "window-list",
              "coverflow-alt-tab"):
        s = _settings(f"{BASE}.{k}")
        if s is not None and s.settings_schema.has_key("pipeline"):
            used.add(s.get_string("pipeline"))
    for pid in REUSE:
        if pid in pipes and pid not in used:
            return pid
    return PIPE


def apply(strength: int | None = None, corner: int | None = None, light: int | None = None) -> dict:
    from gi.repository import Gio
    g, apps = _settings(BASE), _settings(BASE + ".applications")
    if g is None or apps is None:
        return {"ok": False, "error": "Blur my Shell is not installed"}
    pipes = g.get_value("pipelines").unpack()
    pid = _pipe(pipes, apps)
    effs = (pipes.get(pid) or {}).get("effects") or [{"type": "dual_kawase_blur", "id": "effect_kurama_glass"}]
    params = dict(effs[0].get("params") or {})
    old = params.get("unscaled_radius", 40)
    radius = int(old if strength is None else round(max(0, min(100, strength)) * MAX_RADIUS / 100))
    params.update(unscaled_radius=radius, brightness=float(params.get("brightness", BRIGHTNESS)) if light is None
                  else max(0.2, min(1.5, light / 100)))
    pipes[pid] = {"name": "KURAMA glass", "effects": [{**effs[0], "type": "dual_kawase_blur", "params": params}]}
    if pid != PIPE:
        pipes.pop(PIPE, None)  # an earlier runtime-made entry (square corners): not needed
    from gi.repository import GLib
    g.set_value("pipelines", GLib.Variant("a{sa{sv}}", {k: {kk: _v(vv) for kk, vv in v.items()} for k, v in pipes.items()}))
    wl = apps.get_strv("whitelist")
    if CLASS not in wl:
        apps.set_strv("whitelist", wl + [CLASS])
    apps.set_string("pipeline", pid)
    if corner is not None:
        apps.set_int("corner-radius", max(0, min(40, int(corner))))
    apps.set_boolean("blur", True)
    apps.set_boolean("dynamic-opacity", False)  # else the blur disappears from the focused window
    apps.set_int("opacity", 255)  # the page draws its own see-through tint; text stays crisp
    Gio.Settings.sync()
    return state()


if __name__ == "__main__":
    try:
        if len(sys.argv) > 2 and sys.argv[1] == "set":  # set <blur px> [<corner px> [<light %>]]
            nums = [int(float(a)) for a in sys.argv[2:5]] + [None, None]
            out = apply(nums[0], nums[1], nums[2])
        elif len(sys.argv) > 1 and sys.argv[1] == "setup":
            out = apply(None)
        else:
            out = state()
    except Exception as e:  # never a traceback for the UI
        out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    print(json.dumps(out))
