"""Study notes inbox: quick notes from the laptop or the phone (text, voice, photos) filed by subject and date in
~/Notes/<Subject>/<YYYY-MM-DD>.md, and "show my DSA notes from this week".

The subject comes from your words ("note for DSA: ..."), else one tiny fast-tier call picks one of the subjects you
already use (~120 tokens; NOTES_CLASSIFY), else "General".
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from jarvis.core import config

# "note for DSA: ...", "DSA note: ...", "note: ...", "study note in ML - ..."
NOTE = re.compile(r"^\s*(?:(?P<s1>[\w+#. ]{1,30}?)\s+notes?|(?:study |quick |add (?:a )?|take (?:a )?|save (?:a )?)?"
                  r"notes?(?:\s+(?:for|in|under|about|on)\s+(?P<s2>[\w+#. ]{1,30}?))?)\s*[:\-]\s*(?P<t>\S.*)$",
                  re.I | re.S)


def root() -> Path:
    d = Path(config.NOTES_DIR).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def subjects() -> list[str]:
    return sorted(p.name for p in root().iterdir() if p.is_dir() and not p.name.startswith("."))


def _canon(subject: str) -> str:
    s = " ".join(subject.split()).strip(" .")
    for have in subjects():
        if have.lower() == s.lower():
            return have
    return s[:1].upper() + s[1:] if s else "General"


def classify(text: str) -> str:
    have = [s for s in subjects() if s not in ("General", "Lectures")]
    if not config.NOTES_CLASSIFY or len(have) < 2:
        return "General"
    from jarvis.core import llm
    try:
        reply = str(llm.chat([{"role": "system", "content": "Which subject is this study note about? Answer with exactly "
                                                            "one of: " + ", ".join(have + ["General"])},
                              {"role": "user", "content": text[:400]}], tier="fast", purpose="note_subject",
                             max_tokens=60, temperature=0)).strip()
    except Exception:
        return "General"
    return next((s for s in have if s.lower() in reply.lower()), "General")


def add(text: str, subject: str = "") -> str:
    text = text.strip()
    if not text:
        return "error: the note is empty"
    subj = _canon(subject) if subject.strip() else classify(text)
    folder = root() / subj
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / f"{time.strftime('%Y-%m-%d')}.md"
    new = not f.exists()
    with open(f, "a") as fh:
        if new:
            fh.write(f"# {subj}: {time.strftime('%A %d %B %Y')}\n\n")
        fh.write(f"- {time.strftime('%H:%M')} {text}\n")
    return f"Noted under {subj}."


def show(subject: str = "", days: int = 7) -> str:
    since = datetime.now() - timedelta(days=max(1, days))
    want = [_canon(subject)] if subject.strip() else subjects()
    out = []
    for s in want:
        folder = root() / s
        if not folder.is_dir():
            continue
        for f in sorted(folder.glob("*.md")):
            try:
                day = datetime.strptime(f.stem[:10], "%Y-%m-%d")
            except ValueError:
                continue
            if day >= since.replace(hour=0, minute=0, second=0, microsecond=0):
                body = [ln for ln in f.read_text(errors="replace").splitlines() if ln.startswith("- ")]
                if body:
                    out.append(f"## {s}, {day:%a %d %b}\n" + "\n".join(body))
        for img in sorted((folder / "images").glob("*")) if (folder / "images").is_dir() else []:
            if datetime.fromtimestamp(img.stat().st_mtime) >= since:
                out.append(f"(photo) {s}: {img}")
    if not out:
        return (f"No {subject} notes" if subject else "No notes") + f" in the last {days} days." + (
            f" Subjects: {', '.join(subjects())}." if subjects() else "")
    return "\n\n".join(out)
