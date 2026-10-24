"""check_dataset: look over a dataset before training: types, missing values, duplicates, class balance, leakage,
image sizes and broken files (safe, 0 tokens)."""
from __future__ import annotations

from jarvis.core import datacheck
from jarvis.core.registry import tool


@tool(group="dev", safety="safe",
      description="Check a dataset before training: a CSV/TSV/JSON(L) table (types, missing, duplicates, ID columns, "
                  "class balance, label leakage) or an image folder (images per class/split, sizes, broken, duplicates).")
def check_dataset(path: str, label: str = "") -> str:
    """Dataset quick check.

    Args:
        path: The file or folder (loose names work, e.g. "data/train.csv" or "cat dog dataset").
        label: The label/target column for tables (default: guessed, e.g. 'label' or the last column).
    """
    return datacheck.check(path, label)
