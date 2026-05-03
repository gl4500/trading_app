"""
One-shot backfill: populate return_10d in every parquet under
backend/data/history/.

For each row where return_10d is NaN, find the same-symbol row 10 calendar
days later (or beyond) and compute simple % return = (future_price/price - 1).
Mirrors fill_outcomes' logic but runs over the full historical archive in
one pass instead of incrementally on the live cycle.

Usage from project root:
    PYTHONPATH='site-packages;backend' runtime/python/python.exe scripts/backfill_return_10d.py
"""
from __future__ import annotations

import glob
import os
import sys
import time
from typing import Tuple

import numpy as np
import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(os.path.dirname(_HERE), "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

_HISTORY_DIR = os.path.join(_BACKEND, "data", "history")
TEN_DAYS_SECS = 10 * 86_400


def backfill_one(path: str) -> Tuple[int, int, int]:
    """Add return_10d to one parquet. Returns (rows, populated, already_had)."""
    df = pd.read_parquet(path)
    if df.empty or "price" not in df.columns or "snapshot_ts" not in df.columns:
        return (len(df), 0, 0)

    # Sort once for vectorized forward lookup
    df = df.sort_values("snapshot_ts").reset_index(drop=True)
    n = len(df)
    if "return_10d" not in df.columns:
        df["return_10d"] = np.nan
    already_had = int(df["return_10d"].notna().sum())

    ts = df["snapshot_ts"].values.astype(np.float64)
    px = df["price"].values.astype(np.float64)
    j_target = np.searchsorted(ts, ts + TEN_DAYS_SECS, side="left")

    populated = 0
    for i in range(n):
        if not np.isnan(df.at[i, "return_10d"]):
            continue
        j = j_target[i]
        if j >= n:
            continue
        if px[i] > 0 and not np.isnan(px[j]):
            df.at[i, "return_10d"] = float(px[j] / px[i] - 1.0)
            populated += 1

    if populated > 0:
        df.to_parquet(path, index=False)
    return (n, populated, already_had)


def main() -> int:
    files = sorted(glob.glob(os.path.join(_HISTORY_DIR, "*.parquet")))
    files = [f for f in files if not os.path.basename(f).startswith("__")]
    print(f"Found {len(files)} per-symbol parquets in {_HISTORY_DIR}")

    total_rows = 0
    total_pop  = 0
    total_had  = 0
    failed     = 0
    t0 = time.perf_counter()
    for i, f in enumerate(files):
        try:
            rows, pop, had = backfill_one(f)
            total_rows += rows
            total_pop  += pop
            total_had  += had
            if (i + 1) % 25 == 0 or i + 1 == len(files):
                elapsed = time.perf_counter() - t0
                print(f"  [{i+1:>3}/{len(files)}] {os.path.basename(f):<28} "
                      f"rows={rows:>4} +populated={pop:>4} ({elapsed:.1f}s elapsed)")
        except Exception as exc:
            failed += 1
            print(f"  ! {os.path.basename(f)}: {exc}")

    print(f"\nDone in {time.perf_counter()-t0:.1f}s")
    print(f"  symbols processed       : {len(files) - failed}/{len(files)}")
    print(f"  total rows              : {total_rows:,}")
    print(f"  return_10d already had  : {total_had:,}")
    print(f"  return_10d newly populated: {total_pop:,}")
    if failed:
        print(f"  failures                : {failed}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
