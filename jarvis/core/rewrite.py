"""Rewrite the selected text in place, in any app: select text, say "make this formal" / "fix grammar" /
"translate to Nepali" / "shorten this", and the new text replaces the selection.

KURAMA copies the selection in that app itself (Ctrl+C there; the user copies nothing). The rewrite is one fast
LLM call (~2x the text in tokens); the result is pasted over the still-selected text with the app's paste key and
also left on the clipboard (read-only text can't be replaced in place). If KURAMA's own window is in front (the request was typed in the
dashboard), KURAMA switches back to the window the user was in (the one right below it) and pastes there; the
selection is still highlighted in that app.
"""
from __future__ import annotations

import logging
import subprocess
import time

log = logging.getLogger(__name__)
MAX_CHARS = 6000
_SYS = ("Rewrite the user's text as instructed. Keep the meaning, names, numbers, links and formatting (line "
        "breaks, lists). Output ONLY the rewritten text: no quotes, no notes, no explanation.")


def _xclip(args: list[str], text: str | None = None) -> str:
    try:
        if text is not None:  # xclip forks to serve the selection: don't wait on its pipes
            subprocess.run(["xclip", *args, "-i"], input=text, text=True, timeout=5, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            return ""
        return subprocess.run(["xclip", *args, "-o"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def selection() -> str:
    return _xclip(["-selection", "primary"])


def _is_kurama(name: str, cls: tuple | None) -> bool:
    """KURAMA's own window: the wallpaper/panel app, or a browser tab showing the dashboard (a folder that happens
    to be called KURAMA in the file manager is NOT it)."""
    n, c = (name or "").strip().lower(), str(cls[0]).lower() if cls else ""
    if c.startswith("kurama") or "127.0.0.1:8000" in n or "localhost:8000" in n:
        return True
    return n.startswith("kurama") and any(b in c for b in ("brave", "chrome", "chromium", "firefox"))


def target_window() -> tuple[int | None, bool]:
    """(window to paste into, it_is_the_active_one). When KURAMA's own window is in front (the request was typed in
    the dashboard), the target is the window right below it in the stacking order = where the user just was."""
    try:
        from Xlib import X, display
        d = display.Display()
        root = d.screen().root
        active = root.get_full_property(d.intern_atom("_NET_ACTIVE_WINDOW"), X.AnyPropertyType)
        active_id = active.value[0] if active and len(active.value) else None
        stack = root.get_full_property(d.intern_atom("_NET_CLIENT_LIST_STACKING"), X.AnyPropertyType)
        name_atom = d.intern_atom("_NET_WM_NAME")

        def info(wid: int) -> tuple[str, tuple | None]:
            w = d.create_resource_object("window", wid)
            nm = w.get_full_property(name_atom, 0)
            return (nm.value.decode(errors="replace") if nm else ""), w.get_wm_class()
        if active_id and not _is_kurama(*info(active_id)):
            return active_id, True
        for wid in reversed(list(stack.value) if stack else []):  # top of the stack first
            name, cls = info(wid)
            if name and not _is_kurama(name, cls) and cls and cls[0] not in ("gnome-shell", "desktop_window"):
                return wid, False
    except Exception as e:  # noqa: BLE001 - no Xlib/X: treat the front window as the target
        log.info("window lookup failed: %s", e)
        return None, True
    return None, False


def _activate(wid: int) -> None:
    subprocess.run(["xdotool", "windowactivate", "--sync", str(wid)], capture_output=True, timeout=5)


def transform(text: str, instruction: str) -> str:
    from jarvis.core import llm
    reply = llm.chat([{"role": "system", "content": _SYS},
                      {"role": "user", "content": f"Instruction: {instruction}\n\nText:\n{text}"}],
                     tier="fast", purpose="rewrite", max_tokens=min(3000, len(text) // 2 + 300))
    return (reply.text or "").strip().strip('"“”')


def _window_name(wid: int) -> str:
    try:
        return subprocess.run(["xdotool", "getwindowname", str(wid)], capture_output=True, text=True,
                              timeout=3).stdout.strip()[:60]
    except (OSError, subprocess.SubprocessError):
        return "that window"


def rewrite(instruction: str, text: str = "") -> str:
    """Copy the selection FROM the app the user is working in (Ctrl+C there, not the X PRIMARY buffer, which also
    changes when text is selected inside KURAMA), rewrite it, paste it back over the selection."""
    if text.strip():
        return transform(text[:MAX_CHARS], instruction) or "error: the rewrite came back empty"
    from jarvis.core import uiagent
    wid, in_front = target_window()
    if wid is None:
        return "I couldn't find the window with your text. Highlight the text there, then ask again."
    if not in_front:  # asked from KURAMA's window: go back to the document (its selection is still there)
        _activate(wid)
        time.sleep(0.35)
    term = uiagent.family(uiagent.active_class()) == "terminal"
    sentinel = f"__kurama_copy_{time.time()}__"
    _xclip(["-selection", "clipboard"], sentinel)
    uiagent.key("ctrl+shift+c" if term else "ctrl+c")
    time.sleep(0.35)
    sel = _xclip(["-selection", "clipboard"])
    if not sel.strip() or sel == sentinel:
        sel = selection() if in_front else ""  # some apps only set PRIMARY
    if not sel.strip() or sel == sentinel:
        _xclip(["-selection", "clipboard"], "")
        return (f"I couldn't see any highlighted text in '{_window_name(wid)}'. Highlight the words there (they must "
                "be in a box you can type in, to be replaced), then ask again.")
    if len(sel) > MAX_CHARS:
        return f"That selection is too long ({len(sel)} characters, max {MAX_CHARS}). Select a smaller part."
    new = transform(sel, instruction)
    if not new:
        return "error: the rewrite came back empty; nothing was changed"
    _xclip(["-selection", "clipboard"], new)
    if not in_front:
        _activate(wid)  # the LLM call took a moment: make sure the document is still in front
        time.sleep(0.2)
    uiagent.key("ctrl+shift+v" if term else "ctrl+v")
    time.sleep(0.3)
    return (f"Replaced the highlighted text in '{_window_name(wid)}' ({len(new.split())} words). If it couldn't be "
            f"replaced there (read-only text), it is on your clipboard: press Ctrl+V where you want it.\n\n{new}")
