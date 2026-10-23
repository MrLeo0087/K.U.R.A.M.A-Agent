"""launch_workspace: open a named set of apps and sites from config.WORKSPACES (coding, study...). Safe."""
from __future__ import annotations

import difflib

from jarvis.core import config
from jarvis.core.registry import tool
from jarvis.tools.general import _apps, open_url


def find(name: str) -> str | None:
    q = _apps.clean_query(name)
    q = q.removesuffix(" workspace").removesuffix(" mode").removesuffix(" setup").strip()
    names = list(config.WORKSPACES)
    if q in names:
        return q
    near = difflib.get_close_matches(q, names, n=1, cutoff=0.6)
    if near:
        return near[0]
    return next((n for n in names if q and (q in n or n in q)), None)


@tool(group="apps", safety="safe", description="Launch a named workspace: a set of apps and sites (coding, study, research, writing).")
def launch_workspace(name: str) -> str:
    """Open every app and site of a workspace.

    Args:
        name: Workspace name, e.g. "coding" or "study"; "list" shows the available ones.
    """
    if _apps.clean_query(name) in ("list", "all", "help", ""):
        return "workspaces: " + ", ".join(config.WORKSPACES)
    key = find(name)
    if key is None:
        return f"error: no workspace called {name!r}; available: {', '.join(config.WORKSPACES)}"
    spec = config.WORKSPACES[key]
    opened, missing = [], []
    for app in spec.get("apps", []):
        entry, score = _apps.find_app(app)
        if entry is None or score < _apps.TOOL_MIN_SCORE:
            missing.append(app)
            continue
        try:
            _apps.launch(entry)
            opened.append(entry["name"])
        except RuntimeError:
            missing.append(app)
    for site in spec.get("urls", []):
        url = open_url.resolve(site)
        if url is None:
            missing.append(site)
            continue
        try:
            open_url._open(url)
            opened.append(url)
        except RuntimeError:
            missing.append(site)
    out = f"started the {key} workspace: {', '.join(opened) or 'nothing'}"
    return out + (f"; could not open: {', '.join(missing)}" if missing else "")
