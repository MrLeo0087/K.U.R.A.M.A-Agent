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
    assert agents.current() == "general" and fastpath.agent_coding_intent("fix it") is None
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
    assert fastpath.agent_coding_intent("yes").args == {"action": "yes"}
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


def test_new_project_plan_first_then_small_code_cpu_torch_and_here(tmp_path, monkeypatch):
    from jarvis.agents.coding import templates
    monkeypatch.setattr(config, "AGENT_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setattr(templates, "pick", lambda d: templates.TEMPLATES["cnn"])
    here = tmp_path / "open_proj"
    here.mkdir()
    (here / "old.py").write_text("x=1\n")
    monkeypatch.setattr(bridge, "project_root", lambda: here)
    t, root = project.plan("set up a cnn retrain project here")
    assert root.parent == here and root.name == "cnn_retrain"  # 'here' = the open VS Code project (a sub-folder)
    t2, root2 = project.plan("set up a cnn retrain project")
    assert root2.parent == tmp_path / "projects"
    sent = []
    monkeypatch.setattr(llm, "chat", lambda msgs, **k: sent.append(msgs) or llm.Reply(
        "```python\n# file: model.py\nclass Net: pass\n```\n```python\n# file: train.py\nprint('ok')\n```\nEXTRA: pillow", "m"))
    calls = []
    monkeypatch.setattr(project, "_run", lambda cmd, cwd, timeout: calls.append(cmd) or (0, "ok"))
    from jarvis.tools.general import _sys
    monkeypatch.setattr(_sys, "run", lambda argv, **k: calls.append(argv) or "")

    class Ctx:
        msgs = []
        def progress(self, m): self.msgs.append(m)
        def check(self): pass
    ctx = Ctx()
    project.build(ctx, "set up a cnn retrain project here", t, root)
    assert "model.py" in sent[0][0]["content"] and "train.py" in sent[0][0]["content"]  # only the template's files
    assert (root / "model.py").read_text() == "class Net: pass\n"
    assert (root / "requirements.txt").read_text().split() == ["torch", "torchvision", "tqdm", "pillow"]
    assert calls == [["python3", "-m", "venv", ".venv"], ["code", str(root)]]  # owner: a venv, no packages, no run
    readme = (root / "README.md").read_text()
    assert "download.pytorch.org/whl/cpu" in readme and "pip install tqdm pillow" in readme and "python train.py" in readme
    assert ctx.msgs[-1].startswith("» cnn_retrain is ready") and "nothing was installed" in ctx.msgs[-1]


def test_a_big_background_call_never_waits_forever():
    """A 6k-token background call (new project) could never fit the 70% background share of an 8k/min bucket."""
    from jarvis.core import ratelimit
    b = ratelimit.Bucket(8000, 30)
    b.tokens = 3000
    assert not b.fits(7000, ratelimit.BACKGROUND)  # the share must be free first...
    b.tokens = 8000
    assert b.fits(7000, ratelimit.BACKGROUND)  # ...and then it goes (it used to wait forever)


def test_the_agent_never_takes_editing_requests_or_undoes_by_accident(monkeypatch, tmp_path):
    """Traces 2026-10-30 18:48-19:03: 'add comment on this code…', 'update code', 'clean and complete this code' ran
    UNDO; 'replace it' (answering an improved selection) ran the crash fixer."""
    from jarvis.core import assist, semantic
    monkeypatch.setattr(config, "FASTPATH", True)
    agents.switch("coding")
    terminal.record("python main.py", str(tmp_path), 1, "Traceback...\nNameError: name 'x' is not defined")
    scores = {}
    monkeypatch.setattr(semantic, "best_of", lambda t, name, table: scores[name])
    monkeypatch.setattr(semantic, "scores", lambda t: [("apps", 0.70)])
    scores.update(coding=("undo", 0.79), selection=("complete", 0.88))
    assert fastpath.agent_coding_intent("clean and complete this code") is None
    scores.update(coding=("undo", 0.72), selection=("ask", 0.92))
    assert fastpath.agent_coding_intent("add comment on this code and make it more good") is None
    scores.update(coding=("undo", 0.85), selection=("explain", 0.50))
    assert fastpath.agent_coding_intent("update code") is None  # undo needs a near-exact match
    scores.update(coding=("undo", 1.0), selection=("explain", 0.55))
    assert fastpath.agent_coding_intent("undo that").args["action"] == "undo"
    scores.update(coding=("fix", 0.95), selection=("improve", 0.60))
    assert fastpath.agent_coding_intent("fix it").args["action"] == "fix"
    assist._pending.update(old="a", new="b", text=True, expires=9e18)  # 'Say replace it to put it in place'
    scores.update(coding=("fix", 0.88), selection=("improve", 0.80))
    assert fastpath.agent_coding_intent("replace it") is None
    assist._pending.clear()


def test_a_fix_of_only_the_main_block_never_deletes_the_file(proj, monkeypatch):
    """Traces 16:26-17:08: the AI sent only `if __name__ == "__main__": calculator()` and test.py became 2 lines."""
    root, _ = proj
    body = "def calculator():\n" + "".join(f"    x{i} = {i}\n" for i in range(50)) + "\n\nif __name__ == \"__main__\":\n    clculator()\n"
    (root / "app.py").write_text(body)
    terminal.record("python app.py", str(root), 1,
                    f'Traceback (most recent call last):\n  File "{root / "app.py"}", line 55, in <module>\n    clculator()\n'
                    "NameError: name 'clculator' is not defined")
    monkeypatch.setattr(llm, "chat", lambda msgs, **k: llm.Reply(
        "CAUSE: typo.\n```python\n# file: app.py\nif __name__ == \"__main__\":\n    calculator()\n```", "m"))
    out = fixer.fix()
    assert "app.py (+1 −1)" in out
    changes.apply()
    new = (root / "app.py").read_text()
    assert new.count("\n") == body.count("\n") and "    calculator()" in new and "x49 = 49" in new
    monkeypatch.setattr(llm, "chat", lambda msgs, **k: llm.Reply("CAUSE: x.\n```python\n# file: app.py\nprint(\n```", "m"))
    assert "changed nothing" in fixer.fix() and (root / "app.py").read_text() == new  # unplaceable: untouched
