"""Shared secret detection for review_code (not a tool).

Regexes for well-known key formats plus an entropy check for generic `password = "..."` style
assignments. Findings carry only a masked preview (first 4 chars + ****); raw values never leave
this module except through redact(), which replaces them in text before it is shown or sent anywhere.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass

# (kind, pattern, group holding the secret value)
KEY_PATTERNS: tuple[tuple[str, re.Pattern, int], ...] = tuple(
    (k, re.compile(p), g) for k, p, g in (
        ("private_key", r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----", 0),
        ("aws_access_key", r"\b((?:AKIA|ASIA)[0-9A-Z]{16})\b", 1),
        ("github_token", r"\b(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})\b", 1),
        ("groq_key", r"\b(gsk_[A-Za-z0-9]{20,})\b", 1),
        ("anthropic_key", r"\b(sk-ant-[A-Za-z0-9_-]{20,})", 1),
        ("openai_key", r"\b(sk-(?:proj-)?[A-Za-z0-9_-]{20,})", 1),
        ("slack_token", r"\b(xox[abprs]-[A-Za-z0-9-]{10,})", 1),
        ("google_api_key", r"\b(AIza[0-9A-Za-z_-]{35})", 1),
        ("stripe_key", r"\b([rs]k_live_[0-9A-Za-z]{20,})", 1),
        ("telegram_bot_token", r"\b(\d{8,10}:AA[A-Za-z0-9_-]{33})\b", 1),
        ("hf_token", r"\b(hf_[A-Za-z]{34})\b", 1),
        ("jwt", r"\b(eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})", 1),
        ("url_password", r"\b[a-z][a-z0-9+.-]*://[^\s:/@'\"]+:([^\s@/'\"]{6,})@", 1),
    ))
# name = "value" where the name says secret/password/token/key
ASSIGN = re.compile(
    r"""(?i)\b([A-Za-z0-9_.-]*(?:api[_-]?key|secret|token|passw(?:or)?d|passwd|pwd|auth[_-]?key|"""
    r"""access[_-]?key|private[_-]?key|client[_-]?secret)[A-Za-z0-9_]*)["']?\s*(?:=|:|:=|=>)\s*"""
    r"""(?:[rbuf]?["']([^"'\s]{8,})["']|([^\s"'#,;(){}\[\]]{12,})\s*$)""")
PLACEHOLDER = re.compile(
    r"(?i)your|xxx|\*\*\*|example|changeme|change_me|placeholder|dummy|fake|sample|redacted|test|"
    r"secret_here|key_here|token_here|<|>|\$\{|\$\(|%\(|\{\{|^\$|os\.environ|getenv|environ\[|"
    r"settings\.|config\.|^none$|^null$|^true$|^false$")
IGNORE_PRAGMA = re.compile(r"(?i)(?:secrets|secret-scan|gitleaks):\s*(?:ignore|allow)|pragma:\s*allowlist secret")
CONFLICT = re.compile(r"^(?:<{7} |={7}$|>{7} )")


@dataclass
class Finding:
    path: str
    line: int
    kind: str
    preview: str  # masked: first 4 chars + ****
    fingerprint: str = ""  # short hash for de-duplication only (never shown)
    where: str = ""  # "" = working tree, else a commit sha

    def render(self) -> str:
        loc = f"{self.where}:" if self.where else ""
        return f"{loc}{self.path}:{self.line} {self.kind} {self.preview}"


def mask(value: str) -> str:
    """First 4 characters then ****; short values are fully masked."""
    return (value[:4] if len(value) >= 12 else "") + "****"


def entropy(s: str) -> float:
    if not s:
        return 0.0
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in (s.count(ch) for ch in set(s)))


def _plausible(value: str) -> bool:
    """A generic assignment value that looks like a real secret, not a placeholder or code reference."""
    if PLACEHOLDER.search(value) or "." in value and value.replace(".", "").isalpha():
        return False
    if len(set(value)) < 6 or value.isdigit() or re.fullmatch(r"[a-z_.-]+|[A-Z_.-]+", value):
        return False
    if re.fullmatch(r"[A-Za-z_][\w.]*", value) and not any(c.isdigit() for c in value):
        return False  # an identifier / dotted name: a code reference, not a literal secret
    return entropy(value) >= 3.3


def _fp(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8", "ignore")).hexdigest()[:10]


def scan_line(text: str, path: str, lineno: int, where: str = "") -> list[Finding]:
    if len(text) > 4000 or IGNORE_PRAGMA.search(text):
        return []
    out: list[Finding] = []
    seen: set[tuple[int, int]] = set()
    for kind, pat, grp in KEY_PATTERNS:
        for m in pat.finditer(text):
            span = m.span(grp)
            if any(a <= span[0] < b for a, b in seen):
                continue
            value = m.group(grp)
            if kind != "private_key" and (PLACEHOLDER.search(value) or entropy(value) < 3.0):
                continue
            seen.add(span)
            out.append(Finding(path, lineno, kind, mask(value), _fp(value), where))
    if not out:
        m = ASSIGN.search(text)
        if m:
            value = m.group(2) or m.group(3) or ""
            if _plausible(value):
                kind = "password" if re.search(r"(?i)pass|pwd", m.group(1)) else "generic_secret"
                out.append(Finding(path, lineno, kind, mask(value), _fp(value), where))
    return out


def scan_text(text: str, path: str, where: str = "") -> list[Finding]:
    found: list[Finding] = []
    for i, line in enumerate(text.splitlines(), 1):
        if any(h in line for h in ("KEY", "key", "-----", "sk-", "gsk_", "gh", "AKIA", "ASIA", "xox", "AIza",
                                    "eyJ", "_live_", ":AA", "hf_", "://", "ecret", "assw", "oken", "pwd", "PWD",
                                    "uth", "ECRET", "ASSW", "OKEN")):
            found.extend(scan_line(line, path, i, where))
    return found


def redact(text: str) -> str:
    """Replace every detected secret value in text with its masked form (for LLM prompts and reports)."""
    for _kind, pat, grp in KEY_PATTERNS:
        text = pat.sub(lambda m, g=grp: m.group(0).replace(m.group(g), mask(m.group(g))), text)

    def _assign(m: re.Match) -> str:
        value = m.group(2) or m.group(3) or ""
        return m.group(0).replace(value, mask(value)) if value and _plausible(value) else m.group(0)
    return "\n".join(ASSIGN.sub(_assign, ln) for ln in text.split("\n"))


# --- unified diff parsing (shared by precommit_gate / secrets_audit history / review_code) ---
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def added_lines(diff: str):
    """Yield (commit_sha, path, new_line_no, text) for every added line of a (multi-commit) diff."""
    sha, path, ln = "", "", 0
    for raw in diff.splitlines():
        if raw.startswith("commit ") and len(raw) >= 47:
            sha, path = raw[7:19], ""
        elif raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else ("" if raw[4:] == "/dev/null" else raw[4:])
        elif raw.startswith("@@"):
            m = HUNK_RE.match(raw)
            ln = int(m.group(1)) if m else 0
        elif raw.startswith("+") and path:
            yield sha, path, ln, raw[1:]
            ln += 1
        elif raw.startswith(" ") and path:
            ln += 1


def scan_diff(diff: str, limit: int = 200) -> list[Finding]:
    found: list[Finding] = []
    for sha, path, ln, text in added_lines(diff):
        found.extend(scan_line(text, path, ln, sha))
        if len(found) >= limit:
            break
    return found
