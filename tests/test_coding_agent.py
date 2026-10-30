"""The coding agent (jarvis/agents): off by default, on by command; crash -> fix as a reviewed change -> yes applies
+ runs again -> undo; the ChatGPT/Gemini bridge; new projects. LLM, terminal and subprocesses are faked."""
import time
from pathlib import Path

import pytest

from jarvis import agents
from jarvis.agents.coding import blocks, bridge, changes, fixer, project, terminal
from jarvis.core import config, fastpath, llm

TB = '''Traceback (most recent call last):
  File "{f}", line 3, in <module>
    print(total(None))
  File "{f}", line 2, in total
    return sum(xs)
TypeError: 'NoneType' object is not iterable
'''


@pytest.fixture
def proj(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "app.py").write_text("def total(xs):\n    return sum(xs)\nprint(total(None))\n")
    monkeypatch.setattr(config, "FASTPATH", True)
    monkeypatch.setattr(bridge, "project_root", lambda: root)
    ran = []
    monkeypatch.setattr(terminal, "run_again", lambda cmd, cwd="": ran.append(cmd) or f"Running `{cmd}` again…")
    return root, ran


def test_off_by_default_and_switched_by_command(tmp_path):
    assert agents.current() == "general" and fastpath.coding_intent("fix it") is None
    it = fastpath.match("start coding agent")
    assert it.tool == "_agent" and it.args == {"name": "coding"}
    assert "Coding agent on" in agents.switch("coding") and agents.current() == "coding"
    assert config.AGENT_MARKER.read_text() == "coding"  # the VS Code extension watches the terminal only now
    assert fastpath.match("stop coding agent").args == {"name": "general"}
    assert "General" in agents.switch("general") and not config.AGENT_MARKER.exists()
    agents.switch("coding")
    agents._last_use[0] = time.time() - config.AGENT_IDLE_OFF_S - 1  # unused for too long: off by itself
    assert agents.current() == "general"


def test_crash_is_announced_fixed_after_yes_and_undone(proj, monkeypatch):
    root, ran = proj
    agents.switch("coding")
    ev = terminal.record("python app.py", str(root), 1, TB.format(f=root / "app.py"))
    assert "TypeError" in ev["text"] and "app.py line 2" in ev["text"] and "fix it" in ev["text"]
    sent = []
    monkeypatch.setattr(llm, "chat", lambda msgs, **k: sent.append(msgs) or llm.Reply(
        "CAUSE: total() gets None.\n```python\n# file: app.py\ndef total(xs):\n    return sum(xs or [])\n```", "m"))
    out = fixer.fix()
    assert out.startswith("Cause: total() gets None.") and "app.py (+1 −1)" in out and "Say yes" in out
    assert "return sum(xs)" in sent[0][1]["content"]  # the user's code went with the error
    assert (root / "app.py").read_text().count("sum(xs)") == 1  # nothing changed before the yes
    assert fastpath.coding_intent("yes").args == {"action": "yes"}
    assert changes.apply().startswith("Applied to app.py") and ran == ["python app.py"]
    assert "sum(xs or [])" in (root / "app.py").read_text() and "print(total(None))" in (root / "app.py").read_text()
    assert changes.undo().startswith("Undone") and "sum(xs)\n" in (root / "app.py").read_text()


def test_missing_module_is_installed_without_the_ai(proj, monkeypatch):
    root, ran = proj
    monkeypatch.setattr(llm, "chat", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no AI for this")))
    terminal.record("python app.py", str(root), 1, "Traceback...\nModuleNotFoundError: No module named 'cv2'")
    assert "opencv-python" in fixer.fix()
    assert "Running" in changes.apply() and ran[-1].endswith("pip install opencv-python && python app.py")


def test_bridge_prompt_and_applying_a_pasted_answer(proj, monkeypatch):
    root, _ = proj
    clip = {}
    monkeypatch.setattr("jarvis.core.rewrite._xclip", lambda args, text=None: clip.__setitem__("c", text) if text else clip.get("a", ""))
    terminal.record("python app.py", str(root), 1, TB.format(f=root / "app.py"))
    out = bridge.pack("fix this error", "")
    assert out.startswith("Copied a ready prompt") and "TypeError" in clip["c"] and "app.py" in clip["c"]
    assert "# file:" in clip["c"]  # it tells ChatGPT how to answer so the answer can be applied
    clip["a"] = ("Here you go:\n\n**app.py**\n```python\ndef total(xs):\n    return sum(xs or [])\n```\n\n"
                 "```python\n# file: util/helpers.py\nX = 1\n```")
    msg = bridge.apply_answer()
    assert "app.py (+1 −1)" in msg and "helpers.py (new)" in msg
    changes.apply()
    assert (root / "util" / "helpers.py").read_text() == "X = 1\n" and "sum(xs or [])" in (root / "app.py").read_text()
    changes.undo()
    assert not (root / "util" / "helpers.py").exists()  # a file I created: undo removes it


def test_blocks_never_write_outside_the_project(tmp_path):
    assert blocks.parse("```js\n// file: web/app.js\nlet a\n```") == [("web/app.js", "let a\n")]
    assert blocks.to_files("```python\n# file: ../../etc/x.py\nX=1\n```", tmp_path) == {}


def test_new_project_is_written_set_up_and_run_once(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AGENT_PROJECTS_DIR", str(tmp_path))
    monkeypatch.setattr(llm, "chat", lambda *a, **k: llm.Reply(
        "NAME: todo_api\nRUN: python main.py\n```python\n# file: main.py\nprint('hi')\n```\n"
        "```text\n# file: requirements.txt\nrequests\n```\n```markdown\n# file: README.md\n# Todo\n```", "m"))
    calls = []
    monkeypatch.setattr(project, "_run", lambda cmd, cwd, timeout: calls.append(cmd) or (0, "hi"))
    from jarvis.tools.general import _sys
    monkeypatch.setattr(_sys, "run", lambda argv, **k: calls.append(argv) or "")

    class Ctx:
        msgs = []
        def progress(self, m): self.msgs.append(m)
        def check(self): pass
    ctx = Ctx()
    root = Path(project.build(ctx, "a tiny todo api"))
    assert root.name == "todo_api" and (root / "main.py").read_text() == "print('hi')\n"
    assert any("venv" in c for c in calls) and any("pip" in " ".join(c) for c in calls) and ["code", str(root)] in calls
    assert ctx.msgs[-1].startswith("» todo_api is ready")
    monkeypatch.setattr(llm, "chat", lambda *a, **k: llm.Reply("NAME: bad\nRUN: rm -rf ~\n```python\n# file: a.py\nx=1\n```", "m"))
    project.build(Ctx(), "something else entirely")
    assert not any("rm" in " ".join(c) for c in calls if isinstance(c, list))  # the AI's run command is never run blindly
