"""The VS Code editor link (vscode_ext/ + jarvis/core/editor.py) against a fake extension: a state file like the real
one writes, and a tiny HTTP server that edits an in-memory document like VS Code would."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from jarvis.core import assist, browsertab, config, context, editor, rewrite


class FakeVSCode:
    def __init__(self, state_dir: Path, file: Path, text: str):
        self.file, self.text, self.calls = file, text, []
        self.dirty = False
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                ok = self.headers.get("X-Kurama-Token") == "tok"
                out = fake.handle(body) if ok else {"ok": False, "error": "forbidden"}
                data = json.dumps(out).encode()
                self.send_response(200 if ok else 403)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.state = {"v": 1, "pid": os.getpid(), "port": self.server.server_address[1], "token": "tok",
                      "focused_at": 100.0, "workspace": "KURAMA", "root": str(file.parent), "file": str(file),
                      "language": "python", "dirty": False, "selection": "", "sel": None, "cursor": [0, 0],
                      "open": [str(file)]}
        self.path = state_dir / f"{os.getpid()}.json"
        state_dir.mkdir(parents=True, exist_ok=True)
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.state))

    def select(self, start, end):
        lines = self.text.split("\n")
        if start[0] == end[0]:
            sel = lines[start[0]][start[1]:end[1]]
        else:
            sel = "\n".join([lines[start[0]][start[1]:], *lines[start[0] + 1:end[0]], lines[end[0]][:end[1]]])
        self.state.update(selection=sel, sel={"start": list(start), "end": list(end)}, cursor=list(end))
        self.save()

    def _off(self, pos):
        lines = self.text.split("\n")
        return sum(len(x) + 1 for x in lines[:pos[0]]) + pos[1]

    def handle(self, b):
        self.calls.append(b)
        if b["op"] == "text":
            return {"ok": True, "text": self.text, "dirty": self.dirty}
        if b["op"] == "replace_all":
            i, j = 0, len(self.text)
        elif b["op"] == "replace_range":
            i, j = self._off(b["range"][0]), self._off(b["range"][1])
        elif b["op"] == "replace_text":
            if self.text.count(b["old"]) != 1:
                return {"ok": False, "error": "not exactly once"}
            i = self.text.index(b["old"])
            j = i + len(b["old"])
        elif b["op"] == "insert":
            i = j = self._off(b["at"]) if b.get("at") else len(self.text)
        else:
            return {"ok": False, "error": "unknown"}
        if "expect" in b and self.text[i:j] != b["expect"]:
            return {"ok": False, "error": "the text there changed since it was read"}
        self.text = self.text[:i] + b.get("text", "") + self.text[j:]
        return {"ok": True}


@pytest.fixture
def vscode(tmp_path, monkeypatch):
    f = tmp_path / "proj" / "test.py"
    f.parent.mkdir()
    f.write_text("OLD ON DISK\n")
    fake = FakeVSCode(Path(config.VSCODE_STATE_DIR), f, "def add(a, b):\n    return a+b\n\nprint(add(1, 2))\n")
    monkeypatch.setattr(rewrite, "target_window", lambda: (42, False))  # typed in KURAMA: VS Code is right below
    monkeypatch.setattr(rewrite, "_window_name", lambda wid, limit=60: "● test.py - KURAMA - Visual Studio Code"[:limit])
    monkeypatch.setattr(rewrite, "_activate", lambda wid: (_ for _ in ()).throw(AssertionError("no window switching")))
    monkeypatch.setattr(rewrite, "_xclip", lambda args, text=None: "")
    monkeypatch.setattr(config, "CONTEXT", True)
    monkeypatch.setattr(context, "_cache", (0.0, {}))
    yield fake
    fake.server.shutdown()


def test_the_open_file_and_its_unsaved_text_come_from_the_editor(vscode):
    assert assist.open_file_in_editor() == vscode.file
    assert editor.read(vscode.file).startswith("def add")  # the live buffer, not 'OLD ON DISK'


def test_selection_is_exact_and_empty_after_deselect(vscode):
    vscode.select((0, 0), (1, 14))
    g = rewrite.grab()
    assert isinstance(g, rewrite.Grab) and g.text == "def add(a, b):\n    return a+b" and g.editor
    snap = context.snapshot()
    assert snap["selection"] == "def add(a, b):\n    return a+b" and snap["lines"] == (1, 2)
    assert "lines 1-2" in context.line()
    vscode.state.update(selection="", sel={"start": [3, 0], "end": [3, 0]})  # clicked somewhere: nothing selected
    vscode.save()
    assert "Nothing is highlighted in test.py" in rewrite.grab()  # never an old selection
    context._cache = (0.0, {})
    assert context.snapshot()["selection"] == ""


def test_put_replaces_exactly_the_selected_range_and_refuses_if_it_changed(vscode):
    vscode.select((1, 4), (1, 14))
    g = rewrite.grab()
    assert rewrite.put(g, "return a + b")
    assert vscode.text == "def add(a, b):\n    return a + b\n\nprint(add(1, 2))\n"
    vscode.text = vscode.text.replace("return a + b", "return b + a")  # the user edited it meanwhile
    assert not rewrite.put(g, "return 0")  # never pasted over something else
    assert "return b + a" in vscode.text


def test_whole_file_and_pending_change_go_through_the_editor(vscode):
    assert editor.save_text(vscode.file, "x = 1\n") == "editor" and vscode.text == "x = 1\n"
    assert vscode.file.read_text() == "OLD ON DISK\n"  # VS Code saves it, not KURAMA under its feet
    vscode.text = "def f():\n    pass\n"
    assert editor.replace_once(vscode.file, "    pass\n", "    return 1\n") and vscode.text == "def f():\n    return 1\n"
    assert not editor.replace_once(vscode.file, "nope", "x")


def test_without_the_extension_everything_falls_back(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("disk\n")
    assert editor.states() == [] and editor.read(f) == "disk\n"
    assert editor.save_text(f, "new\n") == "disk" and f.read_text() == "new\n"


def test_a_closed_window_is_forgotten(tmp_path):
    d = Path(config.VSCODE_STATE_DIR)
    d.mkdir(parents=True)
    (d / "999999.json").write_text(json.dumps({"pid": 999999, "file": "/x.py"}))
    assert editor.states() == [] and not (d / "999999.json").exists()


def test_browser_highlight_is_used_without_ctrl_c(monkeypatch):
    monkeypatch.setattr(rewrite, "target_window", lambda: (7, False))
    monkeypatch.setattr(rewrite, "_window_name", lambda wid, limit=60: "Photosynthesis - Wikipedia - Brave"[:limit])
    monkeypatch.setattr(rewrite, "_activate", lambda wid: (_ for _ in ()).throw(AssertionError("no window switching")))
    browsertab.put_selection("Plants turn light into sugar.", "https://en.wikipedia.org/wiki/P", "Photosynthesis - Wikipedia")
    g = rewrite.grab()
    assert isinstance(g, rewrite.Grab) and g.text == "Plants turn light into sugar."
    browsertab.put_selection("", "https://en.wikipedia.org/wiki/P", "Photosynthesis - Wikipedia")
    assert browsertab.selection() == ""


def test_read_only_page_text_is_shown_not_pasted(monkeypatch):
    """'format this text' on an AI chat / article: the result is shown (and copied), never a fake 'Replaced'."""
    from jarvis.core import assist
    monkeypatch.setattr(rewrite, "target_window", lambda: (7, False))
    monkeypatch.setattr(rewrite, "_window_name", lambda wid, limit=60: "Notes - Google Gemini - Brave"[:limit])
    monkeypatch.setattr(rewrite, "_activate", lambda wid: (_ for _ in ()).throw(AssertionError("no window switching")))
    monkeypatch.setattr(rewrite, "_xclip", lambda args, text=None: "")
    monkeypatch.setattr(rewrite, "put", lambda g, new: (_ for _ in ()).throw(AssertionError("no paste on a page")))
    monkeypatch.setattr(rewrite, "transform", lambda text, instruction: "## Notes\n- one")
    browsertab.put_selection("notes one two three", "https://gemini.google.com/app/x", "Notes - Google Gemini", editable=False)
    out = assist.run("improve", "format this text into markdown")
    assert "read only" in out and "## Notes" in out and "replace it" not in out
    assert not assist.pending_code_active()  # nothing to put back: no 'replace it' offer


def test_format_shows_first_and_replace_it_puts_it_back(vscode, monkeypatch):
    """Owner: 'format this' -> the result (workspace for a long one), the original untouched; 'replace it' -> in
    place. 'format this and replace it' -> in place at once."""
    from jarvis.core import assist, fastpath
    vscode.text = "notes: teh plan is good\n"
    vscode.select((0, 7), (0, 23))
    monkeypatch.setattr(rewrite, "transform", lambda text, instruction: "The plan is good.")
    out = assist.run("improve", "format this")
    assert "Say 'replace it'" in out and vscode.text == "notes: teh plan is good\n"
    it = fastpath.plan_answer_intent("replace it")
    assert it.args == {"action": "apply_code"}
    assert assist.run("apply_code").startswith("Replaced in test.py") and vscode.text == "notes: The plan is good.\n"
    vscode.text = "notes: teh plan is good\n"
    vscode.select((0, 7), (0, 23))
    assert assist.run("improve", "format this and replace it").startswith("Replaced")
    assert vscode.text == "notes: The plan is good.\n" and not assist.pending_code_active()


def test_translate_and_replace_on_a_read_only_page_says_so(monkeypatch):
    from jarvis.core import assist
    monkeypatch.setattr(rewrite, "target_window", lambda: (7, False))
    monkeypatch.setattr(rewrite, "_window_name", lambda wid, limit=60: "Chat - Google Gemini - Brave"[:limit])
    monkeypatch.setattr(rewrite, "_xclip", lambda args, text=None: "")
    monkeypatch.setattr(rewrite, "put", lambda g, new: (_ for _ in ()).throw(AssertionError("no paste on a page")))
    monkeypatch.setattr(assist, "translate", lambda text, lang: "नमस्ते")
    browsertab.put_selection("hello there", "https://gemini.google.com/app/x", "Chat - Google Gemini", editable=False)
    out = assist.run("translate", "translate into nepali and replace", "ne", True)
    assert "read only" in out and "Replaced" not in out
