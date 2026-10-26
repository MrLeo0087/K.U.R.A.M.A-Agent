"""Smart file organizer: rename and sort a messy folder (Downloads by default) by what is INSIDE the files.

  1. 0 tokens: category by type (Documents, Images, Screenshots, Videos, Audio, Archives, Code, Installers, ...).
  2. Only files with meaningless names (IMG_2031.jpg, doc(3).pdf, Screenshot from ..., download.pdf) get looked at:
     the first page of a PDF / start of a text file, and pictures get one short look by the vision model
     (max config.ORGANIZE_MAX_IMAGES per run).
  3. One fast-LLM call per 40 files gives every document/picture a tidy name and a topic folder (College, Bills,
     Exams...); a topic folder is only made when 2+ files share it. Byte-identical copies go to Duplicates/,
     big videos to Videos/Movies, and files changed in the last 2 minutes (still downloading) are left alone.
Nothing moves until the user says yes (safety.ask) to the plan; every run writes an undo file, and
"undo organize" puts everything back where it was.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
import subprocess
import time
import zipfile
from pathlib import Path

from pydantic import BaseModel, Field

from jarvis.core import config

log = logging.getLogger(__name__)
CATS = {
    "Documents": {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".epub"},
    "Spreadsheets": {".xls", ".xlsx", ".ods", ".csv"},
    "Presentations": {".ppt", ".pptx", ".odp", ".key"},
    "Images": {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".svg", ".tiff"},
    "Videos": {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv"},
    "Audio": {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz"},
    "Code": {".py", ".ipynb", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".html", ".css", ".json", ".yaml",
             ".yml", ".sh", ".sql", ".r", ".go", ".rs"},
    "Installers": {".deb", ".appimage", ".rpm", ".run", ".exe", ".msi", ".snap", ".flatpak"},
}
_MEANINGLESS = re.compile(
    r"^(?:img|image|dsc|dscn|pxl|photo|pic|vid|video|mvimg|screenshot|screen ?shot|scan|doc|document|file|download|"
    r"untitled|new|copy|whatsapp (?:image|video)|signal-|telegram|output|unnamed|temp|tmp)?[\s_\-]*"
    r"(?:from\s+)?[\d\s_\-:.()at]*(?:\(\d+\))?$|^[0-9a-f]{8,}(?:-[0-9a-f]{4,})*$|^\d{6,}[_-]?\d*$", re.I)
_PARTIAL = (".crdownload", ".part", ".download", ".tmp")
UNDO_DIR = "organize_undo"


class Name(BaseModel):
    i: int
    name: str = Field(description="short descriptive file name WITHOUT extension, 2-6 words, keep a date if the "
                                  "file had one")
    topic: str = Field("", description="optional topic folder (1-2 words, e.g. College, Bills, ML, Travel), "
                                       "'' if none fits")


class Names(BaseModel):
    files: list[Name] = Field(default_factory=list)


def category(p: Path) -> str:
    ext = p.suffix.lower()
    if ext in CATS["Images"] and re.search(r"screen\s*shot|screenshot", p.name, re.I):
        return "Screenshots"
    return next((c for c, exts in CATS.items() if ext in exts), "Other")


DOC_CATS = ("Documents", "Spreadsheets", "Presentations")


def messy(p: Path) -> bool:
    """A long download name full of junk: 'Movie (2026) New Released Hindi Dubbed | Cast [zsLMsPSbHNY].jpg',
    'YTDown.com_YouTube_Media_3qzix..._128k.mp3'."""
    st = p.stem
    return len(st) > 60 or st.count(".") >= 3 or bool(re.search(r"\[[A-Za-z0-9_.-]{6,}\]|\bYTDown\b|www\.|\.com_|\|", st))


def meaningless(p: Path) -> bool:
    return bool(_MEANINGLESS.match(p.stem.strip()))


def _snippet(p: Path) -> str:
    ext = p.suffix.lower()
    try:
        if ext == ".pdf":
            return subprocess.run(["pdftotext", "-l", "1", "-q", str(p), "-"], capture_output=True, text=True,
                                  timeout=15).stdout[:400]
        if ext in (".txt", ".md", ".csv", ".py", ".json", ".html"):
            return p.read_text(errors="replace")[:400]
        if ext in (".docx", ".pptx", ".xlsx"):
            with zipfile.ZipFile(p) as z:
                part = next((n for n in z.namelist() if n in ("word/document.xml", "ppt/slides/slide1.xml",
                                                                 "xl/sharedStrings.xml")), None)
                return re.sub(r"<[^>]+>", " ", z.read(part).decode(errors="replace"))[:400] if part else ""
    except Exception as e:  # noqa: BLE001 - no clue just means "keep the name"
        log.info("snippet failed for %s: %s", p.name, e)
    return ""


def _caption(p: Path) -> str:
    """One short look at a picture by the vision model (~600 tokens)."""
    try:
        from PIL import Image
        from jarvis.core import llm
        with Image.open(p) as im:
            im = im.convert("RGB")
            im.thumbnail((768, 768))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=70)
        b64 = base64.b64encode(buf.getvalue()).decode()
        r = llm.chat([{"role": "user", "content": [
            {"type": "text", "text": "In under 12 words, what is this picture of? If it is a screenshot, say of what "
                                     "app/page/error. Plain words only."},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}],
            tier="vision", purpose="organize_caption", max_tokens=40)
        return (r.text or "").strip()[:120]
    except Exception as e:  # noqa: BLE001
        log.info("caption failed for %s: %s", p.name, e)
        return ""


def _free(dest: Path) -> Path:
    n, out = 1, dest
    while out.exists():
        out = dest.with_name(f"{dest.stem} ({n}){dest.suffix}")
        n += 1
    return out


def _clean(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|\n\r\t]+", " ", name).strip(" .")
    return re.sub(r"\s+", " ", name)[:80]


def _topic(t: str) -> str:
    t = _clean(t)
    return t.upper() if len(t) <= 3 else t.title()  # "ml" -> ML, "college" -> College


def _digest(p: Path) -> str:
    import hashlib
    h = hashlib.sha1()
    with open(p, "rb") as f:
        h.update(f.read(1 << 20))  # first MB + size is plenty to spot copies
    return f"{p.stat().st_size}:{h.hexdigest()}"


def duplicates(files: list[Path]) -> dict[Path, Path]:
    """copy -> original, for byte-identical files ("report (1).pdf" next to "report.pdf"). Same size first, so
    almost nothing is hashed."""
    by_size: dict[int, list[Path]] = {}
    for p in files:
        with_size = p.stat().st_size
        if with_size:
            by_size.setdefault(with_size, []).append(p)
    out: dict[Path, Path] = {}
    for group in (g for g in by_size.values() if len(g) > 1):
        seen: dict[str, Path] = {}
        for p in sorted(group, key=lambda q: (len(q.name), q.stat().st_mtime)):  # the shortest name is the original
            d = _digest(p)
            if d in seen:
                out[p] = seen[d]
            else:
                seen[d] = p
    return out


_ORG_SYS = ("You organize a person's files. For each file give: 'name' = a short clear human file name WITHOUT "
            "extension, in Title Case, same language as the original (keep the original words if they are already "
            "meaningful, just drop junk like site names, ids and 'New Released'), and 'topic' = the subject "
            "folder it belongs to (1-2 words: College, School, Bills, Work, Projects, Movies, Music, Travel, "
            "Personal, ML, Certificates, Exams, Receipts...). Reuse the SAME topic word for related files; use '' when "
            "unsure. Base it on the name and the clue.")


def plan(folder: Path, rename: bool = True) -> list[tuple[Path, Path]]:
    now = time.time()
    files = sorted((p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")
                    and not p.name.lower().endswith(_PARTIAL)
                    and now - p.stat().st_mtime > 120),  # skip files still being written / just downloaded
                   key=lambda p: p.stat().st_mtime, reverse=True)
    files = files[: config.ORGANIZE_MAX_FILES]
    dups = duplicates(files)
    clues: list[dict] = []
    images = 0
    for i, p in enumerate(files):
        if p in dups or category(p) in ("Installers", "Archives", "Code"):
            continue
        cat, clue = category(p), ""
        if cat in DOC_CATS:
            clue = _snippet(p)  # every document: its content decides the topic folder
        elif rename and meaningless(p) and p.suffix.lower() in CATS["Images"] and images < config.ORGANIZE_MAX_IMAGES:
            clue, images = _caption(p), images + 1
        elif not messy(p):
            continue  # a picture/video/song with a fine name: just sorted by type, no LLM tokens
        clues.append({"i": i, "name": p.name, "clue": " ".join(clue.split())[:220]})
    names: dict[int, Name] = {}
    if clues and rename:
        from jarvis.core import llm
        for k in range(0, len(clues), 40):  # one call per 40 files
            try:
                got = llm.structured([{"role": "system", "content": _ORG_SYS},
                                      {"role": "user", "content": json.dumps(clues[k:k + 40], ensure_ascii=False)}],
                                     Names, tier="fast", purpose="organize", max_tokens=1800)
                names.update({n.i: n for n in got.files})
            except Exception as e:  # noqa: BLE001 - still sort by type without names/topics
                log.warning("organize naming failed: %s", e)
    # a topic folder only when 2+ files share it (no folders holding a single file)
    from collections import Counter
    count = Counter((category(files[i]), _topic(n.topic)) for i, n in names.items() if _clean(n.topic))
    moves = []
    taken: set[Path] = set()
    for i, p in enumerate(files):
        cat = category(p)
        if cat == "Videos" and p.stat().st_size > 400 * 1024 * 1024:
            cat = "Videos/Movies"
        if p in dups:
            dest = _free(folder / "Duplicates" / p.name)
            taken.add(dest)
            moves.append((p, dest))
            continue
        sub = folder / cat
        n = names.get(i)
        topic = _topic(n.topic) if n and _clean(n.topic) else ""
        if topic and count[(category(p), topic)] >= 2 and category(p) in DOC_CATS:
            sub = sub / topic  # topic folders for documents only (College, Bills, Exams ...)
        renamed = rename and bool(n and _clean(n.name)) and (meaningless(p) or messy(p))
        stem = _clean(n.name) if renamed else p.stem
        if renamed and (dm := re.search(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})", p.stem)) and dm.group(1) not in stem:
            stem = f"{stem} {dm.group(1)}-{dm.group(2)}-{dm.group(3)}"  # keep the photo/scan date
        dest = _free(sub / f"{stem}{p.suffix.lower() if renamed else p.suffix}")
        k, base = 2, dest
        while dest in taken:
            dest = base.with_name(f"{base.stem} ({k}){base.suffix}")
            k += 1
        taken.add(dest)
        if dest != p:
            moves.append((p, dest))
    return moves


def describe(moves: list[tuple[Path, Path]], folder: Path, k: int = 15) -> str:
    lines = [f"{a.name} -> {b.relative_to(folder)}" for a, b in moves[:k]]
    more = f"\n... and {len(moves) - k} more" if len(moves) > k else ""
    return "\n".join(lines) + more


def apply(moves: list[tuple[Path, Path]]) -> Path:
    done = []
    for a, b in moves:
        if not a.exists():
            continue
        b.parent.mkdir(parents=True, exist_ok=True)
        b = _free(b)
        a.rename(b)
        done.append([str(a), str(b)])
    d = Path(config.DATA_DIR) / UNDO_DIR
    d.mkdir(parents=True, exist_ok=True)
    undo = d / f"{int(time.time())}.json"
    undo.write_text(json.dumps(done))
    return undo


def undo_last() -> str:
    d = Path(config.DATA_DIR) / UNDO_DIR
    logs = sorted(d.glob("*.json")) if d.is_dir() else []
    if not logs:
        return "There is nothing to undo."
    pairs = json.loads(logs[-1].read_text())
    back = 0
    for a, b in reversed(pairs):
        src, dst = Path(b), Path(a)
        if src.exists() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            back += 1
    for _, b in pairs:  # remove the folders the organizer made, if they are empty now
        for parent in (Path(b).parent, Path(b).parent.parent):
            try:
                parent.rmdir()
            except OSError:
                pass
    logs[-1].unlink()
    return f"Put {back} of {len(pairs)} files back where they were."


# --- background planning + a pending plan the user approves, edits or lets expire ---
PENDING = "organize_pending"


def _pending() -> dict | None:
    from jarvis.core import store
    try:
        d = json.loads(store.kv_get(PENDING) or "null")
    except (ValueError, TypeError):
        return None
    if not d or time.time() > d.get("expires", 0):
        return None
    return d


def pending_active() -> bool:
    return _pending() is not None


def _save_pending(folder: Path, moves: list[tuple[Path, Path]]) -> None:
    from jarvis.core import store
    store.kv_set(PENDING, json.dumps({"folder": str(folder), "moves": [[str(a), str(b)] for a, b in moves],
                                      "expires": time.time() + config.ORGANIZE_PLAN_TTL_S}))


def clear_pending() -> None:
    from jarvis.core import store
    store.kv_delete(PENDING)


def summary(moves: list[tuple[Path, Path]], folder: Path) -> str:
    """One line for the chat: '30 files -> Documents 5, Images 14, Videos 2 ...; 3 renamed'."""
    from collections import Counter
    tops = Counter(b.relative_to(folder).parts[0] for _, b in moves)
    renamed = sum(1 for a, b in moves if a.stem != b.stem and b.parent.name != "Duplicates")
    parts = ", ".join(f"{k} {v}" for k, v in tops.most_common())
    return f"{len(moves)} files -> {parts}" + (f"; {renamed} get clearer names" if renamed else "")


def readable(moves: list[tuple[Path, Path]], folder: Path) -> str:
    """The plan grouped by destination folder, renames shown, for the workspace."""
    groups: dict[str, list[str]] = {}
    for a, b in moves:
        rel = str(b.parent.relative_to(folder))
        line = a.name if a.name == b.name else f"{a.name}  ->  {b.name}"
        groups.setdefault(rel, []).append(line)
    mins = int(config.ORGANIZE_PLAN_TTL_S // 60)
    out = [f"Plan for {folder.name}: {summary(moves, folder)}",
           f"Say \"yes\" to apply, \"no\" to cancel, or tell me what to change (e.g. \"keep the pictures where they "
           f"are\", \"put the movie posters in Images/Movies\"). It expires in {mins} min.", ""]
    for rel in sorted(groups, key=lambda r: (-len(groups[r]), r)):
        out.append(f"## {rel}  ({len(groups[rel])})")
        out += [f"- {ln}" for ln in sorted(groups[rel], key=str.lower)]
        out.append("")
    return "\n".join(out)


def _publish(moves: list[tuple[Path, Path]], folder: Path) -> Path:
    d = Path(config.OUTPUTS_DIR) / "plans"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"organize-{folder.name.lower()}-{time.strftime('%H%M%S')}.md"
    p.write_text(readable(moves, folder), encoding="utf-8")
    return p


def start(folder: Path, rename: bool = True) -> str:
    """Make the plan as a background job (the chat stays free); the plan goes to the workspace."""
    from jarvis.core import jobs, safety

    def run(ctx) -> str | None:
        ctx.progress("looking at the files")
        moves = plan(folder, rename)
        ctx.check()
        if not moves:
            ctx.progress(f"» {folder.name} already looks organized.")
            return None
        _save_pending(folder, moves)
        mins = int(config.ORGANIZE_PLAN_TTL_S // 60)
        ctx.progress(f"» Plan ready: {summary(moves, folder)}. It's in the workspace. Say yes to apply, no to "
                     f"cancel, or tell me what to change ({mins} min).")
        return str(_publish(moves, folder))
    job = jobs.get_manager().submit(f"Organize plan for {folder.name}", "organize", run)
    with __import__("contextlib").suppress(Exception):
        safety.context().get("jobs", []).append(job.id)  # the UI watches it and announces the plan
    return (f"I'm making a plan for {folder.name} in the background. Keep talking; I'll tell you when it's ready "
            f"and show it in the workspace.")


def apply_pending() -> str:
    d = _pending()
    if not d:
        return "There's no plan waiting (plans expire after a few minutes). Say 'organize my downloads' to make one."
    moves = [(Path(a), Path(b)) for a, b in d["moves"] if Path(a).exists()]
    clear_pending()
    if not moves:
        return "Those files were already moved or deleted; nothing to do."
    apply(moves)
    from jarvis.core import focus
    focus.set_path(d["folder"])
    return f"Organized {len(moves)} files in {Path(d['folder']).name}. Say 'undo organize' to put them back."


def cancel_pending() -> str:
    had = pending_active()
    clear_pending()
    return "Okay, I won't move anything." if had else "There was no plan waiting."


class Change(BaseModel):
    i: int
    dest: str = Field(description="new destination folder relative to the organized folder, or 'KEEP' to leave the "
                                  "file where it is")


class Changes(BaseModel):
    changes: list[Change] = Field(default_factory=list)


def edit_pending(instruction: str) -> str:
    """Change the waiting plan the way the user says ("keep the pictures", "movies into Videos/Movies")."""
    d = _pending()
    if not d:
        return "There's no plan waiting to change. Say 'organize my downloads' to make one."
    folder = Path(d["folder"])
    moves = [(Path(a), Path(b)) for a, b in d["moves"]]
    rows = [{"i": i, "file": a.name, "to": str(b.parent.relative_to(folder))} for i, (a, b) in enumerate(moves)]
    from jarvis.core import llm
    got = llm.structured([{"role": "system", "content": "Change a file-organizing plan as the user asks. Return only "
                                                        "the files whose destination changes ('KEEP' = don't move)."},
                          {"role": "user", "content": f"Instruction: {instruction}\nPlan: {json.dumps(rows)}"}],
                         Changes, tier="fast", purpose="organize_edit", max_tokens=1500)
    keep: set[int] = set()
    n = 0
    for c in got.changes:
        if not 0 <= c.i < len(moves):
            continue
        a, b = moves[c.i]
        if c.dest.strip().upper() == "KEEP":
            keep.add(c.i)
        else:
            rel = _clean(c.dest.replace("\\", "/")).strip("/") or "."
            moves[c.i] = (a, folder / rel / b.name)
        n += 1
    moves = [m for i, m in enumerate(moves) if i not in keep]
    if not n:
        return "I couldn't tell which files to change. Try e.g. 'keep the pictures where they are'."
    _save_pending(folder, moves)  # also restarts the timer
    _publish(moves, folder)
    return f"Changed {n} files. Now: {summary(moves, folder)}. The new plan is in the workspace; say yes to apply."
