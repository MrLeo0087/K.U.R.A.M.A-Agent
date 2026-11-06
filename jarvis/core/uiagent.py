"""Screen agent: control any app's UI (tabs, buttons, menus, settings, typing) — cheapest path first.

Layers (stop at the first that works):
  1. shortcut()  : app-aware keyboard shortcuts ("new tab", "tab 3", "go back", "zoom in")       0 tokens
  2. click_name(): click a button/tab/link whose on-screen name matches what was said             0 tokens
  3. replay      : a free-form task that succeeded before replays its saved steps                 0 tokens
  4. run_task()  : the fast LLM picks the next step from the window's accessibility list (text)   ~600-1000/step
  5. vision      : no accessibility list (some Electron/browser setups) -> screenshot + vision model

The accessibility list comes from scripts/atspi_dump.py run under the SYSTEM python (python3-gi/Atspi) in a
short-lived subprocess, so GObject never stays in KURAMA's memory. Input is sent with xdotool. Clicking anything
that looks risky (send/delete/pay/buy/install/sign out...) asks the user first (safety.ask).
"""
from __future__ import annotations

import base64
import difflib
import io
import json
import logging
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from jarvis.core import config, store

log = logging.getLogger(__name__)
_DUMP = Path(__file__).resolve().parents[2] / "scripts" / "atspi_dump.py"
_SYS_PY = "/usr/bin/python3"
_MACRO = "uimacro:"

# --- app families (by window class) and their shortcuts ---
_FAMILY = (("browser", ("brave", "chrome", "chromium", "firefox", "msedge", "opera", "vivaldi")),
           ("files", ("nautilus", "nemo", "thunar", "caja", "dolphin")),
           ("code", ("code", "vscodium", "cursor")),
           ("terminal", ("terminal", "konsole", "tilix", "kitty", "alacritty", "xterm")))
_APP_WORDS = {"brave": "brave", "chrome": "chrome", "browser": "brave|chrome|firefox", "firefox": "firefox",
              "files": "nautilus", "file manager": "nautilus", "nautilus": "nautilus", "terminal": "terminal",
              "vs code": "code", "vscode": "code", "code": "code", "settings": "gnome-control-center"}

COMMON = {
    "new_tab": "ctrl+t", "close_tab": "ctrl+w", "reopen_tab": "ctrl+shift+t", "next_tab": "ctrl+Tab",
    "prev_tab": "ctrl+shift+Tab", "back": "alt+Left", "forward": "alt+Right", "reload": "F5",
    "zoom_in": "ctrl+plus", "zoom_out": "ctrl+minus", "zoom_reset": "ctrl+0", "find": "ctrl+f",
    "new_window": "ctrl+n", "scroll_down": "Page_Down", "scroll_up": "Page_Up", "top": "ctrl+Home",
    "bottom": "ctrl+End", "copy": "ctrl+c", "paste": "ctrl+v", "cut": "ctrl+x", "select_all": "ctrl+a",
    "undo": "ctrl+z", "redo": "ctrl+shift+z", "save": "ctrl+s", "enter": "Return", "escape": "Escape",
}
FAMILY_KEYS = {
    "browser": {"private_window": "ctrl+shift+n", "address": "ctrl+l", "history": "ctrl+h", "bookmark": "ctrl+d",
                "last_tab": "ctrl+9", "hard_reload": "ctrl+shift+r", "dev_tools": "F12"},
    "files": {"hidden": "ctrl+h", "up": "alt+Up", "home": "alt+Home", "address": "ctrl+l", "reload": "ctrl+r",
              "new_folder": "ctrl+shift+n"},
    "code": {"command_palette": "ctrl+shift+p", "quick_open": "ctrl+p", "sidebar": "ctrl+b",
             "next_tab": "ctrl+Page_Down", "prev_tab": "ctrl+Page_Up", "last_tab": "alt+0"},
    "terminal": {"new_tab": "ctrl+shift+t", "close_tab": "ctrl+shift+w", "copy": "ctrl+shift+c",
                 "paste": "ctrl+shift+v", "next_tab": "ctrl+Page_Down", "prev_tab": "ctrl+Page_Up",
                 "find": "ctrl+shift+f", "new_window": "ctrl+shift+n"},
}
LABELS = {"new_tab": "Opened a new tab", "close_tab": "Closed the tab", "reopen_tab": "Reopened the last tab",
          "next_tab": "Next tab", "prev_tab": "Previous tab", "last_tab": "Last tab", "back": "Went back",
          "forward": "Went forward", "reload": "Reloaded", "hard_reload": "Reloaded (no cache)",
          "zoom_in": "Zoomed in", "zoom_out": "Zoomed out", "zoom_reset": "Zoom reset", "find": "Find bar open",
          "new_window": "Opened a new window", "private_window": "Opened a private window",
          "scroll_down": "Scrolled down", "scroll_up": "Scrolled up", "top": "At the top", "bottom": "At the bottom",
          "copy": "Copied", "paste": "Pasted", "cut": "Cut", "select_all": "Selected all", "undo": "Undone",
          "redo": "Redone", "save": "Saved", "enter": "Pressed Enter", "escape": "Pressed Escape",
          "address": "Address bar focused", "history": "History open", "bookmark": "Bookmarked",
          "dev_tools": "Developer tools toggled", "hidden": "Toggled hidden files", "up": "Went up a folder",
          "home": "Went to Home", "new_folder": "New folder prompt open", "command_palette": "Command palette open",
          "quick_open": "Quick open", "sidebar": "Toggled the sidebar"}

_ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
        "ninth": 9, "1st": 1, "2nd": 2, "3rd": 3}
_IN_APP = r"(?:\s+(?:in|on)\s+(?:the\s+|my\s+)?(?P<app>brave|chrome|firefox|browser|files|file\s+manager|nautilus|" \
          r"terminal|vs\s*code|code))?"
_PL = r"^(?:please\s+|kurama\s+)?"
_END = r"\s*[.!?]*$"
_PHRASES: list[tuple[str, str]] = [
    (r"(?:open\s+|make\s+|create\s+)?(?:a\s+)?new\s+tab", "new_tab"),
    (r"close\s+(?:this\s+|the\s+|current\s+|that\s+)?tab", "close_tab"),
    (r"(?:reopen|restore|bring\s+back|undo\s+close)\s+(?:the\s+)?(?:last\s+)?(?:closed\s+)?tab", "reopen_tab"),
    (r"(?:go\s+to\s+|switch\s+to\s+)?(?:the\s+)?(?:next|right)\s+tab|switch\s+tabs?", "next_tab"),
    (r"(?:go\s+to\s+|switch\s+to\s+)?(?:the\s+)?(?:previous|prev|left)\s+tab", "prev_tab"),
    (r"(?:go\s+to\s+|switch\s+to\s+|open\s+)?(?:the\s+)?last\s+tab", "last_tab"),
    (r"go\s+back|back|previous\s+page|go\s+to\s+(?:the\s+)?previous\s+page", "back"),
    (r"go\s+forward|forward|next\s+page", "forward"),
    (r"(?:reload|refresh)(?:\s+(?:this|the))?(?:\s+(?:page|tab))?", "reload"),
    (r"hard\s+(?:reload|refresh)", "hard_reload"),
    (r"zoom\s+in|make\s+it\s+bigger", "zoom_in"),
    (r"zoom\s+out|make\s+it\s+smaller", "zoom_out"),
    (r"(?:reset|normal)\s+zoom|zoom\s+(?:reset|normal|100)", "zoom_reset"),
    (r"find\s+(?:in|on)\s+(?:this\s+|the\s+)?page", "find"),
    (r"(?:open\s+)?(?:a\s+)?new\s+window", "new_window"),
    (r"(?:open\s+)?(?:a\s+)?(?:new\s+)?(?:private|incognito)\s+(?:window|tab|mode)", "private_window"),
    (r"scroll\s+down(?:\s+a\s+bit)?|page\s+down", "scroll_down"),
    (r"scroll\s+up(?:\s+a\s+bit)?|page\s+up", "scroll_up"),
    (r"(?:go\s+to\s+|scroll\s+to\s+)(?:the\s+)?top(?:\s+of\s+(?:the\s+)?page)?", "top"),
    (r"(?:go\s+to\s+|scroll\s+to\s+)(?:the\s+)?bottom(?:\s+of\s+(?:the\s+)?page)?", "bottom"),
    (r"copy\s+(?:it|this|that|the\s+selection|selection)", "copy"),
    (r"paste(?:\s+(?:it|here|this|that))?", "paste"),
    (r"select\s+all", "select_all"),
    (r"undo(?:\s+(?:that|it))?", "undo"),
    (r"redo(?:\s+(?:that|it))?", "redo"),
    (r"save(?:\s+(?:it|this|the\s+file))", "save"),
    (r"(?:go\s+to\s+|focus\s+)(?:the\s+)?(?:address|url|search)\s+bar", "address"),
    (r"(?:show\s+|open\s+)?(?:browser|browsing)\s+history", "history"),
    (r"bookmark\s+(?:this|it|the\s+page|this\s+page)", "bookmark"),
    (r"(?:open\s+|toggle\s+)?(?:dev(?:eloper)?\s+tools|inspect\s+element)", "dev_tools"),
    (r"(?:show|hide|toggle)\s+hidden\s+files", "hidden"),
    (r"go\s+up(?:\s+(?:a|one)\s+folder)?|(?:go\s+to\s+)?(?:the\s+)?parent\s+folder", "up"),
    (r"(?:open\s+|show\s+)?(?:the\s+)?command\s+palette", "command_palette"),
    (r"quick\s+open", "quick_open"),
    (r"(?:show|hide|toggle)\s+(?:the\s+)?side\s*bar", "sidebar"),
]
_SHORT_RE = [(re.compile(_PL + "(?:" + p + ")" + _IN_APP + _END, re.I), a) for p, a in _PHRASES]
_TAB_N = re.compile(_PL + r"(?:go\s+to\s+|switch\s+to\s+|open\s+|show\s+(?:me\s+)?)?(?:the\s+)?(?:(?P<ord>first|second|"
                    r"third|fourth|fifth|sixth|seventh|eighth|ninth|1st|2nd|3rd|\d)(?:th)?\s+tab|tab\s+(?:number\s+)?"
                    r"(?P<num>\d))" + _IN_APP + _END, re.I)
_PRESS = re.compile(_PL + r"(?:press|hit)\s+(?P<k>[\w\s+-]{1,40}?)(?:\s+key)?" + _IN_APP + _END, re.I)
_TYPE = re.compile(_PL + r"type\s+(?!what\s+i\s+(?:say|speak)\b)(?P<t>.+?)" + _IN_APP + _END, re.I)
_CLICK = re.compile(_PL + r"(?:click|tap|double[\s-]*click)\s+(?:on\s+)?(?:the\s+)?"
                    r"(?!(?:a|my|me|some)?\s*(?:photo|picture|pic|selfie|screenshot|snap)s?\b)(?P<n>.{1,60}?)"
                    r"(?:\s+(?:button|tab|link|option|menu|icon|item|toggle|switch))?" + _IN_APP + _END, re.I)

_KEYWORDS = {"control": "ctrl", "ctrl": "ctrl", "shift": "shift", "alt": "alt", "super": "super",
             "windows": "super", "win": "super", "enter": "Return", "return": "Return", "escape": "Escape",
             "esc": "Escape", "tab": "Tab", "space": "space", "spacebar": "space", "backspace": "BackSpace",
             "delete": "Delete", "del": "Delete", "up": "Up", "down": "Down", "left": "Left", "right": "Right",
             "home": "Home", "end": "End", "page up": "Page_Up", "pageup": "Page_Up", "page down": "Page_Down",
             "pagedown": "Page_Down", "plus": "plus", "minus": "minus", "insert": "Insert"}
_MODS = {"ctrl", "shift", "alt", "super"}
RISKY = re.compile(r"\b(?:send|delete|remove|erase|pay|buy|purchase|order|checkout|transfer|install|uninstall|"
                   r"sign\s*out|log\s*out|format|reset|submit|post|publish|confirm|empty\s+trash|shut\s*down|"
                   r"restart|password|unsubscribe|block)\b", re.I)


# --- low-level input / window helpers ---
def _need() -> str | None:
    return None if shutil.which("xdotool") else "error: xdotool is missing: sudo apt install xdotool"


def _x(*args: str, timeout: float = 5) -> str:
    try:
        r = subprocess.run(["xdotool", *args], capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("xdotool %s failed: %s", args[:2], e)
        return ""


def active_class() -> str:
    return _x("getactivewindow", "getwindowclassname").lower()


def family(cls: str) -> str:
    cls = (cls or "").lower()
    for fam, words in _FAMILY:
        if any(w in cls for w in words):
            return fam
    return "other"


def focus(app: str) -> bool:
    """Bring `app` (a spoken name: brave, files, terminal...) to the front. True if a window matched."""
    if not app:
        return True
    pats = _APP_WORDS.get(app.lower().strip(), app.lower().strip()).split("|")
    try:
        out = subprocess.run(["wmctrl", "-lx"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 3 and any(p in parts[2].lower() for p in pats) and "kurama_wallpaper" not in parts[2].lower():
            subprocess.run(["wmctrl", "-i", "-a", parts[0]], capture_output=True, timeout=5)
            time.sleep(0.35)
            return True
    return False


def to_user_window() -> None:
    """Keys must go to the app the user is working in. When KURAMA's own chat is in front (the request was typed
    there), the window below it gets the keyboard first: 'scroll down' scrolled KURAMA's chat, not the page."""
    from jarvis.core import rewrite
    try:
        wid, in_front = rewrite.target_window()
    except Exception:  # noqa: BLE001 - no X: the front window it is
        return
    if wid and not in_front:
        _x("windowactivate", "--sync", str(wid))
        time.sleep(0.15)


def key(combo: str, times: int = 1) -> None:
    to_user_window()
    for _ in range(max(1, min(times, 30))):
        _x("key", "--clearmodifiers", *combo.split())


def type_text(text: str) -> None:
    _x("type", "--clearmodifiers", "--delay", "12", "--", text, timeout=30)


def click_at(x: int, y: int, double: bool = False) -> None:
    _x("mousemove", "--sync", str(x), str(y), "click", *(["--repeat", "2"] if double else []), "1")


def keys_from_words(words: str) -> str | None:
    """'control shift t' / 'ctrl+t' / 'enter' / 'f5' -> an xdotool key combo, or None if unclear."""
    w = re.sub(r"\s*\+\s*", " ", words.lower().strip())
    w = re.sub(r"\bpage (up|down)\b", r"page\1", w)
    parts, out = w.split(), []
    for p in parts:
        if p in ("and", "then", "the", "key", "keys", "button", "together", "at", "once", "same", "time"):
            continue
        k = _KEYWORDS.get(p) or (p.upper() if re.fullmatch(r"f\d{1,2}", p) else None) or (
            p if re.fullmatch(r"[a-z0-9]", p) else None)
        if not k:
            return None
        out.append(k)
    if out == ["super"]:  # the Super key alone: GNOME's Activities / app launcher
        return "Super_L"
    if not out or all(k in _MODS for k in out):
        return None
    return "+".join(out)


# --- layer 1: shortcuts ---
def parse_shortcut(text: str) -> dict | None:
    """Spoken command -> {"action", "n", "app"} for a 0-token shortcut, or None."""
    t = (text or "").strip()
    if m := _TAB_N.match(t):
        n = int(m.group("num")) if m.group("num") else (_ORD.get(m.group("ord").lower()) or int(m.group("ord")))
        return {"action": "tab", "n": n, "app": m.group("app") or ""}
    for rx, action in _SHORT_RE:
        if m := rx.match(t):
            return {"action": action, "n": 0, "app": m.group("app") or ""}
    return None


def tab_named(name: str, app: str = "") -> str:
    """'switch to the Facebook tab': the browser extension's tab list -> that tab's position -> Ctrl+N (0 tokens)."""
    from jarvis.core import browsertab
    if not browsertab.tabs():
        return ("I can't see the browser's tabs yet: reload the KURAMA tab link extension (brave://extensions, "
                "version 1.3), or say the tab's number ('go to tab 3').")
    t = browsertab.find_tab(name)
    if t is None:
        open_ = ", ".join(x["title"][:30] for x in browsertab.tabs()[:6])
        return f"No open tab matches '{name}'. Open tabs: {open_}."
    if family(active_class()) != "browser" and not focus(app or browsertab.browser_name() or "brave"):
        return "I couldn't find the browser window."
    res = shortcut("tab", t["i"])
    return f"Switched to the {t['title'][:60]} tab." if res.startswith("Switched") else res


def list_tabs() -> str:
    """'what tabs are open': the browser extension's list (0 tokens)."""
    from jarvis.core import browsertab
    tabs = browsertab.tabs()
    if not tabs:
        return "I can't see the browser's tabs (no browser open, or the KURAMA tab link extension needs a reload)."
    return f"{len(tabs)} tabs open:\n" + "\n".join(f"{t['i']}. {t['title'][:70]}" for t in tabs)


def close_tab_named(name: str) -> str:
    """'close the facebook tab': switch to it, close it (Ctrl+W)."""
    switched = tab_named(name)
    if not switched.startswith("Switched"):
        return switched
    key("ctrl+w")
    return switched.replace("Switched to", "Closed", 1)


def tabs_to_close(spec: str, tabs: list[dict], current: int = 0) -> list[int] | str:
    """Which tab positions a request means (or why not): '1,2,3' / '1-5' / 'first second and fourth' /
    'all except 6' / 'all except last' / 'all except youtube' / 'keep youtube' / 'others' (all but the current)."""
    import re
    words = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
             "ninth": 9, "tenth": 10, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
    t = " ".join((spec or "").lower().replace("tabs", "").replace("tab", "").split())
    n = len(tabs)
    last = max((x["i"] for x in tabs), default=0)

    def nums(s: str) -> list[int]:
        out: list[int] = []
        for a, b in re.findall(r"(\d+)\s*(?:-|to)\s*(\d+)", s):
            out += list(range(int(a), int(b) + 1))
        s = re.sub(r"\d+\s*(?:-|to)\s*\d+", " ", s)
        out += [int(x) for x in re.findall(r"\d+", s)]
        out += [words[w] for w in re.findall(r"[a-z]+", s) if w in words]
        if re.search(r"\blast\b", s) and last:
            out.append(last)
        return out
    keep: set[int] = set()
    if m := re.match(r"^(?:all\s+)?(?:except|but|other than|keep(?: only)?|only keep)\s+(.+)$", t) or \
            re.match(r"^all\s+(?:except|but)\s+(.+)$", t):
        rest = m.group(1).strip()
        keep = set(nums(rest))
        if not keep:  # by name: 'keep youtube', 'all except the github one'
            if not tabs:
                return "I can't see the browser's tabs, so I can't tell which ones are " + rest + "."
            keep = {x["i"] for x in tabs if _tab_is(x, rest)}
            if not keep:
                return f"No open tab matches '{rest}', so I closed nothing."
        if not tabs:
            return "I can't see the browser's tabs (reload the KURAMA tab link extension), so I closed nothing."
        return sorted((x["i"] for x in tabs if x["i"] not in keep), reverse=True)
    if t in ("others", "other", "the others", "all others", "all other"):
        if not tabs or not current:
            return "I can't see the browser's tabs, so I closed nothing."
        return sorted((x["i"] for x in tabs if x["i"] != current), reverse=True)
    if t in ("all", "every", "all of them"):
        return "all"
    picked = sorted(set(nums(t)), reverse=True)
    if not picked:
        return ""
    if n and any(i > last for i in picked):
        return f"There are only {n} tabs open."
    return picked


def _tab_is(tab: dict, name: str) -> bool:
    """This tab matches a loose name (site or title), as find_tab does for one tab."""
    import re
    from urllib.parse import urlparse
    key = re.sub(r"[^a-z0-9]+", "", re.sub(r"^(?:the|my)\s+|\s+(?:one|ones|tabs?)$", "", name.lower().strip()))
    hay = re.sub(r"[^a-z0-9]+", "", urlparse(tab.get("url") or "").netloc.lower() + (tab.get("title") or "").lower())
    return bool(key) and key in hay


def close_tabs(spec: str, app: str = "") -> str:
    """Close several browser tabs: by numbers, 'all except N', 'keep youtube'. Highest position first, so the
    numbers don't shift while closing. Never closes the browser itself (11-06: 'close all tabs and keep YouTube'
    closed the whole Brave window). 0 tokens."""
    from jarvis.core import browsertab
    if err := _need():
        return err
    tabs = browsertab.tabs()
    current = next((x["i"] for x in tabs if x.get("url") == (browsertab.get(3600) or ("", ""))[0]), 0)
    which = tabs_to_close(spec, tabs, current)
    if which == "all":  # 'close all tabs' = the browser window; never when the request keeps one ('...keep YouTube')
        import re
        from jarvis.core import safety
        whole = str(safety.context().get("request") or safety.context().get("user_text") or "")
        if re.search(r"\b(?:except|keep|but|only|other than|leave)\b", whole, re.I):
            return "You want to keep some tabs: say which, e.g. 'close all tabs except YouTube'."
        from jarvis.tools.general import _apps
        wins, label = _apps.match_windows(app or browsertab.browser_name() or "browser")
        for w in wins:
            _apps.wmctrl(["-i", "-c", w["id"]])
        return f"Closed all tabs ({label or 'the browser'})." if wins else "No browser window is open."
    if isinstance(which, str):
        return which or "Which tabs? Say their numbers ('close tabs 1, 2 and 3') or 'all except YouTube'."
    if tabs and len(which) >= len(tabs):
        return "That would close every tab (the whole browser). Say which one to keep, e.g. 'all except YouTube'."
    if family(active_class()) != "browser" and not focus(app or browsertab.browser_name() or "brave"):
        return "I couldn't find the browser window."
    for i in which:
        shortcut("tab", i)
        time.sleep(0.15)
        key("ctrl+w")
        time.sleep(0.15)
    left = len(tabs) - len(which) if tabs else None
    return f"Closed {len(which)} tab{'s' if len(which) != 1 else ''} ({', '.join(map(str, sorted(which)))})." + (
        f" {left} left open." if left is not None else "")


def shortcut(action: str, n: int = 0, app: str = "", times: int = 1) -> str:
    if err := _need():
        return err
    if app and not focus(app):
        return f"I couldn't find an open {app} window."
    to_user_window()
    fam = family(active_class())
    if action == "tab":
        if n < 1:
            return "Which tab number?"
        mod = "ctrl" if fam == "browser" else "alt"
        if n <= 8:
            key(f"{mod}+{n}")
        else:  # browsers jump to 1..8; go to 8 then step right
            key(f"{mod}+8")
            for _ in range(n - 8):
                key("ctrl+Tab")
        return f"Switched to tab {n}."
    combo = FAMILY_KEYS.get(fam, {}).get(action) or COMMON.get(action)
    if not combo:
        return f"'{action.replace('_', ' ')}' isn't available here."
    key(combo, times)
    return LABELS.get(action, "Done") + "."


def press(words: str, app: str = "") -> str:
    if err := _need():
        return err
    combo = keys_from_words(words)
    if not combo:
        return f"I don't know the key '{words}'."
    if app and not focus(app):
        return f"I couldn't find an open {app} window."
    key(combo)
    return f"Pressed {combo}."


def type_into(text: str, app: str = "") -> str:
    if err := _need():
        return err
    if app and not focus(app):
        return f"I couldn't find an open {app} window."
    type_text(text)
    return "Typed it."


# --- accessibility snapshot ---
def snapshot(app: str = "") -> dict:
    """{"app","window","items":[...]} of the active window (or `app`), via the system-python AT-SPI helper."""
    want = _APP_WORDS.get(app.lower(), app).split("|")[0] if app else ""
    try:
        r = subprocess.run([_SYS_PY, "-I", str(_DUMP), *([want] if want else [])], capture_output=True,
                           text=True, timeout=8)
        return json.loads(r.stdout or "{}") or {"items": []}
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        log.warning("atspi snapshot failed: %s", e)
        return {"items": []}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def find(items: list[dict], name: str, role: str = "") -> dict | None:
    """Best item for a spoken name: exact > starts-with > contains > fuzzy (0.75). Prefers `role` on ties."""
    want = _norm(name)
    if not want:
        return None
    pool = [i for i in items if not role or i["role"] == role] or items
    scored = []
    for i in pool:
        n = _norm(i["name"])
        if not n:
            continue
        if n == want:
            s = 1.0
        elif n.startswith(want) or (want.startswith(n) and len(n) > 2):
            s = 0.9
        elif f" {want} " in f" {n} ":
            s = 0.85
        else:
            s = difflib.SequenceMatcher(None, want, n).ratio()
        scored.append((s, -len(n), i))
    if not scored:
        return None
    best = max(scored, key=lambda x: (x[0], x[1]))
    return best[2] if best[0] >= 0.75 else None


def _do_click(item: dict, double: bool = False) -> None:
    click_at(item["x"] + item["w"] // 2, item["y"] + item["h"] // 2, double)


def _risky_ok(label: str) -> bool:
    if not RISKY.search(label or ""):
        return True
    from jarvis.core import safety
    return safety.ask(f"Click '{label}'? It may send, delete, pay or change something.")


# --- layer 2: click by name ---
def parse_press(text: str) -> dict | None:
    m = _PRESS.match((text or "").strip())
    if m and keys_from_words(m.group("k")):
        return {"keys": m.group("k").strip(), "app": m.group("app") or ""}
    return None


_THEN_KEY = re.compile(r"[\s,]+(?:and\s+)?(?:then\s+)?(?:press|hit)\s+(?:the\s+)?(?P<k>enter|return|tab)"
                       r"(?:\s+(?:key|button))?[\s.!]*$", re.I)


def parse_type(text: str) -> dict | None:
    m = _TYPE.match((text or "").strip())
    if not m:
        return None
    t = re.sub(r"^(\S+)\s+(?:here|there|in\s+(?:it|here|there))\s*$", r"\1", m.group("t").strip(), flags=re.I)  # 'type hello
    #   here': 'here' is WHERE (11-04 it typed "hello here")
    if k := _THEN_KEY.search(t):  # 'type X then press Enter': type X, then the key (11-02: the words were typed)
        t = t[:k.start()] + ("\t" if k.group("k").lower() == "tab" else "\n")
    return {"text": t.strip(" ").strip("'\""), "app": m.group("app") or ""}


def parse_click(text: str) -> dict | None:
    t = (text or "").strip()
    if m := _CLICK.match(t):
        return {"name": m.group("n").strip(), "app": m.group("app") or "",
                "double": bool(re.match(_PL + r"double", t, re.I))}
    return None


def click_name(name: str, app: str = "", double: bool = False) -> str | None:
    """Click the on-screen element called `name` (0 tokens). None = not found (caller may fall back)."""
    if err := _need():
        return err
    if app and not focus(app):
        return f"I couldn't find an open {app} window."
    snap = snapshot(app)
    item = find(snap.get("items", []), name)
    if not item:
        return None
    if not _risky_ok(item["name"]):
        return "Okay, I didn't click it."
    _do_click(item, double)
    return f"Clicked {item['name']}."


# --- layers 3-5: free-form task ---
class Step(BaseModel):
    """The single next UI step."""
    action: Literal["click", "double_click", "type", "key", "scroll", "done", "fail"] = Field(
        description="click/double_click an item, type text (into item if given), press key combo, scroll up/down, "
                    "done when the task is complete, fail if impossible")
    item: int = Field(-1, description="item number from the list (-1 if none)")
    text: str = Field("", description="text to type, xdotool key combo (ctrl+t, Return), or up/down for scroll")
    say: str = Field("", description="for done/fail: one short sentence for the user")


class VStep(Step):
    x: int = Field(-1, description="click x on the 0-1000 grid")
    y: int = Field(-1, description="click y on the 0-1000 grid")


_SYS = ("You operate a Linux desktop app for the user. Each turn you get the task, steps done so far, and the "
        "window's visible items as 'n|role|name|state'. Reply with the ONE next step. Prefer keyboard shortcuts "
        "when obvious. To fill a field: type with its item number. Say done as soon as the task is complete.")
_VSYS = ("You operate a Linux desktop for the user from a screenshot. Reply with the ONE next step. For a click "
         "give x,y on a 0-1000 grid of the image. Say done as soon as the task is complete.")
_ROLE = {"push button": "btn", "toggle button": "toggle", "check box": "check", "radio button": "radio",
         "menu item": "menu", "check menu item": "menu", "radio menu item": "menu", "page tab": "tab",
         "password text": "password", "combo box": "combo", "list item": "item", "table cell": "cell",
         "spin button": "spin", "tree item": "item", "search box": "search"}


def _compact(items: list[dict], task: str) -> tuple[list[dict], str]:
    """Dedupe, keep the most task-relevant items first (≤ config.UI_MAX_ITEMS), as short lines."""
    seen, uniq = set(), []
    for i in items:
        k = (i["role"], i["name"])
        if k not in seen:
            seen.add(k)
            uniq.append(i)
    words = set(_norm(task).split())
    rel = [i for i in uniq if words & set(_norm(i["name"]).split())]
    rest = [i for i in uniq if i not in rel]
    keep = (rel + rest)[: config.UI_MAX_ITEMS]
    keep.sort(key=lambda i: (i["y"] // 20, i["x"]))  # reading order
    lines = [f"{n}|{_ROLE.get(i['role'], i['role'])}|{i['name'][:50]}|{i.get('state', '')}".rstrip("|")
             for n, i in enumerate(keep)]
    return keep, "\n".join(lines)


def _macro_key(fam: str, task: str) -> str:
    return f"{_MACRO}{fam}:{_norm(task)}"


def _act(step: Step, items: list[dict]) -> str | None:
    """Run one step. Returns an error string, or None on success."""
    item = items[step.item] if 0 <= step.item < len(items) else None
    if step.action in ("click", "double_click"):
        if not item:
            return "no such item"
        if not _risky_ok(item["name"]):
            return "user said no"
        _do_click(item, step.action == "double_click")
    elif step.action == "type":
        if item:
            _do_click(item)
            time.sleep(0.15)
        if RISKY.search(step.text) and not _risky_ok(step.text):
            return "user said no"
        type_text(step.text)
    elif step.action == "key":
        combo = keys_from_words(step.text) or step.text.strip()
        if not re.fullmatch(r"[A-Za-z0-9_+]{1,40}", combo):
            return "bad key"
        key(combo)
    elif step.action == "scroll":
        key("Page_Up" if "up" in step.text.lower() else "Page_Down")
    return None


def _replay(steps: list[dict], app: str) -> bool:
    """Replay saved steps by element NAME (positions change); False as soon as something is missing."""
    for s in steps:
        if s["action"] in ("click", "double_click", "type") and s.get("name"):
            item = find(snapshot(app).get("items", []), s["name"], s.get("role", ""))
            if not item:
                return False
            if s["action"] != "type" and not _risky_ok(item["name"]):
                return False
            _do_click(item, s["action"] == "double_click")
            if s["action"] == "type":
                time.sleep(0.15)
                type_text(s["text"])
        elif s["action"] == "type":
            type_text(s["text"])
        elif s["action"] == "key":
            key(s["text"])
        elif s["action"] == "scroll":
            key("Page_Up" if "up" in s["text"] else "Page_Down")
        time.sleep(0.5)
    return True


def _screenshot_b64() -> str | None:
    try:
        from PIL import Image
        tmp = Path(config.DATA_DIR) / "tmp_screen.png"
        tool = "scrot" if shutil.which("scrot") else "gnome-screenshot"
        argv = ["scrot", "-o", str(tmp)] if tool == "scrot" else ["gnome-screenshot", "-f", str(tmp)]
        subprocess.run(argv, capture_output=True, timeout=10)
        img = Image.open(tmp).convert("RGB")
        img.thumbnail((1280, 1280))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=70)
        tmp.unlink(missing_ok=True)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as e:  # noqa: BLE001 - no screenshot just means no vision step
        log.warning("screenshot for vision failed: %s", e)
        return None


def _screen_size() -> tuple[int, int]:
    out = _x("getdisplaygeometry").split()
    return (int(out[0]), int(out[1])) if len(out) == 2 else (1920, 1080)


def _vision_step(task: str, done: list[str]) -> VStep | None:
    from jarvis.core import llm
    b64 = _screenshot_b64()
    if not b64:
        return None
    msgs = [{"role": "system", "content": _VSYS},
            {"role": "user", "content": [
                {"type": "text", "text": f"Task: {task}\nDone so far: {'; '.join(done) or 'nothing'}"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]
    try:
        return llm.structured(msgs, VStep, tier="vision", purpose="screen_vision", max_tokens=200)
    except Exception as e:  # noqa: BLE001
        log.warning("vision step failed: %s", e)
        return None


def run_task(task: str, app: str = "") -> str:
    """Do a free-form UI task: replay a saved recipe, else let the fast LLM drive it step by step."""
    if err := _need():
        return err
    if app and not focus(app):
        return f"I couldn't find an open {app} window."
    fam = family(active_class())
    mkey = _macro_key(fam, task)
    if saved := store.kv_get(mkey):
        try:
            if _replay(json.loads(saved), app):
                return "Done (from memory, 0 tokens)."
        except (ValueError, KeyError):
            pass
        store.kv_delete(mkey)  # the screen changed; relearn
    from jarvis.core import llm
    done, recipe, used_vision = [], [], False
    for _ in range(config.UI_MAX_STEPS):
        snap = snapshot(app)
        items, listing = _compact(snap.get("items", []), task)
        if items:
            msgs = [{"role": "system", "content": _SYS},
                    {"role": "user", "content": f"Task: {task}\nApp: {snap.get('app', '')} - "
                                                f"{snap.get('window', '')[:60]}\nDone so far: "
                                                f"{'; '.join(done) or 'nothing'}\nItems:\n{listing}"}]
            try:
                step = llm.structured(msgs, Step, tier=config.UI_TIER, purpose="screen_agent", max_tokens=200)
            except Exception as e:  # noqa: BLE001
                return f"I couldn't plan the next step ({e})."
        else:
            step = _vision_step(task, done)
            used_vision = True
            if step is None:
                return ("I can't see this app's buttons. For browsers/VS Code say 'enable screen control' once and "
                        "restart that app.")
        if step.action == "done":
            if recipe and not used_vision:
                store.kv_set(mkey, json.dumps(recipe))
            return step.say or "Done."
        if step.action == "fail":
            return step.say or "I couldn't do that on this screen."
        if isinstance(step, VStep) and not items:
            if step.action in ("click", "double_click"):
                if step.x < 0 or step.y < 0:
                    return "I couldn't find where to click."
                w, h = _screen_size()
                if not _risky_ok(step.say or task):
                    return "Okay, I stopped."
                click_at(step.x * w // 1000, step.y * h // 1000, step.action == "double_click")
                err = None
            else:
                err = _act(step, [])
        else:
            err = _act(step, items)
        if err == "user said no":
            return "Okay, I stopped."
        it = items[step.item] if 0 <= step.item < len(items) else None
        done.append(f"{step.action} {it['name'] if it else step.text}"[:60] + (f" ({err})" if err else ""))
        if not err:
            recipe.append({"action": step.action, "text": step.text,
                           **({"name": it["name"], "role": it["role"]} if it else {})})
        time.sleep(0.6)
    return f"I stopped after {config.UI_MAX_STEPS} steps; it may be partly done."


def enable_accessibility() -> str:
    """Let browsers/Electron apps expose their buttons to the screen agent (they read this at startup)."""
    from jarvis.tools.general import _desk
    if err := _desk.need_gsettings():
        return err
    _desk.gs_set("org.gnome.desktop.interface", "toolkit-accessibility", "true")
    return ("Screen control enabled. Restart Brave/Chrome/VS Code once so they expose their buttons; other apps "
            "work already.")
