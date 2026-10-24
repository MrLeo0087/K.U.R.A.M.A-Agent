"""P8a codequality tools: one test per tool (tmp git repos, mocked subprocess/LLM), routing, masking.
Fake secrets are assembled at runtime so this file itself never looks like it holds one."""
import subprocess

import pytest

from jarvis.core import jobs, llm, meta, registry, router, safety
from jarvis.tools.interactive import _secrets, dependency_doctor, precommit_gate, repo_hygiene, review_code
from jarvis.tools.interactive.secrets_audit import secrets_audit

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
    assert set(tools) == {"dependency_doctor", "repo_check", "review_code"}
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


def test_secret_masking_never_leaks():
    lines = [f'GROQ_API_KEY="{G}"', f"aws = '{A}'", f'db_password = "{P}"', f"token: {H}",
             "-----BEGIN RSA " + "PRIVATE KEY-----", 'api_key = "your-api-key-here"', "password = os.getenv('PW')",
             "self.token = token_value_from_somewhere", f'x = "{G}"  # secrets: ignore']
    found = _secrets.scan_text("\n".join(lines), "cfg.py")
    kinds = [(f.line, f.kind) for f in found]
    assert kinds == [(1, "groq_key"), (2, "aws_access_key"), (3, "password"), (4, "github_token"),
                     (5, "private_key")]
    rendered = "\n".join(f.render() for f in found)
    assert "gsk_****" in rendered and "AKIA****" in rendered and no_raw(rendered)
    red = _secrets.redact("\n".join(lines))
    assert no_raw(red) and "gsk_****" in red and "AKIA****" in red and "Hun7****" in red
    assert _secrets.mask("short") == "****"


def test_secrets_audit_tree_history_and_env(repo):
    (repo / "config.py").write_text(f'GROQ_API_KEY = "{G}"\nAWS = "{A}"\n')
    (repo / "old.py").write_text(f'db_password = "{P}"\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add config")
    (repo / "old.py").write_text("db_password = os.getenv('DB_PASSWORD')\n")
    (repo / ".gitignore").write_text("__pycache__/\n")
    (repo / ".env").write_text(f"GITHUB_TOKEN={H}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "move password to env, oops env")
    out = secrets_audit(str(repo), commits=50)
    assert "config.py:1 groq_key gsk_****" in out and "config.py:2 aws_access_key" in out
    assert "old.py:1 password" in out  # only in history now
    assert "only in history" in out and "TRACKED env file" in out and ".env is NOT in .gitignore" in out
    assert ".env:1 github_token ghp_****" in out
    assert no_raw(out) and len(out) <= 800


def test_secrets_audit_clean_repo(repo):
    (repo / ".env").write_text(f"GROQ_API_KEY={G}\n")  # ignored, untracked: fine
    out = secrets_audit(str(repo))
    assert out.startswith("secrets_audit proj: 0 possible secret(s)") and ".env ignored and untracked" in out


def test_precommit_gate_checks_and_hook(repo, monkeypatch):
    monkeypatch.setattr(precommit_gate, "find_ruff", lambda: None)  # exercise the ast fallback
    monkeypatch.setattr(precommit_gate, "MAX_BYTES", 1000)
    assert "nothing staged" in precommit_gate.precommit_gate(str(repo))
    (repo / "bad.py").write_text("def f(:\n    pass\n")
    (repo / "lint.py").write_text(f"import sys\nimport json\n\nKEY = '{G}'\nbreakpoint()\nprint(json)\n")
    (repo / "merge.txt").write_text("a\n<<<<<<< HEAD\nb\n=======\nc\n>>>>>>> other\n")
    (repo / "big.bin").write_bytes(b"\0" * 5000)
    _git(repo, "add", "-A")
    out = precommit_gate.precommit_gate(str(repo))
    assert out.startswith("pre-commit gate proj: FAIL")
    for part in ("syntax: bad.py:1", "lint: lint.py:1 unused import sys", "secrets: lint.py:4 groq_key gsk_****",
                 "breakpoints: lint.py:5", "conflict markers: merge.txt:2", "large files: big.bin", "debug prints"):
        assert part in out, part
    assert no_raw(out) and len(out) <= 800
    _git(repo, "reset", "-q")
    (repo / "ok.py").write_text("X = 1\n")
    _git(repo, "add", "ok.py")
    assert "PASS" in precommit_gate.precommit_gate(str(repo))
    # hook: asks first; never replaces a foreign hook without a yes
    asked = []
    monkeypatch.setattr(safety, "ask", lambda q: asked.append(q) or True)
    out = precommit_gate.precommit_gate(str(repo), install_hook=True)
    hook = repo / ".git" / "hooks" / "pre-commit"
    assert "installed pre-commit hook" in out and precommit_gate.HOOK_MARK in hook.read_text()
    assert "-m jarvis.tools.interactive.precommit_gate" in hook.read_text() and len(asked) == 1
    hook.write_text("#!/bin/sh\necho mine\n")
    monkeypatch.setattr(safety, "ask", lambda q: False)
    assert "kept the existing" in precommit_gate.precommit_gate(str(repo), install_hook=True)
    assert hook.read_text() == "#!/bin/sh\necho mine\n"


def test_precommit_gate_main_exit_code(repo, monkeypatch):
    monkeypatch.chdir(repo)
    (repo / "x.py").write_text("breakpoint()\n")
    _git(repo, "add", "x.py")
    assert precommit_gate.main() == 1


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


def test_repo_hygiene(repo):
    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "a.cpython-312.pyc").write_bytes(b"\0")
    (repo / "model.pt").write_bytes(b"\0" * 10)
    (repo / "b.py").write_text("# TODO: fix\n# FIXME later\n")
    _git(repo, "add", "-f", "-A")
    _git(repo, "commit", "-q", "-m", "junk")
    _git(repo, "branch", "feature-done")
    (repo / "emptydir").mkdir()
    out = repo_hygiene.repo_hygiene(str(repo))
    assert "2 TODO/FIXME" in out and "add README and LICENSE" in out
    assert "untrack junk (git rm --cached): __pycache__/a.cpython-312.pyc" in out
    assert "big/binary files tracked" in out and "model.pt" in out
    assert "merged branches to delete: feature-done" in out and "empty folders: emptydir" in out
    assert ".gitignore: add" in out and ".pytest_cache/" in out and len(out) <= 800


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


def test_precommit_gate_uses_ruff_with_error_rules(repo, monkeypatch):
    calls, real_run = [], precommit_gate._proc.run

    def fake_run(argv, cwd=None, timeout=20, **kw):
        if not str(argv[0]).endswith("ruff"):
            return real_run(argv, cwd=cwd, timeout=timeout, **kw)
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, "lint.py:1:8: F401 [*] `sys` imported but unused\n", "")
    monkeypatch.setattr(precommit_gate, "find_ruff", lambda: "/usr/bin/ruff")
    monkeypatch.setattr(precommit_gate._proc, "run", fake_run)
    (repo / "lint.py").write_text("import sys\n")
    _git(repo, "add", "lint.py")
    out = precommit_gate.precommit_gate(str(repo))
    assert "FAIL" in out and "ruff: lint.py:1:8: F401" in out
    assert calls[0][:2] == ["/usr/bin/ruff", "check"] and precommit_gate.RUFF_DEFAULT_RULES in calls[0]
