"""apps: open apps, websites and folders by name; close, force-kill, arrange windows, press keys (safe dispatcher)."""
from __future__ import annotations

import re
from typing import Literal

from jarvis.core.registry import tool
from jarvis.tools.core._hub import Act, run


def _open(a: dict) -> tuple[str, dict]:
    """One name -> website, folder or app: a URL / known site / domain is a site; a folder that exists and is not an
    app is the file manager; everything else is an app ('open tara' = the Tara folder, 'open brave' = the app)."""
    name = (a.get("target") or "").strip()
    if re.search(r"\b(?:vs\s*code|vscode|visual\s+studio\s+code|code|editor)\b", a.get("how") or "", re.I):
        return "open_path", {"path": name, "app": "vscode"}  # 'open Downloads in VS Code'
    other = (a.get("text") or "").strip()
    if re.fullmatch(r"(?:vs\s*code|vscode|visual\s+studio\s+code|code)", name, re.I) and other:
        return "open_path", {"path": other, "app": "vscode"}  # target=VS Code + the folder in text: open THAT folder
    from jarvis.tools.general import _apps, open_url
    if re.search(r"\b(?:website|site|\.com|\.org|https?://|www\.)", name, re.I) or open_url.resolve(name):
        return "open_url", {"target": name}
    if re.search(r"\bfolder\b", name, re.I):
        return "open_folder", {"name": re.sub(r"\s*\bfolder\b", "", name, flags=re.I).strip()}
    entry, score = _apps.find_app(name)
    if score < 70:
        from jarvis.core.paths import smart_path
        if smart_path(name, want="dir") is not None:
            return "open_folder", {"name": name}
    return "open_app", {"name": name}


TABLE = {
    "open": _open,
    "close": Act("close_app", lambda a: {"name": a.get("target")}),
    "kill": Act("kill_app", lambda a: {"name": a.get("target"), "force": True}),
    "window": Act("window", lambda a: {"action": a.get("how", "focus"), "name": a.get("target")}),
    "tab": Act("app_control", lambda a: {"action": "shortcut", "text": (  # no tab named: list them (was 'tab:None')
        f"tab:{t}" if (t := (a.get('target') or a.get('text') or "").strip()) else "tabs")}),
    "press": Act("app_control", lambda a: {"action": "press", "text": a.get("text") or a.get("target")}),
    "type": Act("app_control", lambda a: {"action": "type", "text": a.get("text"), "app": a.get("target")}),
    "click": Act("app_control", lambda a: {"action": "click", "text": a.get("text") or a.get("target")}),
    "install": Act("install_app", lambda a: {"action": a.get("how", "install"), "name": a.get("target")}),
    "name": Act("app_name", lambda a: {"name": a.get("target"), "app": a.get("text", "")}),
}


@tool(group="core", safety="safe",
      description="Open an app, website or folder by name; close or force-kill an app; arrange a window "
                  "(minimize/maximize/left/right/focus, or the home screen = desktop); switch to a browser tab by name or number (tab); press keys, type or click in the app in front; install an app; "
                  "name (remember which app a word means: 'when I say browser, open Brave').")
def apps(action: Literal["open", "close", "kill", "window", "tab", "press", "type", "click", "install", "name"], target: str = "",
         how: str = "", text: str = "") -> str:
    """Apps, websites, folders and windows.

    Args:
        action: open, close, kill (force), window, tab (switch to a browser tab: target = its name or number; no target = list the open tabs), press
            (keys like 'ctrl+v', 'enter'), type, click, install, name (target = the word the user says, text = the
            app it opens; empty text forgets the word).
        target: App / website / folder name ('brave', 'youtube', 'tara'), or several sites 'youtube, facebook'.
        how: open: the app to open it IN ('vscode' for a folder/file in VS Code); window: focus, minimize, maximize,
            left, right, restore, list, desktop (go to the home screen); install: install, remove, search, update.
        text: What to type, the keys to press, or what to click.
    """
    if action == "open" and re.search(r",|\band\b", target or "") and all(len(p.split()) <= 3 for p in re.split(r",|\band\b", target)):
        return "\n".join(run(TABLE, {"action": "open", "target": p.strip()}) for p in re.split(r",|\band\b", target) if p.strip())
    return run(TABLE, {"action": action, "target": target, "how": how, "text": text})
