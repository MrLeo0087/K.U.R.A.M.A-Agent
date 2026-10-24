"""laptop_toggle: the laptop's quick switches: Wi-Fi, Bluetooth, airplane mode, power mode, screen off. Safe."""
from __future__ import annotations

from typing import Literal

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


@tool(group="system", safety="safe",
      description="Laptop switches: Wi-Fi, Bluetooth, airplane mode on/off, power mode (saver/balanced/performance), screen off.")
def laptop_toggle(setting: Literal["wifi", "bluetooth", "airplane", "power_mode", "screen"],
                  state: str = "status") -> str:
    """Turn a laptop setting on/off or read it.

    Args:
        setting: wifi, bluetooth, airplane, power_mode or screen.
        state: on / off / status; for power_mode: saver, balanced or performance; for screen: off.
    """
    state = (state or "status").lower().strip()
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
            _sys.run(["xset", "dpms", "force", "off"])
            return "Screen off. Move the mouse to wake it."
    except _sys.SysError as e:
        return f"error: {e}"
    return f"error: unknown setting {setting!r}"
