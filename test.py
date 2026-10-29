"""batch_cleaner.py

Asynchronous utilities for cleaning large CSV files.

The module provides:
- :func:`process_large_csv` – Reads a CSV file in chunks, strips whitespace
  from string columns, drops rows that are completely empty, computes basic
  summary statistics, and writes the cleaned data to a Parquet file using a
  thread‑pool executor.

The implementation uses :mod:`pandas` for data manipulation and :mod:`asyncio`
for asynchronous orchestration. Logging is used to report progress and errors.
"""

from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

# Configure module‑level logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
_handler = logging.StreamHandler()
_formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
_handler.setFormatter(_formatter)
logger.addHandler(_handler)


def _strip_whitespace(df: pd.DataFrame) -> pd.DataFrame:
    """Strip leading/trailing whitespace from all object (string) columns."""
    str_cols = df.select_dtypes(include=["object"]).columns
    if not str_cols.empty:
        logger.debug("Stripping whitespace from columns: %s", list(str_cols))
        df[str_cols] = df[str_cols].applymap(
            lambda x: x.strip() if isinstance(x, str) else x
        )
    return df


def _drop_all_nan_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows where every column is NaN."""
    before = len(df)
    df = df.dropna(how="all")
    after = len(df)
    logger.debug("Dropped %d all‑NaN rows", before - after)
    return df


def _compute_summary(df: pd.DataFrame) -> Tuple[int, Dict[str, int]]:
    """
    Compute summary statistics for a DataFrame chunk.

    Returns
    -------
    row_count : int
        Number of rows in the chunk after cleaning.
    missing_counts : dict
        Mapping of column name → count of missing values in that column.
    """
    row_count = len(df)
    missing_counts = df.isna().sum().to_dict()
    logger.debug("Chunk summary – rows: %d, missing: %s", row_count, missing_counts)
    return row_count, missing_counts


def _write_parquet(df: pd.DataFrame, output_path: Path) -> None:
    """Write a DataFrame to a Parquet file, appending if the file exists."""
    if output_path.exists():
        # Append to existing file by reading it, concatenating, and overwriting.
        # This is simple but not optimal for huge data; for production consider
        # pyarrow.dataset or partitioned writes.
        logger.debug("Appending to existing Parquet file %s", output_path)
        existing = pd.read_parquet(output_path)
        combined = pd.concat([existing, df], ignore_index=True)
        combined.to_parquet(output_path, index=False)
    else:
        logger.debug("Creating new Parquet file %s", output_path)
        df.to_parquet(output_path, index=False)


async def process_large_csv(
    file_path: str,
    chunk_size: int = 10_000,
    *,
    output_path: str | None = None,
    max_workers: int = 4,
) -> Dict[str, object]:
    """
    Asynchronously process a large CSV file in chunks.

    The function:
    1. Reads the CSV file lazily using ``pandas.read_csv`` with ``chunksize``.
    2. Strips whitespace from all string columns.
    3. Drops rows that are completely NaN.
    4. Accumulates basic summary statistics.
    5. Writes the cleaned data to a Parquet file using a thread‑pool executor.

    Parameters
    ----------
    file_path : str
        Path to the input CSV file.
    chunk_size : int, default 10_000
        Number of rows per chunk.
    output_path : str | None, optional
        Destination Parquet file. If ``None``, the output file will be the same
        name as the input with a ``.parquet`` suffix.
    max_workers : int, default 4
        Number of threads for the executor that performs the I/O‑bound Parquet
        writes.

    Returns
    -------
    dict
        Summary information containing total rows processed, total missing
        values per column, and the path to the generated Parquet file.

    Raises
    ------
    FileNotFoundError
        If ``file_path`` does not exist.
    ValueError
        If ``chunk_size`` is not positive.
    Exception
        For any unexpected errors during processing.
    """
    logger.info("Starting processing of CSV file %s", file_path)

    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"The file {file_path!r} does not exist.")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer.")

    output_path = Path(output_path) if output_path else Path(file_path).with_suffix(".parquet")
    logger.info("Cleaned data will be written to %s", output_path)

    total_rows = 0
    total_missing: Dict[str, int] = {}
    loop = asyncio.get_running_loop()

    # Use a thread pool for the blocking Parquet write operations
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        try:
            # Iterate over CSV chunks
            for i, chunk in enumerate(
                pd.read_csv(file_path, chunksize=chunk_size, dtype=str, keep_default_na=True)
            ):
                logger.debug("Processing chunk %d", i + 1)

                # Clean the chunk
                chunk = _strip_whitespace(chunk)
                chunk = _drop_all_nan_rows(chunk)

                # Update statistics
                rows, missing = _compute_summary(chunk)
                total_rows += rows
                for col, miss_cnt in missing.items():
                    total_missing[col] = total_missing.get(col, 0) + miss_cnt

                # Write cleaned chunk to Parquet asynchronously
                await loop.run_in_executor(
                    executor, _write_parquet, chunk, output_path
                )
                logger.info(
                    "Chunk %d processed: %d rows written, cumulative rows %d",
                    i + 1,
                    rows,
                    total_rows,
                )
        except Exception as exc:
            logger.exception("Error while processing CSV file: %s", exc)
            raise

    summary = {
        "total_rows": total_rows,
        "total_missing_per_column": total_missing,
        "output_parquet": str(output_path),
    }
    logger.info("Processing complete. Summary: %s", summary)
    return summary


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Asynchronously clean a large CSV and write to Parquet."
    )
    parser.add_argument("csv_path", help="Path to the input CSV file.")
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=10_000,
        help="Number of rows per processing chunk (default: 10,000).",
    )
    parser.add_argument(
        "--output",
        help="Destination Parquet file. Defaults to input filename with .parquet extension.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of worker threads for Parquet writing (default: 4).",
    )
    args = parser.parse_args()

    try:
        result = asyncio.run(
            process_large_csv(
                args.csv_path,
                chunk_size=args.chunk_size,
                output_path=args.output,
                max_workers=args.workers,
            )
        )
        print(json.dumps(result, indent=2))
    except Exception as e:
        logger.error("Failed to process file: %s", e)
        raise SystemExit(1)
