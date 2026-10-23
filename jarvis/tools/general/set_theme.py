"""set_theme: switch GNOME between light and dark mode without touching icon/cursor themes. Safe.

Sets org.gnome.desktop.interface color-scheme (prefer-light / prefer-dark). If the current GTK
(and GNOME Shell user) theme has a matching -Light/-Dark sibling installed (e.g. WhiteSur-Dark ->
WhiteSur-Light), it switches to that sibling too, so custom themes keep their look.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from jarvis.core.registry import tool
from jarvis.tools.general import _sys

IFACE = "org.gnome.desktop.interface"
SHELL_THEME = "org.gnome.shell.extensions.user-theme"
THEME_DIRS = (Path.home() / ".themes", Path.home() / ".local/share/themes", Path("/usr/share/themes"))
_SUFFIX = re.compile(r"([-_ ])(dark|light)(?=$|[-_])", re.I)


def _get(schema: str, key: str) -> str | None:
    try:
        return _sys.run(["gsettings", "get", schema, key], timeout=4).strip().strip("'")
    except _sys.SysError:
        return None


def _set(schema: str, key: str, value: str) -> None:
    _sys.run(["gsettings", "set", schema, key, value], timeout=4)


def _installed(name: str) -> bool:
    return any((d / name).is_dir() for d in THEME_DIRS)


def sibling(theme: str, mode: str, exists=_installed) -> str | None:
    """'WhiteSur-Dark' -> 'WhiteSur-Light' (if installed); Yaru <-> Yaru-dark; else None."""
    if _SUFFIX.search(theme):
        word = "Light" if mode == "light" else "Dark"
        cand = _SUFFIX.sub(lambda m: m.group(1) + (word if m.group(2)[0].isupper() else word.lower()),
                           theme, count=1)
    elif mode == "dark":
        cand = theme + ("-dark" if theme.islower() or theme.startswith("Yaru") else "-Dark")
    else:
        return None
    return cand if cand != theme and exists(cand) else None


def current_mode() -> str:
    scheme = _get(IFACE, "color-scheme") or ""
    return "dark" if "dark" in scheme else "light"


@tool(group="display", safety="safe",
      description="Switch the desktop between light mode and dark mode (keeps your icons and cursor).")
def set_theme(mode: Literal["light", "dark", "toggle", "status"] = "toggle") -> str:
    """Light/dark mode.

    Args:
        mode: light, dark, toggle, or status (just report the current mode).
    """
    if not _sys.which("gsettings"):
        return "error: gsettings not found (GNOME settings tool)"
    now = current_mode()
    if mode == "status":
        return f"The desktop is in {now} mode."
    target = ("light" if now == "dark" else "dark") if mode == "toggle" else mode
    try:
        _set(IFACE, "color-scheme", "prefer-dark" if target == "dark" else "prefer-light")
        changed = []
        gtk = _get(IFACE, "gtk-theme")
        if gtk and (new := sibling(gtk, target)):
            _set(IFACE, "gtk-theme", new)
            changed.append(new)
        shell = _get(SHELL_THEME, "name")
        if shell and (new := sibling(shell, target)):
            _set(SHELL_THEME, "name", new)
    except _sys.SysError as e:
        return f"error: could not switch to {target} mode ({e})"
    extra = f" (theme {changed[0]})" if changed else ""
    return f"Switched to {target} mode{extra}."
