"""Rewrite the selected text in place, in any app: select text, say "make this formal" / "fix grammar" /
"translate to Nepali" / "shorten this", and the new text replaces the selection.

X11 keeps the current selection in the PRIMARY buffer, so nothing has to be copied first. The rewrite is one fast
LLM call (~2x the text in tokens); the result is pasted over the still-selected text with the app's paste key, and
the user's clipboard is put back afterwards. If KURAMA's own window is in front (the request was typed in the
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


def rewrite(instruction: str, text: str = "") -> str:
    if text.strip():
        return transform(text[:MAX_CHARS], instruction) or "error: the rewrite came back empty"
    sel = selection()
    if not sel.strip():
        return "Select the text first (highlight it with the mouse), then ask again."
    if len(sel) > MAX_CHARS:
        return f"That selection is too long ({len(sel)} characters, max {MAX_CHARS}). Select a smaller part."
    new = transform(sel, instruction)
    if not new:
        return "error: the rewrite came back empty; nothing was changed"
    old_clip = _xclip(["-selection", "clipboard"])
    _xclip(["-selection", "clipboard"], new)
    wid, in_front = target_window()
    if wid is None and not in_front:
        return "Done. The new text is on your clipboard: click where it should go and press Ctrl+V.\n\n" + new
    if not in_front:  # asked from KURAMA's window: go back to the document (its selection is still there)
        _activate(wid)
        time.sleep(0.35)
    from jarvis.core import uiagent
    paste = "ctrl+shift+v" if uiagent.family(uiagent.active_class()) == "terminal" else "ctrl+v"
    time.sleep(0.15)
    uiagent.key(paste)
    time.sleep(0.4)
    if old_clip:
        _xclip(["-selection", "clipboard"], old_clip)  # leave the user's clipboard as it was
    words = len(new.split())
    return f"Replaced the selected text ({words} words)."
