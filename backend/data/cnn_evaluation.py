"""
CNN evaluation harness — pure functions for honest model assessment.

Functions
---------
compute_ic           Spearman rank correlation of predictions vs realized returns.
compute_ir           Information Ratio: mean(IC) / std(IC) across folds.
compute_calibration  Bucketed predicted-vs-realized for calibration plots.
walkforward_folds    Time-ordered (train_idx, val_idx) generator with embargo.
"""
from __future__ import annotations

import math
from typing import Iterable, List, Sequence, Tuple

import numpy as np
import pandas as pd


def compute_ic(y_pred: np.ndarray, y_true: np.ndarray) -> float:
    """
    Spearman rank correlation between predicted and realized returns.

    IC > 0.05 is conventionally considered a real edge for cross-sectional alpha.
    Returns 0.0 when undefined (constant predictions, empty input, mismatched lengths).
    """
    y_pred = np.asarray(y_pred).ravel()
    y_true = np.asarray(y_true).ravel()
    if y_pred.size == 0 or y_true.size == 0 or y_pred.size != y_true.size:
        return 0.0
    s_pred = pd.Series(y_pred)
    s_true = pd.Series(y_true)
    if s_pred.nunique() < 2 or s_true.nunique() < 2:
        return 0.0
    # Pearson on average ranks = Spearman, and avoids scipy dependency
    # (pd.Series.corr(method="spearman") imports scipy.stats internally)
    ic = s_pred.rank(method="average").corr(s_true.rank(method="average"))
    return 0.0 if (ic is None or not math.isfinite(ic)) else float(ic)


def compute_ir(ics: Sequence[float]) -> float:
    """
    Information Ratio: mean(IC) / std(IC) across folds.

    A stable positive IC across walk-forward folds is what distinguishes
    a real edge from a one-off fluke. IR > 1.0 is good; > 2.0 is rare.

    Returns 0.0 when undefined (zero std, fewer than 2 folds).
    """
    arr = np.asarray(list(ics), dtype=np.float64)
    if arr.size < 2:
        return 0.0
    sd = float(arr.std(ddof=0))
    if sd < 1e-12:
        return 0.0
    return float(arr.mean() / sd)


def compute_calibration(
    y_pred: np.ndarray,
    y_true: np.ndarray,
    n_buckets: int = 5,
) -> List[dict]:
    """
    Quintile-bucketed calibration: split predictions into n equal-count buckets
    by predicted quantile, return mean predicted and mean realized per bucket.

    Used for calibration plots — a well-calibrated model has mean_pred ≈ mean_actual
    across buckets. A miscalibrated model shows over/under-prediction by bucket.

    Returns
    -------
    list of dicts ordered by ascending predicted quantile, each with:
        bucket      : int (0 = lowest predicted, n_buckets-1 = highest)
        count       : int (number of samples in this bucket)
        mean_pred   : float
        mean_actual : float
    """
    y_pred = np.asarray(y_pred).ravel()
    y_true = np.asarray(y_true).ravel()
    if y_pred.size == 0 or y_pred.size != y_true.size:
        return []

    try:
        labels = pd.qcut(y_pred, q=n_buckets, labels=False, duplicates="drop")
    except ValueError:
        return []

    out: List[dict] = []
    for b in sorted(np.unique(labels[~pd.isna(labels)])):
        mask = labels == b
        if not mask.any():
            continue
        out.append({
            "bucket":      int(b),
            "count":       int(mask.sum()),
            "mean_pred":   float(y_pred[mask].mean()),
            "mean_actual": float(y_true[mask].mean()),
        })
    return out


_SECS_PER_DAY = 86_400.0


def walkforward_folds(
    timestamps: np.ndarray,
    n_folds: int = 3,
    min_val_days: int = 14,
    embargo_bars: int = 1,
) -> List[Tuple[np.ndarray, np.ndarray]]:
    """
    Generate (train_idx, val_idx) tuples for walk-forward cross-validation.

    Each fold:
      - Train set is everything strictly before the fold's val start.
      - Val set spans at least `min_val_days` calendar days.
      - `embargo_bars` rows between train end and val start are excluded from
        both — prevents the model from seeing samples whose forward outcome
        overlaps the val period.

    Folds are anchored to the END of the data (rolling-origin from the back),
    so the most recent fold's val is always the last `min_val_days` of data
    and earlier folds shift backward by the val window. This is more honest
    than expanding-origin CV when data density is uneven over time.

    Parameters
    ----------
    timestamps   : (N,) float seconds since epoch
    n_folds      : how many CV folds to produce
    min_val_days : minimum calendar days the val window must span
    embargo_bars : rows to exclude between train end and val start

    Returns
    -------
    List of (train_idx, val_idx) numpy index arrays. Empty list when the
    dataset is too short to satisfy min_val_days for n_folds.
    """
    ts = np.asarray(timestamps, dtype=np.float64)
    if ts.size == 0:
        return []

    sort_idx = np.argsort(ts)
    sorted_ts = ts[sort_idx]

    val_secs = min_val_days * _SECS_PER_DAY
    total_secs = sorted_ts[-1] - sorted_ts[0]
    if total_secs < val_secs * (n_folds + 1):
        # Can't fit n_folds val windows AND any training data
        return []

    folds: List[Tuple[np.ndarray, np.ndarray]] = []
    end_ts = sorted_ts[-1]
    for fold_i in range(n_folds):
        val_end = end_ts - fold_i * val_secs
        val_start = val_end - val_secs
        if val_start <= sorted_ts[0]:
            break

        val_mask_sorted = (sorted_ts >= val_start) & (sorted_ts <= val_end)
        train_cutoff_idx = int(np.searchsorted(sorted_ts, val_start, side="left"))
        train_end_idx = max(0, train_cutoff_idx - embargo_bars)
        if train_end_idx < 1 or not val_mask_sorted.any():
            continue
        train_idx_sorted = np.arange(0, train_end_idx)
        val_idx_sorted = np.where(val_mask_sorted)[0]

        # Map back to original (unsorted) indices
        train_idx = sort_idx[train_idx_sorted]
        val_idx = sort_idx[val_idx_sorted]
        folds.append((train_idx, val_idx))

    # Reverse so folds are in chronological order (oldest val first)
    folds.reverse()
    return folds
