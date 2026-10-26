"""Small Excel sheets KURAMA keeps for the user (~/Documents/KURAMA/*.xlsx): editable by hand in LibreOffice,
written atomically under a file lock (server and Telegram may write at the same time)."""
from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def locked(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p.with_suffix(".lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            yield p
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


def load(p: Path, head: list[str], sheet: str = "") -> list[dict]:
    """Rows as {lowercase column: text}; columns found by their heading, so the user may reorder them.
    sheet = a named tab (missing tab = no rows); '' = the first one."""
    if not p.exists():
        return []
    from openpyxl import load_workbook
    wb = load_workbook(p, read_only=True)
    if sheet and sheet[:31] not in wb.sheetnames:
        return []
    ws = wb[sheet[:31]] if sheet else wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    have = [str(h or "").strip().lower() for h in rows[0]]
    col = {k.lower(): have.index(k.lower()) for k in head if k.lower() in have}
    out = []
    for r in rows[1:]:
        d = {k: (str(r[i]).strip() if i < len(r) and r[i] is not None else "") for k, i in col.items()}
        if any(d.values()):
            out.append({k.lower(): d.get(k.lower(), "") for k in head})
    return out


def save(p: Path, head: list[str], rows: list[dict], title: str, widths: tuple[int, ...] = ()) -> None:
    save_book(p, [(title, head, rows, widths)])


def save_book(p: Path, tabs: list[tuple[str, list[str], list[dict], tuple[int, ...]]]) -> None:
    """Several tabs in one workbook: (title, head, rows, widths) each."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    for n, (title, head, rows, widths) in enumerate(tabs):
        ws = wb.active if n == 0 else wb.create_sheet()
        ws.title = title[:31]
        ws.append(head)
        for c in ws[1]:
            c.font = Font(bold=True)
        for r in rows:
            ws.append([r.get(k.lower(), "") for k in head])
        for i, w in enumerate(widths):
            ws.column_dimensions[chr(65 + i)].width = w
        ws.freeze_panes = "A2"
    tmp = p.with_suffix(".tmp.xlsx")
    wb.save(tmp)
    tmp.replace(p)
