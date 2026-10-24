"""repo_check: pre-commit checks, repo tidiness and a secrets scan in one tool (safe).

Merged from precommit_gate, repo_hygiene and secrets_audit (their old names still work as aliases).
"""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import alias, tool
from jarvis.tools.interactive.precommit_gate import precommit_gate
from jarvis.tools.interactive.repo_hygiene import repo_hygiene
from jarvis.tools.interactive.secrets_audit import secrets_audit


@tool(group="codequality", safety="safe",
      description="Check a repo: precommit (staged files: syntax, lint, secrets, big files), hygiene (README, "
                  ".gitignore, junk, stale branches), secrets (leaked keys in files and history), or all.")
def repo_check(check: Literal["all", "precommit", "hygiene", "secrets"] = "all", repo: str = ".",
               install_hook: bool = False) -> str:
    """Check a repo.

    Args:
        check: Which check (all = the three, one after another).
        repo: The repo folder.
        install_hook: Also install the pre-commit check as a git hook (check=precommit).
    """
    if check == "precommit":
        return precommit_gate(repo, install_hook)
    if check == "hygiene":
        return repo_hygiene(repo)
    if check == "secrets":
        return secrets_audit(repo)
    return "\n\n".join(f"## {t}\n{f(repo)}" for t, f in
                       (("Pre-commit", precommit_gate), ("Hygiene", repo_hygiene), ("Secrets", secrets_audit)))


alias("precommit_gate", "repo_check", check="precommit")
alias("repo_hygiene", "repo_check", check="hygiene")
alias("secrets_audit", "repo_check", lambda a: {"repo": a.get("repo", ".")}, check="secrets")
