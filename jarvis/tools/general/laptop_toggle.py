"""laptop_toggle: the laptop's quick switches: Wi-Fi, Bluetooth, airplane mode, power mode, screen off. Safe."""
from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Literal

from jarvis.core import store
from jarvis.core.registry import tool
from jarvis.tools.general import _sys

MODES = {"saver": "power-saver", "power-saver": "power-saver", "balanced": "balanced", "performance": "performance"}


def _radio(kind: str, state: str) -> str:
    if kind == "wifi":
        if state == "status":
            return f"Wi-Fi is {_sys.run(['nmcli', 'radio', 'wifi']).strip()}."
        _sys.run(["nmcli", "radio", "wifi", "on" if state == "on" else "off"])
        return f"Wi-Fi turned {state}."
    dev = "all" if kind == "airplane" else "bluetooth"
    if state == "status":
        out = _sys.run(["rfkill", "list", dev])
        blocked = "Soft blocked: yes" in out
        return f"{'Airplane mode' if kind == 'airplane' else 'Bluetooth'} is {'on' if blocked == (kind == 'airplane') else 'off'}."
    block = (state == "on") == (kind == "airplane")  # airplane ON = block all radios; bluetooth ON = unblock
    _sys.run(["rfkill", "block" if block else "unblock", dev])
    return f"{'Airplane mode' if kind == 'airplane' else 'Bluetooth'} turned {state}."


_AWAKE_KEYS = (("org.gnome.desktop.session", "idle-delay"),
               ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-ac-type"),
               ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-battery-type"))


_CAFFEINE = Path.home() / ".local/share/gnome-shell/extensions/caffeine@patapon.info/schemas"


def _caffeine(on: bool | None = None) -> bool | None:
    """The owner's Caffeine extension (the cup in the top bar): read (on=None) or switch it. None = not installed."""
    for d in (_CAFFEINE, Path("/usr/share/gnome-shell/extensions/caffeine@patapon.info/schemas")):
        if (d / "gschemas.compiled").exists():
            base = ["gsettings", "--schemadir", str(d)]
            if on is None:
                return _sys.run(base + ["get", "org.gnome.shell.extensions.caffeine", "user-enabled"]).strip() == "true"
            _sys.run(base + ["set", "org.gnome.shell.extensions.caffeine", "user-enabled", "true" if on else "false"])
            return on
    return None


def _awake(state: str) -> str:
    """Keep the screen on (no blank, no sleep) - Ubuntu's nearest thing to an always-on display - and back. With the
    Caffeine extension installed, its own switch (the cup in the top bar shows it); else the GNOME settings."""
    caf = _caffeine()
    if caf is not None:
        if state in ("status", ""):
            return "Caffeine is on: the screen stays on." if caf else "Caffeine is off: the screen sleeps as usual."
        _caffeine(state == "on")
        return ("Okay: Caffeine is on, the screen stays on and the laptop won't sleep by itself." if state == "on"
                else "Okay: Caffeine is off, the screen sleeps as usual.")
    if state in ("status", ""):
        return "The screen stays on." if store.kv_get("stay_awake_saved") else "The screen turns off and sleeps as usual."
    if state == "on":
        if not store.kv_get("stay_awake_saved"):  # the owner's own values, put back by 'off'
            store.kv_set("stay_awake_saved", json.dumps({k: _sys.run(["gsettings", "get", sch, k]).strip() for sch, k in _AWAKE_KEYS}))
        _sys.run(["gsettings", "set", "org.gnome.desktop.session", "idle-delay", "0"])
        for sch, k in _AWAKE_KEYS[1:]:
            _sys.run(["gsettings", "set", sch, k, "nothing"])
        return "Okay: the screen stays on and the laptop won't sleep by itself. Say 'let the screen sleep' to undo it."
    saved = json.loads(store.kv_get("stay_awake_saved") or "{}")
    for sch, k in _AWAKE_KEYS:
        v = saved.get(k)
        if v:
            _sys.run(["gsettings", "set", sch, k, v.strip("'").replace("uint32 ", "")])
    store.kv_set("stay_awake_saved", "")
    return "Okay: the screen and sleep settings are back to how they were."


@tool(group="system", safety="safe",
      description="Laptop switches: Wi-Fi, Bluetooth, airplane mode on/off, power mode (saver/balanced/performance), screen off "
                  "now, stay_awake (keep the screen on: 'always on display', no sleep) on/off.")
def laptop_toggle(setting: Literal["wifi", "bluetooth", "airplane", "power_mode", "screen", "stay_awake"],
                  state: str = "status") -> str:
    """Turn a laptop setting on/off or read it.

    Args:
        setting: wifi, bluetooth, airplane, power_mode, screen (turn it off now) or stay_awake (keep the screen on).
        state: on / off / status; for power_mode: saver, balanced or performance; for screen: off.
    """
    state = (state or "status").lower().strip()
    if setting in ("wifi", "bluetooth", "airplane"):  # "turn it off" next time means this one
        store.kv_set("last_switch", json.dumps({"device": setting, "t": time.time()}))
    try:
        if setting in ("wifi", "bluetooth", "airplane"):
            if state not in ("on", "off", "status"):
                return "error: say on, off or status"
            return _radio(setting, state)
        if setting == "power_mode":
            if state in ("status", ""):
                return f"Power mode is {_sys.run(['powerprofilesctl', 'get']).strip()}."
            mode = MODES.get(state.replace(" ", "-"), MODES.get("saver" if state == "on" else "balanced" if state == "off" else ""))
            if not mode:
                return "error: choose saver, balanced or performance"
            _sys.run(["powerprofilesctl", "set", mode])
            return f"Power mode set to {mode.replace('-', ' ')}."
        if setting == "screen":
            if state == "on":  # 'turn on the screen / always on display' must never turn it OFF (11-04)
                return _awake("on")
            _sys.run(["xset", "dpms", "force", "off"])
            return "Screen off. Move the mouse to wake it."
        if setting == "stay_awake":
            return _awake(state)
    except _sys.SysError as e:
        return f"error: {e}"
    return f"error: unknown setting {setting!r}"
