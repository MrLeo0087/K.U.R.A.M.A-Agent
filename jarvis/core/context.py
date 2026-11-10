"""What is open right now (0 tokens to collect, ~30 to send): the file open in VS Code and the code selected in it,
or the browser's tab. Read only — nothing is clicked or typed. The selection is X's PRIMARY buffer, trusted only
when it is really in the open file (so text highlighted elsewhere, or in KURAMA, never counts).
"""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

_cache: tuple[float, dict] = (0.0, {})


def _primary() -> str:
    if not shutil.which("xclip"):
        return ""
    try:
        r = subprocess.run(["xclip", "-o", "-selection", "primary"], capture_output=True, text=True, timeout=0.5)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _lines(st: dict) -> tuple[int, int] | None:
    """The selected lines, 1-based ((12, 30)), or None when nothing is selected."""
    sel = st.get("sel") if st.get("selection") else None
    if not sel:
        return None
    end = sel["end"][0] - (1 if sel["end"][1] == 0 and sel["end"][0] > sel["start"][0] else 0)
    return sel["start"][0] + 1, end + 1


def snapshot() -> dict:
    """{'file': Path|None, 'selection': str, 'tab': (url, title)|None}; cached for 2 s (one per request)."""
    global _cache
    if time.monotonic() - _cache[0] < 2:
        return _cache[1]
    out: dict = {"file": None, "selection": "", "tab": None}
    from jarvis.core import config
    if not config.CONTEXT:
        return out
    try:
        from jarvis.core import assist, editor
        if (st := editor.target()) is not None:  # the editor link: exact file, selection (or none), unsaved edits
            if st.get("file"):
                out.update(file=Path(st["file"]), selection=(st.get("selection") or "").strip(),
                           lines=_lines(st), dirty=bool(st.get("dirty")), exact=True, root=st.get("root") or "")
        else:
            f = assist.open_file_in_editor()
            if f is not None and f.is_file():
                out["file"] = f
                sel = _primary().strip()
                if sel and len(sel) < 20000 and sel in f.read_text(errors="replace"):
                    out["selection"] = sel
    except Exception:  # noqa: BLE001 - context is a bonus, never a failure
        pass
    if out["file"] is None:
        try:
            from jarvis.core import browsertab
            out["tab"] = browsertab.get(600)
            if out["tab"] is not None:
                out["page_selection"] = browsertab.selection().strip()
        except Exception:  # noqa: BLE001
            pass
    from jarvis.tools.interactive import _secrets
    if out["file"] is not None and _secrets.private(out.get("selection", ""), out["file"]):
        out.update(file=None, selection="", private=True)  # .env / keys: never in a prompt, never "this"
    elif out.get("page_selection") and _secrets.private(out["page_selection"]):
        out["page_selection"] = ""
    _cache = (time.monotonic(), out)
    return out


def line() -> str:
    """One short sentence for the system prompt ('' when nothing useful is open)."""
    top = None
    try:  # the app the user used LAST decides what "this" means (with VS Code always open, the browser tab used to
        from jarvis.core import filemanager  # be hidden: "save this link" saved an old link from the chat)
        st = filemanager.state()
        top = st.get("top")
        if fm := filemanager.line():
            return fm
    except Exception:  # noqa: BLE001
        pass
    if top == "browser" and (tab := _tab_line()):
        return tab
    s = snapshot()
    if s["file"] is not None:
        txt = f"Open in VS Code: {s['file'].name} ({s['file'].parent.name})."
        if s.get("root"):
            txt += f" Its project folder: {s['root']} (new files 'in this project/VS Code' go there)."
        if s["selection"]:
            sel = " ".join(s["selection"].split())
            where = f" (lines {s['lines'][0]}-{s['lines'][1]})" if s.get("lines") else ""
            txt += f" Selected{where}: `{sel[:160]}{'…' if len(sel) > 160 else ''}` — 'this/it/the code' means it;" \
                   " to change it use text edit_code."
        else:
            txt += " 'this code/file' means it; to change it use text edit_code."
        txt += " To write code into it (generate + write, like an editor): text code_to_file with the user's words."
        return txt
    if s["tab"]:
        txt = f"Open in the browser: {s['tab'][1][:80]} ({s['tab'][0][:100]}) — 'this page/link/video' means it."
        if sel := " ".join((s.get("page_selection") or "").split()):
            txt += f" Highlighted on the page: `{sel[:160]}{'…' if len(sel) > 160 else ''}` — 'this/it/the text' means it."
        return txt
    return ""


def _tab_line() -> str:
    """The browser tab line from the extension (url + title), '' when there is none."""
    try:
        from jarvis.core import browsertab
        tab = browsertab.get()
        if not tab:
            return ""
        txt = f"Open in the browser: {tab[1][:80]} ({tab[0][:150]}) — 'this page/link/website' means it."
        from jarvis.tools.interactive import _secrets
        if (sel := " ".join((browsertab.selection() or "").split())) and not _secrets.private(sel):
            txt += f" Highlighted on the page: `{sel[:160]}{'…' if len(sel) > 160 else ''}`."
        return txt
    except Exception:  # noqa: BLE001
        return ""


def editor_open() -> bool:
    return snapshot()["file"] is not None


def _norm(t: str) -> str:
    return " ".join((t or "").split())


def latest_selection() -> dict:
    """The text the owner highlighted LAST, wherever it is (11-10: 'ask Gemini to explain this sentence' sent the code
    still selected in VS Code, and 'explain the code' sent nothing). Candidates: the browser highlight (extension,
    with its time), each VS Code window's selection (with its time), and X11's PRIMARY selection, which is always the
    newest highlight in ANY app (VS Code and Brave set it too; Ctrl+C copies are NOT it). PRIMARY decides: the
    candidate it equals wins; a PRIMARY that matches none is a highlight in another app (a PDF viewer, a terminal).
    Without PRIMARY, the newest timestamp wins. Returns {'text', 'source': browser|editor|screen|'', 'ts', ...}."""
    import time
    from jarvis.core import browsertab, config, editor
    now = time.time()
    cands = []
    sel = browsertab.selection_context()
    if sel.get("text", "").strip() and now - float(sel.get("ts") or 0) <= config.SELECTION_MEMORY_S:
        cands.append({**sel, "source": "browser", "ts": float(sel.get("ts") or 0)})
    try:
        for st in editor.states():
            if (st.get("selection") or "").strip() and st.get("file") and now - float(st.get("ts") or 0) <= config.SELECTION_MEMORY_S:
                cands.append({"text": st["selection"], "source": "editor", "ts": float(st.get("ts") or 0),
                              "file": st["file"], "root": st.get("root") or "", "lines": _lines(st)})
    except Exception:  # noqa: BLE001 - the editor link is a bonus
        pass
    prim = _primary().strip()
    if prim and len(prim) < 20000:
        p = _norm(prim)
        hit = [c for c in cands if _norm(c["text"]) == p] or [c for c in cands if p and p in _norm(c["text"])]
        if hit:
            return max(hit, key=lambda c: c["ts"])
        return {"text": prim, "source": "screen", "ts": now}
    return max(cands, key=lambda c: c["ts"]) if cands else {"text": "", "source": "", "ts": 0.0}
