"""Shell allowlist check (stdlib only, so tiny daemons can use it without importing the agent).

check_shell(cmd) -> (allowed, reason): only binaries in config.SHELL_ALLOWLIST; never sudo/su/doas/
pkexec; no pipes, redirects, chaining or command substitution.
"""
from __future__ import annotations

import re
import shlex

from jarvis.core import config

_SHELL_META = re.compile(r"[;&|`<>]|\$\(|\$\{|\n")
NEVER = ("sudo", "su", "doas", "pkexec")


def check_shell(cmd: str | list[str]) -> tuple[bool, str]:
    """(allowed, reason). Only allowlisted binaries; no sudo, pipes, redirects or chaining."""
    if isinstance(cmd, str):
        if _SHELL_META.search(cmd):
            return False, "shell operators (; & | ` < > $()) are not allowed"
        try:
            argv = shlex.split(cmd)
        except ValueError as e:
            return False, f"cannot parse command: {e}"
    else:
        argv = list(cmd)
    if not argv:
        return False, "empty command"
    binary = argv[0].rsplit("/", 1)[-1]
    if binary in NEVER:
        return False, f"{binary} is never allowed"
    if binary not in config.SHELL_ALLOWLIST:
        return False, f"{binary} is not in the shell allowlist"
    return True, "ok"
