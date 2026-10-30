"""Rewrite the selected text in place, in any app: select text, say "make this formal" / "fix grammar" /
"translate to Nepali" / "shorten this", and the new text replaces the selection.

KURAMA copies the selection in that app itself (Ctrl+C there; the user copies nothing). The rewrite is one fast
LLM call (~2x the text in tokens); the result is pasted over the still-selected text with the app's paste key and
also left on the clipboard (read-only text can't be replaced in place). If KURAMA's own window is in front (the request was typed in the
dashboard), KURAMA switches back to the window the user was in (the one right below it) and pastes there; the
selection is still highlighted in that app.

Typed requests: the copy-history worker also watches the X PRIMARY selection and remembers the newest text the
user highlighted OUTSIDE KURAMA (memory only, SELECTION_MEMORY_S), with the window it was in. So "what does this
mean" typed in KURAMA's chat knows the word without switching windows or pressing Ctrl+C (that sometimes landed in
another VS Code pane or found the highlight gone), and selecting text inside KURAMA never replaces it.
"""
from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

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


def _window_name(wid: int, limit: int = 60) -> str:
    try:
        return subprocess.run(["xdotool", "getwindowname", str(wid)], capture_output=True, text=True,
                              timeout=3).stdout.strip()[:limit]
    except (OSError, subprocess.SubprocessError):
        return "that window"


# the newest selection made OUTSIDE KURAMA (set by the clipboard_watch worker in the same process)
_LAST: dict = {"text": "", "wid": None, "title": "", "cls": "", "ts": 0.0, "kurama_newer": False, "watching": False}


def remember_selection(text: str, wid: int | None, title: str, cls: str, in_kurama: bool) -> None:
    """Called on every PRIMARY change (debounced). Inside KURAMA only flags that PRIMARY is now KURAMA's."""
    _LAST["watching"] = True
    if in_kurama:
        _LAST["kurama_newer"] = True
        return
    if text.strip():
        _LAST.update(text=text, wid=wid, title=title, cls=cls, ts=time.time(), kurama_newer=False)


def remembered() -> "Grab | None":
    """The selection the user made outside KURAMA before typing the request (None: nothing fresh / not watching)."""
    from jarvis.core import config, uiagent
    if not _LAST["watching"] or not _LAST["ts"] or time.time() - _LAST["ts"] > config.SELECTION_MEMORY_S:
        return None
    text = _LAST["text"]
    if not _LAST["kurama_newer"]:  # PRIMARY still belongs to that app: its current text is the freshest
        cur = selection()
        if cur.strip():
            text = cur
    if not text.strip() or len(text) > MAX_CHARS:
        return None
    return Grab(text, _LAST["wid"], False, uiagent.family(_LAST["cls"]) == "terminal", _LAST["title"] or "that window")


def _from_browser(wid: int, in_front: bool) -> "Grab | None":
    """A browser with the KURAMA extension: the text highlighted on its page (no window switch, no Ctrl+C)."""
    from jarvis.core import browsertab
    title = _window_name(wid, limit=400)
    if not any(b in title for b in ("Brave", "Chrome", "Chromium")):
        return None
    text = browsertab.selection(title)
    return Grab(text, wid, in_front, False, _window_name(wid)) if text.strip() and len(text) <= MAX_CHARS else None


class Grab:
    """The highlighted text, copied from the app the user works in, and where it came from."""

    def __init__(self, text: str, wid: int | None, in_front: bool, term: bool, title: str, editor: dict | None = None):
        self.text, self.wid, self.in_front, self.term, self.title = text, wid, in_front, term, title
        self.editor = editor  # VS Code with the editor link: its state when grabbed (file, selection range)


def _from_editor(wid: int, in_front: bool) -> "Grab | str | None":
    """VS Code with the editor link: the exact selection (no window switch, no Ctrl+C), or why there is none.
    None: not VS Code / no link (the caller uses the old way)."""
    from jarvis.core import editor
    title = _window_name(wid, limit=400)
    st = editor.for_window(title)
    if st is None:
        return None
    name = Path(st.get("file") or "").name or "VS Code"
    if not (st.get("selection") or "").strip():
        if (st.get("selection_chars") or 0) > 0:
            return f"That selection in {name} is too long ({st['selection_chars']} characters). Select a smaller part."
        return f"Nothing is highlighted in {name}. Select the code or text there, then ask again."
    return Grab(st["selection"], wid, in_front, False, _window_name(wid), editor=st)


def grab() -> Grab | str:
    """Copy the selection FROM the app the user is working in (Ctrl+C there, not the X PRIMARY buffer, which also
    changes when text is selected inside KURAMA). Returns a Grab, or a message for the user."""
    from jarvis.core import uiagent
    wid, in_front = target_window()
    if wid is not None and (ed := _from_editor(wid, in_front)) is not None:
        return ed
    if wid is not None and (br := _from_browser(wid, in_front)) is not None:
        return br
    if not in_front and (mem := remembered()):  # typed in KURAMA: what was highlighted out there, no switching
        return mem
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
    title = _window_name(wid)
    if not sel.strip() or sel == sentinel:
        _xclip(["-selection", "clipboard"], "")
        return f"I couldn't see any highlighted text in '{title}'. Highlight it there, then ask again."
    if len(sel) > MAX_CHARS:
        return f"That selection is too long ({len(sel)} characters, max {MAX_CHARS}). Select a smaller part."
    return Grab(sel, wid, in_front, term, title)


def grab_cursor() -> Grab | str:
    """The window to type into at the cursor (no selection needed): the front app, or the one below KURAMA."""
    from jarvis.core import uiagent
    wid, in_front = target_window()
    if wid is None:
        return "I couldn't find the editor window. Click where the code should go, then ask again."
    from jarvis.core import editor
    if (st := editor.for_window(_window_name(wid, limit=400))) is not None:  # the editor link inserts at its cursor
        return Grab("", wid, in_front, False, _window_name(wid), editor=st)
    if not in_front:
        _activate(wid)
        time.sleep(0.35)
    term = uiagent.family(uiagent.active_class()) == "terminal"
    return Grab("", wid, in_front, term, _window_name(wid))


def put(g: Grab, new: str) -> bool:
    """Paste `new` over the (still highlighted) selection / at the cursor of the grabbed window; it also stays on
    the clipboard. VS Code with the editor link: replaced in the editor itself, exactly the range that was selected
    (even if the cursor moved meanwhile), one Ctrl+Z undoes it."""
    from jarvis.core import uiagent
    _xclip(["-selection", "clipboard"], new)
    if g.editor is not None:
        from jarvis.core import editor
        st, f = g.editor, g.editor.get("file") or ""
        r = (editor.edit(st, "replace_range", file=f, range=[st["sel"]["start"], st["sel"]["end"]], expect=g.text, text=new)
             if g.text and st.get("sel") else editor.edit(st, "insert", file=f, at=st.get("cursor"), text=new))
        if r.get("ok"):
            return True
        log.info("editor link edit failed: %s", r.get("error"))
        return False  # the code changed under it: never paste over whatever is selected now (it's on the clipboard)
    if not g.in_front and g.wid is not None:
        _activate(g.wid)  # the LLM call took a moment: make sure the document is still in front
        time.sleep(0.2)
    uiagent.key("ctrl+shift+v" if g.term else "ctrl+v")
    time.sleep(0.3)
    return True


def rewrite(instruction: str, text: str = "") -> str:
    """Rewrite the highlighted text and paste the new version over it."""
    if text.strip():
        return transform(text[:MAX_CHARS], instruction) or "error: the rewrite came back empty"
    g = grab()
    if isinstance(g, str):
        return g
    new = transform(g.text, instruction)
    if not new:
        return "error: the rewrite came back empty; nothing was changed"
    if not put(g, new):
        return f"The text in '{g.title}' changed meanwhile, so I didn't replace it: the new text is on your clipboard.\n\n{new}"
    return (f"Replaced the highlighted text in '{g.title}' ({len(new.split())} words). If it couldn't be "
            f"replaced there (read-only text), it is on your clipboard: press Ctrl+V where you want it.\n\n{new}")
