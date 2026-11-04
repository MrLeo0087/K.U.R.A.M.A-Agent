"""Plugin discovery shared by every extension point (agents, memory sources; tools use registry.discover).

A plugin is a module or a sub-package dropped into a package folder. `load(package, attr)` imports each one and
collects `attr` from it. Every plugin is isolated: one that fails to import is logged and listed in `broken()`,
and the others still load. Nothing central has to be edited to add one.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any

log = logging.getLogger("jarvis.plugins")

_broken: dict[str, str] = {}  # module -> error (shown by `broken()`, /health and the laptop doctor)


def names(package: str) -> list[str]:
    """Plugin names in a package WITHOUT importing them (cheap: for listings). '_private' modules are skipped."""
    try:
        pkg = importlib.import_module(package)
    except ImportError as e:
        log.warning("plugin package %s not importable: %s", package, e)
        return []
    return sorted(m.name for m in pkgutil.iter_modules(pkg.__path__) if not m.name.startswith("_"))


def load_one(package: str, name: str, attr: str) -> Any | None:
    """`package.name.attr`, or None (logged once) when the plugin is broken or has no `attr`."""
    mod_name = f"{package}.{name}"
    try:
        mod = importlib.import_module(mod_name)
    except Exception as e:  # noqa: BLE001 - one broken plugin must never stop the others
        if mod_name not in _broken:
            log.error("plugin %s failed to load: %s", mod_name, e)
        _broken[mod_name] = f"{type(e).__name__}: {e}"
        return None
    _broken.pop(mod_name, None)
    got = getattr(mod, attr, None)
    if got is None:
        log.debug("plugin %s has no %s", mod_name, attr)
    return got


def load(package: str, attr: str) -> dict[str, Any]:
    """{name: attr} for every plugin in package that loads and defines attr."""
    out = {}
    for n in names(package):
        if (got := load_one(package, n, attr)) is not None:
            out[n] = got
    return out


def broken() -> dict[str, str]:
    """Plugins that failed to import: {module: error}."""
    return dict(_broken)
