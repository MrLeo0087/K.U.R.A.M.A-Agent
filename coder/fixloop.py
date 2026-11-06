"""Fix what the checks found, cheaply: each problem goes with only its file (cut around the line when the file is
long), the plan's short brief and the other files' names; the smart model returns the corrected file. Then the
checks run again, at most settings.MAX_FIX_ROUNDS times."""
from __future__ import annotations

import re
from collections import defaultdict

from coder import connect, models, safety, settings, verify, writer
from coder.run import Run

_SYS = ("You fix bugs in ONE file of a project. Keep everything that works; change only what the problems need; keep "
        "names consistent with the plan and the other files. Reply with ONLY the complete corrected file in one fenced "
        "code block.")


def _file_of(problem: str) -> str:
    return re.split(r":\d+:|: ", problem, maxsplit=1)[0].strip()


def fix_round(run: Run, problems: list[str]) -> int:
    """One round: each file with problems rewritten once. Returns how many files were changed."""
    by_file: dict[str, list[str]] = defaultdict(list)
    for p in problems:
        by_file[_file_of(p)].append(p)
    changed = 0
    for rel, probs in by_file.items():
        p = run.root / rel
        if not p.is_file():
            continue
        src = p.read_text(encoding="utf-8", errors="replace")
        if len(src) > 24000:
            run.note(f"fix skipped: {rel} is too long to send whole")
            continue
        others = "".join(f"\n--- {u} (for reference: keep these names) ---\n{writer._show(run, u)}"
                         for u in _partners(run, rel)[:2])
        user = (writer.plan_brief(run) + f"\nProblems in `{rel}`:\n" + "\n".join(f"- {x}" for x in probs)
                + others + f"\n\n--- {rel} (fix this file) ---\n{src}")
        try:
            body = writer.code_of(models.ask(run, "fix", _SYS, user, min(4000, len(src) // 3 + 600)))
        except Exception as e:  # noqa: BLE001
            run.note(f"fix of {rel} failed: {e}")
            continue
        if body.strip() and body.strip() != src.strip():
            safety.write(run, rel, body)
            changed += 1
    return changed


def _partners(run: Run, rel: str) -> list[str]:
    """The files a broken one must agree with: its planned uses / users, or the pages its selectors refer to."""
    spec = next((f for f in run.files if f.path == rel), None)
    out = writer.related(run, spec) if spec else []
    if rel.endswith((".js", ".mjs")):
        out += [p.relative_to(run.root).as_posix() for p in (run.root).glob("*.html")]
    return list(dict.fromkeys(out))


def problems(run: Run) -> list[str]:
    """Static problems first (0 tokens); a web page with none is then opened headless and clicked through: its
    browser errors count too (a plain HTML/CSS/JS project; a React app needs its packages installed first)."""
    found = connect.check(run) + verify.check(run)
    if not found and not (run.root / "package.json").exists():
        from coder import preview
        if preview.page_root(run.root) is not None:
            found = preview.selftest(run.root) or []
    return found


def loop(run: Run, on_round=None) -> list[str]:
    """Check, fix, check again (max rounds). Returns what is still wrong ([] = all good)."""
    left = problems(run)
    for i in range(settings.MAX_FIX_ROUNDS):
        if not left:
            break
        run.note(f"round {i + 1} problems: " + " | ".join(left)[:1500])
        if on_round:
            on_round(i + 1, left)
        if not fix_round(run, left):
            break
        left = problems(run)
    run.problems = left
    return left
