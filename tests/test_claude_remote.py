"""Claude Code from Telegram (11-09): a long '/claude say ...' reaches Claude Code (not KURAMA's AI), your
conversations are listed by their own titles and one can be opened by number, '/claude say' marks the
conversation in use (the extension then never leaves a blank copy tab), the extension still parses."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from jarvis.core import claudewatch, config, editor, fastpath


def test_a_long_claude_say_goes_to_claude_code(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    it = fastpath.match("/claude say " + "please continue with the next phase and tell me what changed " * 8)
    assert (it.tool, it.args["action"]) == ("claude_code", "say") and len(it.args["text"]) > 200


def _conv(folder: Path, sid: str, prompt: str, ai: str = "", custom: str = ""):
    rows = [{"type": "user", "cwd": "/home/leo/proj", "message": {"content": prompt}}]
    if ai:
        rows.append({"type": "ai-title", "aiTitle": ai})
    if custom:
        rows.append({"type": "custom-title", "customTitle": custom})
    (folder / f"{sid}.jsonl").write_text("\n".join(json.dumps(r) for r in rows))


def test_conversations_are_listed_by_their_titles_and_one_opens_by_number(tmp_path, monkeypatch):
    proj = tmp_path / ".claude" / "projects" / "p"
    proj.mkdir(parents=True)
    _conv(proj, "a1", "fix the login bug", ai="Login bug fix")
    _conv(proj, "b2", "write tests", ai="Tests", custom="My tests")
    _conv(proj, "c3", "/usage")  # KURAMA's own usage check: never listed
    monkeypatch.setattr(claudewatch, "settings_files", lambda: [tmp_path / ".claude" / "settings.json"])
    text = claudewatch.sessions_text()
    assert "Login bug fix" in text and "My tests" in text and "/usage" not in text
    calls = []
    monkeypatch.setattr(claudewatch, "_window", lambda cwd, min_ext=5: {"root": cwd})
    monkeypatch.setattr(editor, "edit", lambda st, op, **kw: calls.append((op, kw)) or {"ok": True})
    first = json.loads(__import__("jarvis.core.store", fromlist=["x"]).kv_get(claudewatch._PICK_KEY))[0]
    out = claudewatch.open_session("1")
    assert out.startswith("Opened") and calls[0] == ("claude_say", {"session": first["id"], "current": False})
    assert claudewatch._current()["id"] == first["id"]  # /claude say now talks to it


def test_claude_say_marks_the_conversation_in_use(monkeypatch):
    calls = []
    monkeypatch.setattr(claudewatch, "_window", lambda cwd, min_ext=5: {"root": "/x", "workspace": "x"})
    monkeypatch.setattr(editor, "edit", lambda st, op, **kw: calls.append(kw) or {"ok": True, "typed": True})
    monkeypatch.setattr(claudewatch, "_press_enter", lambda ws: True)
    claudewatch._into_vscode({"id": "s1", "cwd": "/x", "prompt": "p"}, "next phase")
    assert calls[0]["current"] is True and calls[0]["session"] == "s1"


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_the_vscode_extension_parses():
    ext = Path(__file__).resolve().parent.parent / "vscode_ext" / "extension.js"
    assert subprocess.run(["node", "--check", str(ext)], capture_output=True).returncode == 0
