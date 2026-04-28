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

    # Use pandas rank with average method to handle ties correctly
    rank_pred = s_pred.rank(method="average").values
    rank_true = s_true.rank(method="average").values

    # Pearson correlation on ranks = Spearman correlation
    mean_rank_pred = np.mean(rank_pred)
    mean_rank_true = np.mean(rank_true)

    numerator = np.sum((rank_pred - mean_rank_pred) * (rank_true - mean_rank_true))
    denominator = np.sqrt(
        np.sum((rank_pred - mean_rank_pred) ** 2)
        * np.sum((rank_true - mean_rank_true) ** 2)
    )

    if denominator < 1e-12:
        return 0.0

    ic = numerator / denominator
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
