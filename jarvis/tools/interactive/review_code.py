"""review_code: AI review of the staged diff, a file or the last commit (safe, token-cheap).
Hunks are scored by risk (eval/exec, shell, pickle, secrets, bare except, size...) and the riskiest
are packed into <= 2500 chars (secrets redacted) for one fast-tier call with a short rubric
(bugs, security, clarity); the reply is cut to <= 8 bullets with file:line. Diffs touching more than
5 files run as a background job that reviews in batches and writes data/outputs/review-*.md."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from jarvis.core.registry import tool
from jarvis.tools.interactive import _proc, _secrets

BUDGET = 2500  # chars of code per LLM call
MAX_BULLETS = 8
BG_FILES = 5  # more files than this -> background job
BG_MAX_CALLS = 6  # cap on batches per background review
FILE_CHUNK = 40  # lines per pseudo-hunk when reviewing a whole file
NOISY = (":(exclude)*.lock", ":(exclude)package-lock.json", ":(exclude)*.min.js", ":(exclude)*.ipynb",
         ":(exclude)*.svg")
RUBRIC = ("You review code changes. Find real problems only, in this order: bugs, security, clarity. "
          "Reply with at most 8 bullets, each '- path:line [bug|security|clarity] short finding + fix'. "
          "Use the line numbers shown at the start of lines. No praise, no summary. "
          "If nothing important, reply '- no significant issues'.")
RISK = [(re.compile(p), w) for p, w in (
    (r"\beval\(|\bexec\(|__import__\(", 5), (r"shell\s*=\s*True|os\.system\(|os\.popen\(", 5),
    (r"pickle\.loads?\(|yaml\.load\((?!.*Loader)|marshal\.loads", 4), (r"(?i)passw|secret|token|api[_-]?key", 3),
    (r"(?i)\bselect\b.*\bfrom\b.*(?:%s|\{|\+)|execute\(f[\"']", 4), (r"except\s*:|except Exception:\s*pass", 3),
    (r"verify\s*=\s*False|chmod\(.*0o?777|rm -rf|shutil\.rmtree", 4), (r"requests\.(?:get|post)\((?!.*timeout)", 2),
    (r"\bTODO\b|\bFIXME\b|\bHACK\b", 1), (r"\bglobal\b|threading|asyncio|lock", 1), (r"open\(", 1),
)]


@dataclass
class Hunk:
    path: str
    start: int
    lines: list[str] = field(default_factory=list)  # rendered: "123+ code" / "    - code" / "124  code"
    added: int = 0
    score: float = 0.0

    def text(self) -> str:
        return f"## {self.path}\n" + "\n".join(self.lines)


def parse_diff(diff: str) -> list[Hunk]:
    hunks: list[Hunk] = []
    path, ln, cur = "", 0, None
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else ""
            cur = None
        elif raw.startswith(("--- ", "diff --git", "index ", "new file", "deleted file", "similarity", "rename ")):
            continue
        elif raw.startswith("@@"):
            m = _secrets.HUNK_RE.match(raw)
            ln = int(m.group(1)) if m else 0
            cur = Hunk(path, ln) if path else None
            if cur:
                hunks.append(cur)
        elif cur is None:
            continue
        elif raw.startswith("+"):
            cur.lines.append(f"{ln}+ {raw[1:]}")
            cur.added += 1
            ln += 1
        elif raw.startswith("-"):
            cur.lines.append(f"   - {raw[1:]}")
        elif raw.startswith(" "):
            cur.lines.append(f"{ln}  {raw[1:]}")
            ln += 1
    return [part for h in hunks if h.lines for part in split(h)]


def split(h: Hunk, size: int = FILE_CHUNK) -> list[Hunk]:
    """Cut long hunks into windows so risk scoring can pick the dangerous part of a big change."""
    if len(h.lines) <= size:
        return [h]
    return [Hunk(h.path, h.start, h.lines[i:i + size], sum("+ " in t[:8] for t in h.lines[i:i + size]))
            for i in range(0, len(h.lines), size)]


def file_hunks(path: Path, rel: str) -> list[Hunk]:
    lines = path.read_text("utf-8", "replace").splitlines()
    out = []
    for i in range(0, len(lines), FILE_CHUNK):
        chunk = lines[i:i + FILE_CHUNK]
        h = Hunk(rel, i + 1, [f"{i + 1 + j}  {t}" for j, t in enumerate(chunk)], added=len(chunk))
        out.append(h)
    return out


def score(h: Hunk) -> float:
    body = "\n".join(t for t in h.lines if "+ " in t[:8] or t[:1].isdigit())
    s = sum(w * len(p.findall(body)) for p, w in RISK)
    return s + min(h.added, 40) / 10 + (2 if h.path.endswith((".py", ".js", ".ts", ".sh", ".go", ".rs")) else 0)


def _trim(h: Hunk, room: int) -> str:
    text = _secrets.redact(h.text())
    if len(text) <= room:
        return text
    return text[: max(room - 12, 0)].rsplit("\n", 1)[0] + "\n...[cut]"


def pack(hunks: list[Hunk], budget: int = BUDGET) -> tuple[str, int]:
    """Riskiest hunks first until the budget is used; returns (text, hunks included)."""
    for h in hunks:
        h.score = score(h)
    parts, used, n = [], 0, 0
    for h in sorted(hunks, key=lambda x: -x.score):
        room = budget - used
        if room < 200:
            break
        t = _trim(h, room)
        parts.append(t)
        used += len(t) + 1
        n += 1
    return "\n".join(parts), n


def ask_llm(code: str, label: str) -> tuple[list[str], int]:
    from jarvis.core import llm

    reply = llm.chat([{"role": "system", "content": RUBRIC},
                      {"role": "user", "content": f"Review ({label}):\n{code}"}],
                     tier="fast", purpose="review_code", max_tokens=700, temperature=0.2)
    bullets = []
    for ln in str(reply).splitlines():
        ln = ln.strip()
        if re.match(r"^(?:[-*•]|\d+[.)])\s+", ln):
            bullets.append("- " + re.sub(r"^(?:[-*•]|\d+[.)])\s+", "", ln).replace("**", "")[:170])
    tokens = getattr(reply, "prompt_tokens", 0) + getattr(reply, "completion_tokens", 0)
    return _secrets.redact("\n".join(bullets[:MAX_BULLETS])).splitlines(), tokens


def get_diff(root: Path, target: str) -> tuple[str, str]:
    """(diff, label) for staged / last_commit / commit:<sha>."""
    if target in ("last_commit", "last", "commit", "head"):
        diff = _proc.git(["show", "-U2", "--no-color", "--no-ext-diff", "--format=%h %s", "HEAD", "--", ".", *NOISY],
                         root, timeout=30)
        return diff, "last commit " + (diff.splitlines()[0][:60] if diff else "")
    if target.startswith("commit:"):
        sha = target.split(":", 1)[1].strip()
        if not re.fullmatch(r"[0-9a-fA-F]{4,40}|HEAD~?\d*", sha):
            raise _proc.ProcError(f"bad commit id: {sha}")
        return _proc.git(["show", "-U2", "--no-color", "--no-ext-diff", "--format=%h %s", sha, "--", ".", *NOISY],
                         root, timeout=30), f"commit {sha}"
    diff = _proc.git(["diff", "--cached", "-U2", "--no-color", "--no-ext-diff", "--", ".", *NOISY], root, timeout=30)
    if diff.strip():
        return diff, "staged changes"
    return _proc.git(["diff", "-U2", "--no-color", "--no-ext-diff", "--", ".", *NOISY], root, timeout=30), \
        "unstaged changes (nothing staged)"


def _background(hunks: list[Hunk], label: str, nfiles: int) -> str:
    from jarvis.core import config, jobs

    def job(ctx) -> str:
        by_file: dict[str, list[Hunk]] = {}
        for h in hunks:
            by_file.setdefault(h.path, []).append(h)
        batches, cur, size = [], [], 0
        for path in sorted(by_file, key=lambda p: -max(score(h) for h in by_file[p])):
            fsize = sum(len(h.text()) for h in by_file[path])
            if cur and size + fsize > BUDGET:
                batches.append(cur)
                cur, size = [], 0
            cur += by_file[path]
            size += fsize
        if cur:
            batches.append(cur)
        found, tokens = [], 0
        for i, batch in enumerate(batches[:BG_MAX_CALLS], 1):
            if ctx.job.cancel_event.is_set():
                break
            ctx.progress(f"reviewing batch {i}/{min(len(batches), BG_MAX_CALLS)}")
            code, _n = pack(batch)
            bullets, t = ask_llm(code, label)
            found += [b for b in bullets if "no significant issues" not in b.lower()]
            tokens += t
        config.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        path = config.OUTPUTS_DIR / f"review-{datetime.now():%Y%m%d-%H%M%S}.md"
        skipped = max(len(batches) - BG_MAX_CALLS, 0)
        path.write_text(f"# Code review: {label}\n\n{nfiles} files, {len(batches)} batches"
                        f"{f' ({skipped} skipped)' if skipped else ''}, ~{tokens} tokens\n\n"
                        + ("\n".join(found) or "- no significant issues") + "\n", encoding="utf-8")
        return str(path)

    j = jobs.get_manager().submit(f"review {label[:40]}", "review", job, label)
    return f"started job #{j.id}: reviewing {label} ({nfiles} files) in the background; report goes to data/outputs/review-*.md"


@tool(group="codequality", safety="safe", max_chars=1400,
      description="AI code review of the staged diff, a file or the last commit; returns up to 8 findings with file:line.")
def review_code(target: str = "staged", repo: str = ".", path: str = "") -> str:
    """Review code changes for bugs, security and clarity.

    Args:
        target: "staged" (default; falls back to unstaged), "last_commit", "commit:<sha>" or "file".
        repo: Repository folder (default: current folder).
        path: File to review when target is "file" (or any file path given as target).
    """
    target = (target or "staged").strip()
    if path or target == "file" or Path(target).suffix:
        fp = Path(path or target).expanduser()
        base = _proc.resolve_dir(repo)
        fp = fp if fp.is_absolute() else base / fp
        if not fp.is_file():
            return f"file not found: {fp}"
        hunks, label, nfiles = file_hunks(fp, fp.name), f"file {fp.name}", 1
    else:
        root = _proc.repo_root(repo)
        diff, label = get_diff(root, target.lower().replace(" ", "_") if ":" not in target else target)
        hunks = parse_diff(diff)
        nfiles = len({h.path for h in hunks})
        if not hunks:
            return f"nothing to review ({label}: no changes)"
        if nfiles > BG_FILES:
            return _background(hunks, label, nfiles)
    code, n = pack(hunks)
    bullets, tokens = ask_llm(code, label)
    if not bullets:
        bullets = ["- no significant issues"]
    foot = f"(reviewed {n}/{len(hunks)} hunks of {label}, ~{tokens} tokens)"
    return _proc.clip("\n".join(bullets + [foot]), 1400)
