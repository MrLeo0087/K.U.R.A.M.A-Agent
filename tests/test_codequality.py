"""P8a codequality tools: one test per tool (tmp git repos, mocked subprocess/LLM), routing, masking.
Fake secrets are assembled at runtime so this file itself never looks like it holds one."""
import subprocess

import pytest

from jarvis.core import jobs, llm, meta, registry, router
from jarvis.tools.interactive import dependency_doctor, review_code

G = "gsk_" + "Q7xLm9TzR2vWb8NcK4pYh6JdF3sA1eU"
A = "AKIA" + "Z7Q2LM4XPB9RT6KD"
P = "Hun7er" + "-Pa55w0rd-9x!"
H = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
RAW = (G, A, P, H)


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "proj"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "Tester")
    (r / "a.py").write_text("import os\n\nprint(os.getcwd())\n")
    (r / ".gitignore").write_text("__pycache__/\n.env\nvenv/\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "first")
    return r


def no_raw(text):
    return not any(s in text for s in RAW) and not any(s[4:14] in text for s in RAW)


def test_registered_safe_and_small_group():
    tools = {t.name: t for t in registry.schemas_for(["codequality"])}
    assert set(tools) == {"dependency_doctor", "review_code", "code_tidy", "code_nav"}
    assert all(registry.safety_of(t) == "safe" for t in tools.values())


def test_routing_en_hi_ne_and_meta_budget(monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no classifier")))
    for text in ("check my dependencies for outdated packages", "scan the repo for leaked keys",
                 "install a pre-commit hook", "review my code", "review the last commit", "check repo hygiene",
                 "lint my staged files", "any vulnerable packages?", "कोड रिभ्यु गर", "mera code review karo"):
        assert router.route(text, log_it=False).groups == ["codequality"], text
    assert "git" in router.route("run the pre-commit checks then commit it", log_it=False).groups
    assert router.route("run tests", log_it=False).groups == ["dev"]
    assert "codequality(" in meta.schema()["function"]["description"]
    assert meta.estimate_tokens() < 200


def _fake_llm(seen, bullets=12):
    def fake_chat(messages, tier="fast", **kw):
        seen.append({"tier": tier, "user": messages[1]["content"], "system": messages[0]["content"]})
        body = "\n".join(f"- a.py:{i} [bug] issue {i}" for i in range(1, bullets + 1))
        return llm.Reply(body + f"\n- cfg.py:1 [security] key {G} hardcoded", "m", prompt_tokens=900,
                         completion_tokens=120)
    return fake_chat


def test_review_code_staged_last_commit_and_file(repo, monkeypatch):
    seen = []
    monkeypatch.setattr(llm, "chat", _fake_llm(seen))
    assert "nothing to review" in review_code.review_code(repo=str(repo))
    (repo / "a.py").write_text("import os, subprocess\n" + "x = 1\n" * 300
                               + f"subprocess.run(cmd, shell=True)\nKEY = '{G}'\n")
    (repo / "notes.md").write_text("hello\n" * 200)
    _git(repo, "add", "-A")
    out = review_code.review_code("staged", repo=str(repo))
    assert seen[-1]["tier"] == "fast" and len(seen[-1]["user"]) <= review_code.BUDGET + 60
    assert "shell=True" in seen[-1]["user"] and G not in seen[-1]["user"]  # riskiest first, secret redacted
    bullets = [ln for ln in out.splitlines() if ln.startswith("- ")]
    assert len(bullets) == 8 and "~1020 tokens" in out and no_raw(out)
    _git(repo, "commit", "-q", "-m", "risky change")
    out = review_code.review_code("last commit", repo=str(repo))
    assert "last commit" in seen[-1]["user"] and "risky change" in out
    out = review_code.review_code("file", repo=str(repo), path="a.py")
    assert "file a.py" in out and len(seen[-1]["user"]) <= review_code.BUDGET + 60


def test_review_code_many_files_runs_in_background(repo, monkeypatch):
    seen = []
    monkeypatch.setattr(llm, "chat", _fake_llm(seen, bullets=2))
    for i in range(7):
        (repo / f"m{i}.py").write_text(f"def f{i}():\n    return eval(input())\n")
    _git(repo, "add", "-A")
    msg = review_code.review_code(repo=str(repo))
    assert msg.startswith("started job #") and "7 files" in msg
    job = jobs.get_manager().wait(int(msg.split("#")[1].split(":")[0]), timeout=10)
    assert job.status == "done" and "/review-" in job.output_path
    with open(job.output_path) as fh:
        text = fh.read()
    assert "# Code review: staged changes" in text and "7 files" in text and no_raw(text)
    assert 1 <= len(seen) <= review_code.BG_MAX_CALLS


def test_dependency_doctor(tmp_path, monkeypatch):
    proj = tmp_path / "app"
    proj.mkdir()
    (proj / "requirements.txt").write_text("requests==2.32.0\nflask\nrequests>=2\nnumpy==2.0.0  # math\n"
                                           "torch==2.4.0\nghostpkg==1.0\n-r other.txt\n")
    (proj / "pyproject.toml").write_text('[project]\nname="app"\ndependencies=["rich>=13"]\n')
    (proj / "main.py").write_text("import requests\nfrom flask import Flask\nimport rich\n")
    installed = {"requests": "2.32.0", "flask": "3.0", "numpy": "2.0.0", "torch": "2.4.0", "rich": "13.0",
                 "nvidia-cudnn-cu12": "9.0"}
    pkgmap = {"requests": ["requests"], "flask": ["Flask"], "numpy": ["numpy"], "torch": ["torch"], "rich": ["rich"]}
    monkeypatch.setattr(dependency_doctor, "probe_env", lambda py: (installed, pkgmap))
    monkeypatch.setattr(dependency_doctor, "outdated", lambda py: {"numpy": ("2.0.0", "2.5.0")})
    monkeypatch.setattr(dependency_doctor, "audit", lambda root, py, files: ["requests 2.32.0 (GHSA-x)"])
    out = dependency_doctor.dependency_doctor(str(proj))
    assert "6 deps in requirements.txt, pyproject.toml" in out
    assert "unpinned: flask, requests, rich" in out and "duplicates: requests (conflicting specs" in out
    assert "missing from venv: ghostpkg" in out and "never imported (maybe transitive/CLI): numpy, torch" in out
    assert "outdated: numpy 2.0.0->2.5.0" in out and "vulnerable: requests 2.32.0 (GHSA-x)" in out
    assert "torch/GPU baggage installed: nvidia-cudnn-cu12, torch (declared!)" in out and len(out) <= 800
    assert "no requirements" in dependency_doctor.dependency_doctor(str(tmp_path))


def test_dependency_doctor_outdated_handles_failure(monkeypatch):
    def boom(*a, **k):
        raise dependency_doctor._proc.ProcError("python3 timed out after 25s")
    monkeypatch.setattr(dependency_doctor._proc, "run", boom)
    assert dependency_doctor.outdated("python3").startswith("skipped")
