"""Contacts kept in a real Excel sheet (~/Documents/KURAMA/contacts.xlsx): add, find (fuzzy), list, update, delete.

The sheet is the source of truth, so it can also be edited by hand in LibreOffice/Excel. Columns: Name, Phone,
Note, Added. A file lock keeps the server and the Telegram worker from writing at the same time. 0 tokens.
"""
from __future__ import annotations

import difflib
import fcntl
import re
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from jarvis.core import config

HEAD = ["Name", "Phone", "Note", "Added"]


def path() -> Path:
    return Path(config.CONTACTS_FILE).expanduser()


@contextmanager
def _locked():
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p.with_suffix(".lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            yield p
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


def _load(p: Path) -> list[dict]:
    if not p.exists():
        return []
    from openpyxl import load_workbook
    ws = load_workbook(p, read_only=True).active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    head = [str(h or "").strip().lower() for h in rows[0]]
    col = {k: head.index(k) for k in ("name", "phone", "note", "added") if k in head}
    out = []
    for r in rows[1:]:
        get = lambda k: str(r[col[k]]).strip() if k in col and col[k] < len(r) and r[col[k]] is not None else ""  # noqa: E731
        if get("name") or get("phone"):
            out.append({"name": get("name"), "phone": get("phone"), "note": get("note"), "added": get("added")})
    return out


def _save(p: Path, rows: list[dict]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Contacts"
    ws.append(HEAD)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in sorted(rows, key=lambda r: r["name"].lower()):
        ws.append([r["name"], r["phone"], r["note"], r["added"]])
    for col, w in zip("ABCD", (28, 20, 30, 18)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    tmp = p.with_suffix(".tmp.xlsx")
    wb.save(tmp)
    tmp.replace(p)


def clean_phone(phone: str) -> str:
    phone = (phone or "").strip()
    keep = re.sub(r"[^\d+]", "", phone)
    return keep if len(re.sub(r"\D", "", keep)) >= 5 else ""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9ऀ-ॿ]+", " ", (s or "").lower()).strip()


def match(rows: list[dict], name: str) -> list[dict]:
    """Exact > all words contained > fuzzy (0.72) by name; also matches by number digits."""
    want = _norm(name)
    if not want:
        return []
    digits = re.sub(r"\D", "", name)
    if len(digits) >= 5:
        return [r for r in rows if digits in re.sub(r"\D", "", r["phone"])]
    exact = [r for r in rows if _norm(r["name"]) == want]
    if exact:
        return exact
    words = want.split()
    part = [r for r in rows if all(w in _norm(r["name"]).split() or w in _norm(r["name"]) for w in words)]
    if part:
        return part
    scored = [(difflib.SequenceMatcher(None, want, _norm(r["name"])).ratio(), r) for r in rows]
    best = [r for s, r in sorted(scored, key=lambda x: -x[0]) if s >= 0.72]
    return best[:3]


def _line(r: dict) -> str:
    return f"{r['name']}: {r['phone']}" + (f" ({r['note']})" if r["note"] else "")


def add(name: str, phone: str, note: str = "") -> str:
    name, ph = " ".join(name.split()).strip(" ,."), clean_phone(phone)
    name = name.title() if name.islower() else name
    if not name or not ph:
        return "error: I need a name and a valid phone number."
    with _locked() as p:
        rows = _load(p)
        same = [r for r in rows if _norm(r["name"]) == _norm(name)]
        if any(re.sub(r"\D", "", r["phone"]) == re.sub(r"\D", "", ph) for r in same):
            return f"{name} is already saved with {ph}."
        rows.append({"name": name, "phone": ph, "note": note.strip(),
                     "added": datetime.now().strftime("%Y-%m-%d %H:%M")})
        _save(p, rows)
    extra = f" ({name} now has {len(same) + 1} numbers)" if same else ""
    return f"Saved {name}: {ph}{extra}."


def find(name: str) -> str:
    with _locked() as p:
        rows = _load(p)
    if not rows:
        return "Your contacts sheet is empty. Say 'save Ram's number 98...' to add one."
    hits = match(rows, name)
    if not hits:
        return f"No contact matches '{name}'."
    return "\n".join(_line(r) for r in hits[:8])


def list_all(limit: int = 50) -> str:
    with _locked() as p:
        rows = _load(p)
    if not rows:
        return "No contacts saved yet."
    rows.sort(key=lambda r: r["name"].lower())
    more = f"\n... and {len(rows) - limit} more (all in {p})" if len(rows) > limit else ""
    return f"{len(rows)} contacts:\n" + "\n".join(_line(r) for r in rows[:limit]) + more


def update(name: str, phone: str) -> str:
    ph = clean_phone(phone)
    if not ph:
        return "error: that phone number doesn't look valid."
    with _locked() as p:
        rows = _load(p)
        hits = match(rows, name)
        if len(hits) != 1:
            return f"No contact matches '{name}'." if not hits else "Which one?\n" + "\n".join(_line(r) for r in hits)
        hits[0]["phone"] = ph
        _save(p, rows)
    return f"Updated {hits[0]['name']}: {ph}."


def delete(name: str) -> str:
    with _locked() as p:
        rows = _load(p)
        hits = match(rows, name)
        if len(hits) != 1:
            return f"No contact matches '{name}'." if not hits else "Which one?\n" + "\n".join(_line(r) for r in hits)
        from jarvis.core import safety
        if not safety.ask(f"Delete contact {_line(hits[0])}?"):
            return "Okay, kept it."
        rows.remove(hits[0])
        _save(p, rows)
    return f"Deleted {hits[0]['name']}."
