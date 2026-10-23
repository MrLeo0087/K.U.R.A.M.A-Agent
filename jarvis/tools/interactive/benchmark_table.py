"""benchmark_table: build a markdown results table from experiment files (safe; no LLM).
Reads CSV/TSV, JSON, JSONL and log lines ("epoch 3 acc=0.91 loss=0.23") from a folder, file or glob.
One row per run: a file, or each row when the data has a name/run/model column; epoch-style rows use
the last value per metric (mode="best" takes each metric's best). Best value per metric is bold
(lower is better for loss/error/time-like names), rows are sorted by the main metric, the table is
saved to data/outputs/bench-*.md and a <= 800-char preview is returned."""
from __future__ import annotations

import csv
import glob
import io
import json
import re
from datetime import datetime
from pathlib import Path

from jarvis.core import config
from jarvis.core.registry import tool
from jarvis.tools.interactive import _proc

EXTS = (".csv", ".tsv", ".json", ".jsonl", ".log", ".txt", ".out")
MAX_FILES = 200
MAX_BYTES = 20_000_000
MAX_COLS = 8
MAX_ROWS = 50
NAME_COLS = ("name", "run", "model", "experiment", "exp", "config", "run_name", "id")
INFO_COLS = {"epoch", "step", "iter", "iteration", "batch", "seed", "lr", "learning_rate", "global_step"}
LOWER = re.compile(r"(?i)loss|err|mae|mse|rmse|wer|cer|perplexity|ppl|latency|time|sec|_ms$|^ms$|duration|"
                   r"mem|fpr|fnr|nll|bpc|cost|eer")
PRIMARY = re.compile(r"(?i)acc|f1|auc|map|bleu|rouge|score|precision|recall|r2|iou|dice")
KV = re.compile(r"(?<![\w.])([A-Za-z][\w./-]*)\s*[=:]\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)%?(?![\w:])")
EPOCH = re.compile(r"(?i)\b(epoch|step|iter)\s+(\d+)\b")


def _num(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().rstrip("%")
    try:
        return float(s)
    except ValueError:
        return None


def lower_better(metric: str) -> bool:
    return bool(LOWER.search(metric)) and not PRIMARY.search(metric)


def _rows_to_runs(rows: list[dict], stem: str, mode: str) -> list[tuple[str, dict]]:
    """Rows -> runs: each row is a run when there is a text name column, else rows are epochs of one run."""
    if not rows:
        return []
    keys = {k for r in rows for k in r}
    name_col = next((c for c in keys if c.lower() in NAME_COLS
                     and any(_num(r.get(c)) is None and r.get(c) not in (None, "") for r in rows)), None)
    numeric = [{k: n for k, v in r.items() if k != name_col and (n := _num(v)) is not None} for r in rows]
    if name_col:
        return [(str(r.get(name_col)), m) for r, m in zip(rows, numeric) if m]
    merged: dict[str, float] = {}
    for m in numeric:
        for k, v in m.items():
            if mode == "best" and k in merged and k.lower() not in INFO_COLS:
                merged[k] = min(merged[k], v) if lower_better(k) else max(merged[k], v)
            else:
                merged[k] = v
    return [(stem, merged)] if merged else []


def _flat_numbers(obj, prefix: str = "", depth: int = 0) -> dict:
    out = {}
    if isinstance(obj, dict) and depth < 3:
        for k, v in obj.items():
            out.update(_flat_numbers(v, f"{prefix}.{k}" if prefix else str(k), depth + 1))
    elif (n := _num(obj)) is not None and not isinstance(obj, str):
        out[prefix or "value"] = n
    return out


def parse_file(p: Path, mode: str) -> list[tuple[str, dict]]:
    stem, ext = p.stem, p.suffix.lower()
    if ext in (".csv", ".tsv"):
        text = p.read_text("utf-8", "replace")
        try:
            dialect = csv.Sniffer().sniff(text[:2048], delimiters=",\t;|")
        except csv.Error:
            dialect = csv.excel_tab if ext == ".tsv" else csv.excel
        rows = [{(k or "").strip(): v for k, v in r.items() if k} for r in csv.DictReader(io.StringIO(text), dialect=dialect)]
        return _rows_to_runs(rows, stem, mode)
    if ext == ".json":
        obj = json.loads(p.read_text("utf-8", "replace"))
        if isinstance(obj, list):
            return _rows_to_runs([r for r in obj if isinstance(r, dict)], stem, mode)
        if isinstance(obj, dict):
            for key in ("runs", "results", "experiments", "history"):
                if isinstance(obj.get(key), list):
                    return _rows_to_runs([r for r in obj[key] if isinstance(r, dict)], stem, mode)
            if obj and all(isinstance(v, dict) for v in obj.values()):  # {"modelA": {...}, ...}
                return [(str(k), m) for k, v in obj.items() if (m := _flat_numbers(v))]
            m = _flat_numbers(obj)
            return [(stem, m)] if m else []
        return []
    rows = []
    with p.open("r", encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            if ext == ".jsonl" or ln.lstrip().startswith("{"):
                try:
                    r = json.loads(ln)
                    if isinstance(r, dict):
                        rows.append(r)
                    continue
                except ValueError:
                    if ext == ".jsonl":
                        continue
            r = {k: v for k, v in KV.findall(ln)}
            if not r:
                continue
            r.update({k.lower(): v for k, v in EPOCH.findall(ln)})
            rows.append(r)
    return _rows_to_runs(rows, stem, mode)


def gather(path: str) -> list[Path]:
    raw = str(Path(path).expanduser()) if path else "."
    if any(c in raw for c in "*?["):
        files = [Path(x) for x in sorted(glob.glob(raw, recursive=True))]
    else:
        p = Path(raw).resolve()
        if p.is_file():
            files = [p]
        elif p.is_dir():
            files = sorted(x for x in p.rglob("*") if x.suffix.lower() in EXTS
                           and not any(part in _proc.EXCLUDES for part in x.relative_to(p).parts)
                           and len(x.relative_to(p).parts) <= 3)
        else:
            files = []
    return [f for f in files if f.is_file() and f.suffix.lower() in EXTS and f.stat().st_size <= MAX_BYTES][:MAX_FILES]


def _fmt(v: float) -> str:
    return f"{v:.0f}" if v.is_integer() and abs(v) < 1e9 else f"{v:.4g}"


def build(runs: list[tuple[str, dict]], metric: str = "") -> tuple[str, str, int]:
    """(markdown table, sort metric, rows dropped)."""
    count: dict[str, int] = {}
    for _, m in runs:
        for k in m:
            count[k] = count.get(k, 0) + 1
    metrics = sorted((k for k in count if k.lower() not in INFO_COLS), key=lambda k: (-count[k], list(count).index(k)))
    info = [k for k in count if k.lower() in INFO_COLS and k.lower() in ("epoch", "step")][:1]
    cols = metrics[: MAX_COLS - len(info)]
    key = next((c for c in cols if c.lower() == metric.lower()), None) if metric else None
    key = key or next((c for c in cols if PRIMARY.search(c)), None) or next(
        (c for c in cols if "loss" in c.lower()), None) or (cols[0] if cols else "")
    low = lower_better(key) if key else False
    runs = sorted(runs, key=lambda r: (r[1][key] * (1 if low else -1)) if key in r[1] else float("inf"))
    dropped = max(len(runs) - MAX_ROWS, 0)
    runs = runs[:MAX_ROWS]
    best = {}
    for c in cols:
        vals = [m[c] for _, m in runs if c in m]
        if len(vals) > 1:
            best[c] = min(vals) if lower_better(c) else max(vals)
    head = ["run"] + cols + info
    lines = ["| " + " | ".join(head) + " |", "|---" + "|---:" * (len(head) - 1) + "|"]
    for name, m in runs:
        cells = [name.replace("|", "/")[:40]]
        for c in cols:
            if c not in m:
                cells.append("–")
            else:
                s = _fmt(m[c])
                cells.append(f"**{s}**" if c in best and m[c] == best[c] else s)
        cells += [_fmt(m[c]) if c in m else "–" for c in info]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines), key, dropped


@tool(group="devutils", safety="safe", max_chars=900,
      description="Build a markdown benchmark/results table (best per metric bold) from CSV/JSON/log files.")
def benchmark_table(path: str = ".", metric: str = "", mode: str = "last") -> str:
    """Parse result files into a sorted markdown table saved under data/outputs.

    Args:
        path: Folder, file or glob of result files (CSV, JSON, JSONL, logs).
        metric: Metric to sort by (default: accuracy/F1-like, else loss).
        mode: "last" (final value of each metric per run) or "best" (best value per metric).
    """
    files = gather(path)
    if not files:
        return f"no result files (csv/json/jsonl/log) found at {path}"
    runs, bad = [], 0
    for f in files:
        try:
            got = parse_file(f, "best" if mode == "best" else "last")
        except (ValueError, OSError, csv.Error):
            bad += 1
            continue
        names = {n for n, _ in runs}
        for name, m in got:
            if name in names:
                name = f"{f.parent.name}/{name}"
            runs.append((name, m))
    if not runs:
        return f"found {len(files)} files but no numeric metrics in them"
    table, key, dropped = build(runs, metric)
    low = lower_better(key) if key else False
    meta = (f"{len(runs)} runs from {len(files)} files; sorted by {key or '-'} "
            f"({'lower' if low else 'higher'} is better); **bold** = best per metric"
            + (f"; {dropped} more rows not shown" if dropped else "") + (f"; {bad} files unreadable" if bad else ""))
    config.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    out = config.OUTPUTS_DIR / f"bench-{datetime.now():%Y%m%d-%H%M%S}.md"
    out.write_text(f"# Benchmark: {path}\n\n{meta}\n\n{table}\n", encoding="utf-8")
    preview = table if len(table) <= 640 else table[:640].rsplit("\n", 1)[0] + "\n| ... |"
    return _proc.clip(f"{meta}\n{preview}\nsaved {out}", 800)
