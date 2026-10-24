"""P4 interactive tools: one test per tool (tmp_path git repos / projects, mocked LLM, no network)."""
import shutil
import subprocess

import pytest

from jarvis.core import config, jobs, llm, registry
from jarvis.tools.interactive import _proc, env_doctor, find_files, git_commit, run_tests, scaffold_project
from jarvis.tools.interactive.git_branch import git_branch
from jarvis.tools.interactive.git_diff_summary import git_diff_summary
from jarvis.tools.interactive.git_log import git_log
from jarvis.tools.interactive.git_status import git_status


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "demo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "Tester")
    (r / "a.py").write_text("print('a')\n")
    _git(r, "add", "a.py")
    _git(r, "commit", "-q", "-m", "first commit")
    return r


def test_tools_registered_with_groups_and_safety():
    tools = {t.name: t for t in registry.schemas_for(["dev", "git", "filesearch"])}
    expect = {"scaffold_project": "confirm", "python_env": "safe", "find_files": "safe",
              "git_info": "safe", "git_change": "confirm", "run_tests": "safe"}
    assert {n: registry.safety_of(tools[n]) for n in expect} == expect
    assert registry.group_of(tools["find_files"]) == "filesearch"
    assert registry.group_of(tools["git_change"]) == "git" and registry.group_of(tools["python_env"]) == "dev"


def test_git_status_log_and_diff(repo):
    (repo / "a.py").write_text("print('b')\n")
    (repo / "new.txt").write_text("x")
    out = git_status(str(repo))
    assert "demo on main (no upstream)" in out and "1 modified" in out and "1 untracked" in out
    assert "?? new.txt" in out
    assert git_log(str(repo), n=5).endswith("first commit")
    assert "unstaged:" in git_diff_summary(str(repo)) and "a.py" in git_diff_summary(str(repo))


def test_git_status_outside_repo(tmp_path):
    with pytest.raises(_proc.ProcError, match="not a git repository"):
        git_status(str(tmp_path))


def test_git_commit_auto_message_is_token_cheap(repo, monkeypatch):
    seen = {}

    def fake_chat(messages, tier="fast", **kw):
        seen.update(tier=tier, user=messages[1]["content"])
        return llm.Reply('"Add b module."', "m")

    monkeypatch.setattr(llm, "chat", fake_chat)
    (repo / "b.py").write_text("x = 1\n" * 2000)
    assert "nothing staged" in git_commit.git_commit(repo=str(repo))
    out = git_commit.git_commit(repo=str(repo), add_all=True)
    assert out.startswith("committed ") and "Add b module" in out and "Not pushed" in out
    assert seen["tier"] == "fast" and len(seen["user"]) < 2300  # stat + <=1500 chars of diff
    assert git_log(str(repo), n=1).endswith("Add b module")


def test_git_branch_create_switch_and_guard(repo):
    assert "created and switched to branch feature-x" in git_branch("feature-x", "create", str(repo))
    assert "switched to branch main" in git_branch("main", "switch", str(repo))
    assert "branches: feature-x, main" in git_status(str(repo))
    for bad in (["push"], ["reset", "--hard"], ["branch", "-D", "x"], ["switch", "--force", "x"]):
        with pytest.raises(_proc.ProcError, match="not allowed"):
            _proc.git(bad, repo)


def test_find_files_by_name_and_content(tmp_path):
    if not (shutil.which("rg") and (shutil.which("fdfind") or shutil.which("fd"))):
        pytest.skip("fdfind/rg not installed")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "config.py").write_text("TOKEN_LIMIT = 5\n")
    (tmp_path / "venv").mkdir()
    (tmp_path / "venv" / "config.py").write_text("TOKEN_LIMIT = 9\n")  # excluded folder
    out = find_files.find_files("config.py", str(tmp_path))
    assert "pkg/config.py" in out and "venv/" not in out
    out = find_files.find_files("token_limit", str(tmp_path), kind="content")
    assert "pkg/config.py:1:TOKEN_LIMIT = 5" in out and "venv/" not in out
    assert "no files matching" in find_files.find_files("nothing_here.xyz", str(tmp_path))


def test_env_doctor_report_hides_key(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "GROQ_API_KEY", "gsk_secret_value_123")
    monkeypatch.setattr(env_doctor.shutil, "which", lambda c: None if c == "ffmpeg" else f"/usr/bin/{c}")
    out = env_doctor.env_doctor(str(tmp_path))
    assert "Python 3." in out and "RAM" in out and "swap" in out and "Disk: /" in out
    assert "missing ffmpeg" in out and "GROQ key: set" in out and "gsk_secret" not in out
    assert len(out) <= 800


def test_scaffold_project(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(scaffold_project, "_make_venv", lambda target: calls.append(target) or "venv created")
    out = scaffold_project.scaffold_project("my-api", "fastapi", str(tmp_path), create_venv=True)
    root = tmp_path / "my-api"
    assert "created fastapi project" in out and "venv created" in out and calls == [root]
    for rel in ("README.md", ".gitignore", "requirements.txt", "pytest.ini", "src/my_api/main.py",
                "tests/test_main.py"):
        assert (root / rel).is_file(), rel
    assert "fastapi" in (root / "requirements.txt").read_text()
    compile((root / "src/my_api/main.py").read_text(), "main.py", "exec")
    assert "refused" in scaffold_project.scaffold_project("my-api", "fastapi", str(tmp_path))
    assert "error" in scaffold_project.scaffold_project("../evil", "python-cli", str(tmp_path))


def test_run_tests_counts_and_first_failure(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "test_x.py").write_text(
        "def test_ok():\n    assert 1\n\ndef test_bad():\n    assert 2 + 2 == 5\n\ndef test_bad2():\n    assert 0\n")
    out = run_tests.run_tests(str(proj))
    assert out.startswith("FAIL: 2 failed, 1 passed") and "test_bad" in out and "assert" in out
    assert "test_bad2" not in out.split("first failure:")[1]  # only the first failure
    assert len(out) <= 800
    assert run_tests.run_tests(str(proj), pattern="ok").startswith("PASS: 1 passed")
    # long suites go to the JobManager
    monkeypatch.setattr(run_tests, "execute", lambda argv, cwd, timeout, cancel=None: "PASS: 3 passed")
    msg = run_tests.run_tests(str(proj), timeout=120)
    assert msg.startswith("started job #")
    job = jobs.get_manager().wait(int(msg.split("#")[1].split(":")[0]), timeout=10)
    assert job.status == "done" and "PASS: 3 passed" in open(job.output_path).read()
