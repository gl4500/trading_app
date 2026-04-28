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
