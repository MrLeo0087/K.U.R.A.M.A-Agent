"""Shared helpers for the interactive tools (not a tool): allowlisted subprocess runs with a
timeout and cancel support, folder resolution, and a guarded git runner (never push/force/reset)."""
from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

from jarvis.core import safety

# Folders no search or scan should walk into.
EXCLUDES = (".git", "node_modules", "venv", ".venv", "env", "__pycache__", ".mypy_cache",
            ".pytest_cache", ".ruff_cache", "site-packages", ".cache", ".tox", "dist", "build")
# git subcommands/flags these tools must never run, whatever the caller asks.
GIT_FORBIDDEN_CMDS = ("push", "reset", "clean", "rebase", "filter-branch", "gc", "prune", "update-ref")
GIT_FORBIDDEN_FLAGS = ("--force", "-f", "--hard", "--force-with-lease", "--discard-changes", "-D")


class ProcError(RuntimeError):
    """A command was refused, missing, failed or timed out. .output holds any partial stdout."""

    def __init__(self, msg: str, output: str = ""):
        super().__init__(msg)
        self.output = output


def run(argv: list[str], cwd: str | Path | None = None, timeout: float = 20,
        env: dict | None = None, cancel: threading.Event | None = None) -> subprocess.CompletedProcess:
    """Run an allowlisted argv (no shell). Raises ProcError on refusal, missing binary, timeout or cancel."""
    argv = [str(a) for a in argv]
    ok, why = safety.check_shell(argv)
    if not ok:
        raise ProcError(f"refused: {why}")
    try:
        p = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, env=env, start_new_session=True)
    except FileNotFoundError:
        raise ProcError(f"{argv[0].rsplit('/', 1)[-1]} not found: install it first") from None
    waited, step = 0.0, 0.5 if cancel is not None else timeout
    while True:
        try:
            out, err = p.communicate(timeout=min(step, max(timeout - waited, 0.01)))
            return subprocess.CompletedProcess(argv, p.returncode, out or "", err or "")
        except subprocess.TimeoutExpired:
            waited += step
            stopped = cancel is not None and cancel.is_set()
            if waited >= timeout or stopped:
                p.kill()
                out, _ = p.communicate()
                what = "cancelled" if stopped else f"timed out after {int(timeout)}s"
                raise ProcError(f"{argv[0].rsplit('/', 1)[-1]} {what}", out or "") from None


def resolve_dir(path: str | None, default: str = ".") -> Path:
    p = Path(os.path.expanduser(path or default)).resolve()
    if not p.is_dir():
        raise ProcError(f"not a folder: {p}")
    return p


def _git_env() -> dict:
    env = dict(os.environ)
    env.update(GIT_TERMINAL_PROMPT="0", LC_ALL="C", GIT_PAGER="cat", GIT_EDITOR="true")
    return env


def guard_git(args: list[str]) -> None:
    if not args or args[0] in GIT_FORBIDDEN_CMDS or any(a in GIT_FORBIDDEN_FLAGS for a in args):
        raise ProcError(f"refused: 'git {' '.join(args[:3])}' is not allowed (no push/force/reset)")


def git(args: list[str], repo: str | Path, timeout: float = 15, ok_codes: tuple[int, ...] = (0,)) -> str:
    """Run `git -C repo <args>` (guarded) and return stdout; raise ProcError with git's message on failure."""
    guard_git(args)
    cp = run(["git", "--no-optional-locks", "-C", str(repo), *args], timeout=timeout, env=_git_env())
    if cp.returncode not in ok_codes:
        msg = (cp.stderr or cp.stdout).strip().splitlines()
        raise ProcError(msg[-1][:300] if msg else f"git {args[0]} failed ({cp.returncode})")
    return cp.stdout


def repo_root(path: str | None) -> Path:
    base = resolve_dir(path)
    try:
        return Path(git(["rev-parse", "--show-toplevel"], base).strip())
    except ProcError:
        raise ProcError(f"not a git repository: {base}") from None


def clip(text: str, limit: int = 800) -> str:
    return text if len(text) <= limit else text[: limit - 12].rstrip() + "\n...[more]"
