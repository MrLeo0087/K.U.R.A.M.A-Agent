"""Dataset quick check before training (0 tokens, no pandas: stdlib csv/json + numpy + Pillow, all lazy).

Tables (.csv .tsv .jsonl .json): rows/columns, per-column type, missing %, unique values, numeric range, duplicate
rows, constant and ID-like columns, the label column's class balance, and leakage hints (a column that predicts the
label one-to-one). Image folders: images per class (sub-folders), sizes and colour modes, unreadable files,
duplicates (also ACROSS train/val/test, which is leakage).
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path

MAX_ROWS = 200_000
IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
LABEL_NAMES = ("label", "labels", "target", "class", "y", "category", "output", "sentiment", "outcome")
SPLITS = ("train", "training", "val", "valid", "validation", "dev", "test", "testing")


# ---------------------------------------------------------------- tables
def _num(v: str) -> float | None:
    try:
        f = float(v.replace(",", "")) if isinstance(v, str) else float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def read_table(path: Path) -> tuple[list[str], list[list[str]], bool]:
    """(columns, rows as strings, truncated)."""
    suf = path.suffix.lower()
    rows: list[list[str]] = []
    if suf in (".jsonl", ".ndjson") or (suf == ".json" and path.read_text(errors="replace")[:1] not in "["):
        cols: list[str] = []
        with open(path, errors="replace") as f:
            for i, ln in enumerate(f):
                if i >= MAX_ROWS:
                    return cols, rows, True
                try:
                    obj = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    for k in obj:
                        if k not in cols:
                            cols.append(k)
                    rows.append(["" if obj.get(c) is None else str(obj.get(c)) for c in cols])
        return cols, [r + [""] * (len(cols) - len(r)) for r in rows], False
    if suf == ".json":
        data = json.loads(path.read_text(errors="replace"))
        data = [d for d in data if isinstance(d, dict)][:MAX_ROWS]
        cols = list(dict.fromkeys(k for d in data for k in d))
        return cols, [["" if d.get(c) is None else str(d.get(c)) for c in cols] for d in data], False
    with open(path, newline="", errors="replace") as f:
        sample = f.read(20000)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel_tab if suf == ".tsv" else csv.excel
        reader = csv.reader(f, dialect)
        cols = next(reader, [])
        for i, r in enumerate(reader):
            if i >= MAX_ROWS:
                return cols, rows, True
            rows.append((r + [""] * len(cols))[: len(cols)])
    return [c.strip() or f"col{i}" for i, c in enumerate(cols)], rows, False


MISSING = {"", "na", "n/a", "nan", "null", "none", "?", "-"}


def column_profile(name: str, values: list[str]) -> dict:
    n = len(values)
    present = [v for v in values if v.strip().lower() not in MISSING]
    nums = [x for x in (_num(v) for v in present) if x is not None]
    kind = "empty"
    if present:
        if len(nums) >= 0.95 * len(present):
            kind = "int" if all(x == int(x) for x in nums) else "float"
        elif all(v.strip().lower() in ("true", "false", "yes", "no", "0", "1") for v in present[:2000]):
            kind = "bool"
        else:
            kind = "text"
    uniq = len(set(present))
    p = {"name": name, "kind": kind, "missing": 1 - len(present) / n if n else 0, "unique": uniq}
    if kind in ("int", "float") and nums:
        a = __import__("numpy").asarray(nums, dtype=float)
        p.update(min=float(a.min()), max=float(a.max()), mean=float(a.mean()))
    if kind == "text":
        p["avg_len"] = sum(len(v) for v in present) / max(1, len(present))
    if kind != "float" and uniq <= 50:
        p["counts"] = Counter(present).most_common(12)
    return p


TARGET_WORDS = ("survived", "churn", "default", "fraud", "diagnosis", "species", "is_", "has_", "spam", "price",
                "salary", "outcome", "result", "status", "grade", "rating", "approved", "passed", "y_")


def guess_label(cols: list[str], profiles: dict[str, dict]) -> str | None:
    """The label column: a usual label name, else a known target word, else the last column if it looks like one."""
    for c in cols:
        if c.strip().lower() in LABEL_NAMES:
            return c
    for c in cols:
        low = c.strip().lower()
        if any(low.startswith(w) or low == w.strip("_") for w in TARGET_WORDS) and 2 <= profiles[c]["unique"] <= 50:
            return c
    last = cols[-1] if cols else None
    if last and 2 <= profiles[last]["unique"] <= 50:
        return last
    return None


def check_table(path: Path, label: str = "") -> str:
    cols, rows, cut = read_table(path)
    if not cols or not rows:
        return f"{path.name}: no rows I can read."
    n = len(rows)
    profiles = {c: column_profile(c, [r[i] for r in rows]) for i, c in enumerate(cols)}
    out = [f"{path.name}: {n:,} rows{'+ (first 200k read)' if cut else ''} x {len(cols)} columns"]
    issues: list[str] = []
    dup = n - len({tuple(r) for r in rows})
    if dup:
        issues.append(f"{dup:,} duplicate rows ({dup / n:.1%}): drop them, or they inflate validation scores.")
    lab = label if label in profiles else guess_label(cols, profiles)
    for c in cols:
        p = profiles[c]
        line = f"- {c}: {p['kind']}, {p['unique']:,} unique"
        if p["missing"]:
            line += f", {p['missing']:.0%} missing"
        if "min" in p:
            line += f", range {p['min']:.4g}..{p['max']:.4g} (mean {p['mean']:.4g})"
        out.append(line)
        if p["missing"] >= 0.4:
            issues.append(f"'{c}' is {p['missing']:.0%} empty: drop it or impute carefully.")
        if p["unique"] <= 1:
            issues.append(f"'{c}' has a single value: useless for training, drop it.")
        if c != lab and p["unique"] >= 0.98 * n and p["kind"] in ("int", "text") and n > 50:
            issues.append(f"'{c}' is (almost) unique for every row (an ID?): drop it before training.")
    if lab:
        p = profiles[lab]
        counts = p.get("counts") or []
        if counts:
            total = sum(k for _, k in counts)
            share = ", ".join(f"{v}: {k:,} ({k / total:.0%})" for v, k in counts[:8])
            out.append(f"Label '{lab}': {share}")
            if len(counts) >= 2 and counts[-1][1] / counts[0][1] < 0.2:
                issues.append(f"Classes are imbalanced (smallest is {counts[-1][1] / counts[0][1]:.0%} of the largest):"
                              f" use class weights or stratified splits, and judge with F1, not accuracy.")
        li = cols.index(lab)
        for i, c in enumerate(cols):
            if c == lab or profiles[c]["unique"] < 2 or profiles[c]["unique"] >= 0.98 * n:
                continue
            pairs = defaultdict(set)
            for r in rows[:50000]:
                pairs[r[i]].add(r[li])
            if all(len(s) == 1 for s in pairs.values()) and profiles[c]["unique"] <= max(50, n // 20):
                issues.append(f"'{c}' predicts '{lab}' perfectly: possible leakage (is it derived from the label?).")
    out.insert(1, "Problems:\n" + "\n".join(f"* {x}" for x in issues) if issues else "No obvious problems.")
    return "\n".join(out)


# ---------------------------------------------------------------- image folders
def _images(folder: Path) -> list[Path]:
    return [p for p in folder.rglob("*") if p.suffix.lower() in IMG_EXT and p.is_file()]


def _fingerprint(p: Path) -> str:
    with open(p, "rb") as f:
        return hashlib.md5(f.read(65536) + str(p.stat().st_size).encode()).hexdigest()


def check_images(folder: Path) -> str:
    from PIL import Image

    imgs = _images(folder)
    if not imgs:
        return f"{folder.name}: no images found."
    out = [f"{folder.name}: {len(imgs):,} images"]
    issues: list[str] = []
    splits = [d for d in folder.iterdir() if d.is_dir() and d.name.lower() in SPLITS]
    bases = splits or [folder]
    for base in bases:
        per = Counter(p.relative_to(base).parts[0] if len(p.relative_to(base).parts) > 1 else "(no class folder)"
                      for p in _images(base))
        head = f"{base.name}: " if splits else "Classes: "
        out.append(head + ", ".join(f"{c} {k:,}" for c, k in per.most_common(12)) + (" ..." if len(per) > 12 else ""))
        if len(per) >= 2 and min(per.values()) / max(per.values()) < 0.2:
            issues.append(f"{base.name}: classes are imbalanced ({min(per.values())} vs {max(per.values())} images).")
    sample = random.Random(0).sample(imgs, min(300, len(imgs)))
    sizes, modes, bad = Counter(), Counter(), []
    for p in sample:
        try:
            with Image.open(p) as im:
                sizes[im.size] += 1
                modes[im.mode] += 1
        except Exception:
            bad.append(p)
    for p in imgs[:3000]:
        if p in sample:
            continue
        try:
            with Image.open(p) as im:
                im.verify()
        except Exception:
            bad.append(p)
    out.append("Sizes: " + ", ".join(f"{w}x{h} ({k})" for (w, h), k in sizes.most_common(4))
               + (f" and {len(sizes) - 4} more" if len(sizes) > 4 else ""))
    out.append("Modes: " + ", ".join(f"{m} {k}" for m, k in modes.most_common()))
    if len(sizes) > 1:
        issues.append("Images have different sizes: resize/crop them in your transforms.")
    if len(modes) > 1:
        issues.append(f"Mixed colour modes ({', '.join(modes)}): convert all to RGB.")
    if bad:
        issues.append(f"{len(bad)} unreadable image(s), e.g. {bad[0].relative_to(folder)}: delete or replace them.")
    seen: dict[str, Path] = {}
    dups, cross = 0, 0
    for p in imgs[:8000]:
        try:
            h = _fingerprint(p)
        except OSError:
            continue
        if h in seen:
            dups += 1
            if splits and seen[h].relative_to(folder).parts[0] != p.relative_to(folder).parts[0]:
                cross += 1
        else:
            seen[h] = p
    if cross:
        issues.append(f"{cross} image(s) appear in more than one split (train/val/test): that's leakage, remove them.")
    elif dups:
        issues.append(f"{dups} duplicate image(s): they skew training.")
    out.insert(1, "Problems:\n" + "\n".join(f"* {x}" for x in issues) if issues else "No obvious problems.")
    return "\n".join(out)


def check(path: str, label: str = "") -> str:
    from jarvis.core.paths import smart_path

    p = Path(path).expanduser()
    if not p.exists():
        p = smart_path(path) or p
    if not p.exists():
        return f"error: I can't find {path!r}"
    if p.is_dir():
        if _images(p):
            return check_images(p)
        tables = sorted([f for f in p.iterdir() if f.suffix.lower() in (".csv", ".tsv", ".jsonl", ".json")],
                        key=lambda f: f.stat().st_size, reverse=True)
        if tables:
            return "\n\n".join(check_table(t, label) for t in tables[:3])
        return f"{p.name}: no images or tables (.csv/.tsv/.jsonl/.json) in it."
    if p.suffix.lower() in (".csv", ".tsv", ".txt", ".jsonl", ".ndjson", ".json"):
        return check_table(p, label)
    if p.suffix.lower() in (".parquet", ".xlsx", ".xls"):
        return f"error: {p.suffix} needs pandas, which KURAMA keeps out to stay light; export it as CSV first."
    return f"error: I can check tables (.csv .tsv .jsonl .json) and image folders, not {p.suffix or 'that'}."
