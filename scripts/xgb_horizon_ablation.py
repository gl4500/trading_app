"""
Label-horizon ablation for XGB-native production model.

Computes forward returns at multiple horizons (1d, 5d, 10d, 30d, 60d)
from the `price` column, then re-runs walk-forward XGB on each as the
label. Reports per-horizon (mean_IC, IR, mean_WFE, last_WFE) for both
the full-19-channel set and the winning 6-channel subset from the
prior channel ablation.

Usage from project root:
    PYTHONPATH='site-packages;backend' runtime/python/python.exe scripts/xgb_horizon_ablation.py
"""
from __future__ import annotations

import os
import sys
import time
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import xgboost as xgb

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(os.path.dirname(_HERE), "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from data.cnn_evaluation import compute_ic, compute_ir, walkforward_folds
from data.cnn_model import _compute_wfe, build_training_windows, WINDOW_SIZE
from data.signal_history import (
    signal_history,
    SOURCE_COLUMNS, AGENT_COLUMNS, RV_COLUMNS, RETURN_COLUMNS,
    _MACRO_COLUMN_MAP,
)
from data.xgboost_model import last_timestep_features

MACRO_CHANNEL_NAMES = list(_MACRO_COLUMN_MAP.values())
CHANNEL_NAMES: List[str] = (
    list(SOURCE_COLUMNS) + list(AGENT_COLUMNS)
    + list(RV_COLUMNS) + list(RETURN_COLUMNS) + MACRO_CHANNEL_NAMES
)
# Winning 6-channel subset from xgb_channel_ablation.py:
WINNING_6 = ["rv_20d", "iv_rv_score", "r_120", "r_5", "rv_60d", "agent_consensus"]
WINNING_6_IDX = [CHANNEL_NAMES.index(n) for n in WINNING_6]

PARAMS = {
    "max_depth": 6, "eta": 0.05, "subsample": 0.8,
    "colsample_bytree": 0.8, "alpha": 0.1, "lambda": 1.0,
    "objective": "reg:squarederror", "eval_metric": "rmse",
    "tree_method": "hist", "seed": 42, "verbosity": 0,
}


def compute_forward_return(df: pd.DataFrame, days: int) -> pd.Series:
    """Per-symbol forward return at `days` calendar-days ahead.

    For each row, find the same-symbol future snapshot where
    (future_ts - current_ts) >= days*86400, and compute simple % return.
    Rows without enough forward data → NaN.
    """
    secs = days * 86_400.0
    out = pd.Series(np.nan, index=df.index, dtype=np.float64)
    for sym, grp in df.groupby("symbol", sort=False):
        g = grp.sort_values("snapshot_ts")
        ts = g["snapshot_ts"].values
        px = g["price"].values
        idx = g.index.values
        # For each row i, find the smallest j>i with ts[j] >= ts[i]+secs
        n = len(g)
        j_target = np.searchsorted(ts, ts + secs, side="left")
        valid = j_target < n
        i_valid = np.where(valid)[0]
        for i in i_valid:
            j = j_target[i]
            if px[i] > 0 and not np.isnan(px[j]):
                out.at[idx[i]] = float(px[j] / px[i] - 1.0)
    return out


def fit_and_score(X: np.ndarray, y: np.ndarray, t: np.ndarray, cols: List[int]) -> Dict:
    """Walk-forward XGB on X[:, cols] with same fold config as production."""
    Xs = X[:, cols]
    folds = walkforward_folds(t, n_folds=3, min_val_days=14, embargo_bars=1)
    if not folds:
        return {"mean_ic": float("nan"), "ir": float("nan"),
                "mean_wfe": float("nan"), "last_wfe": None}
    ics: List[float] = []
    wfes: List[float] = []
    last_wfe = None
    for i, (tr, va) in enumerate(folds):
        dtrain = xgb.DMatrix(Xs[tr], label=y[tr])
        dval = xgb.DMatrix(Xs[va], label=y[va])
        booster = xgb.train(
            PARAMS, dtrain, num_boost_round=500,
            evals=[(dval, "val")], early_stopping_rounds=30, verbose_eval=False,
        )
        vp = booster.predict(dval).astype(np.float32)
        vt = y[va].astype(np.float32)
        ics.append(compute_ic(vp, vt))
        wfe, _ = _compute_wfe(vt.tolist(), vp.tolist())
        if wfe is not None:
            wfes.append(wfe)
            last_wfe = wfe
    return {
        "mean_ic": float(np.mean(ics)) if ics else float("nan"),
        "ir": compute_ir(ics),
        "mean_wfe": float(np.mean(wfes)) if wfes else float("nan"),
        "last_wfe": last_wfe,
    }


def main() -> int:
    print("Loading training data...")
    df = signal_history.get_training_data()
    print(f"  rows={len(df):,}  symbols={df['symbol'].nunique()}")
    span_days = (df["snapshot_ts"].max() - df["snapshot_ts"].min()) / 86_400
    print(f"  span: {span_days:.0f} calendar days")

    horizons = [1, 5, 10, 30, 60]
    print(f"\nComputing forward returns for horizons {horizons}...")
    t0 = time.perf_counter()
    label_cols: Dict[int, str] = {}
    for h in horizons:
        col = f"return_{h}d_exp"
        df[col] = compute_forward_return(df, h)
        label_cols[h] = col
        n_valid = int(df[col].notna().sum())
        n_total = len(df)
        std = float(df[col].dropna().std())
        print(f"  horizon={h:>3}d  valid={n_valid:>6}/{n_total}  std={std:.4f}  xs_std={std*100:.2f}%")
    print(f"  ({time.perf_counter()-t0:.1f}s)")

    # Build features once (label-independent)
    # We'll re-run build_training_windows once per label since it filters NaN labels
    print(f"\n{'horizon':>8} {'feat_set':<14} {'N':>7} {'mean_IC':>9} {'IR':>7} {'mean_WFE':>10} {'last_WFE':>10}")
    print("-" * 80)

    for h in horizons:
        # Swap return_5d in the df with the experimental horizon so that
        # build_training_windows uses LABEL_HORIZON_COL='return_5d' but on
        # the new horizon's values. (Alternative: bypass the helper, but
        # this stays consistent with the rest of the pipeline.)
        df_h = df.copy()
        df_h["return_5d"] = df_h[label_cols[h]]
        df_h["return_5d"] = np.clip(df_h["return_5d"], -0.20, 0.20)  # match production
        # Also clip wider for longer horizons since 30d returns can legitimately
        # exceed ±20% — production clip is too tight at 30d. Use ±50%.
        if h >= 30:
            df_h["return_5d"] = np.clip(df[label_cols[h]], -0.50, 0.50)

        X_3d, y, _w, t = build_training_windows(df_h, T=WINDOW_SIZE)
        if len(X_3d) == 0:
            print(f"{h:>6}d  {'(no data)'}")
            continue
        X = last_timestep_features(X_3d)

        # Full 19 channels
        r_full = fit_and_score(X, y, t, list(range(19)))
        last_str_full = f"{r_full['last_wfe']:+.4f}" if r_full['last_wfe'] is not None else "  nan"
        print(f"{h:>6}d  {'19-channels':<14} {len(X):>7} {r_full['mean_ic']:>+9.4f} "
              f"{r_full['ir']:>+7.2f} {r_full['mean_wfe']:>+10.4f} {last_str_full:>10}")

        # Winning 6 channels
        r_win = fit_and_score(X, y, t, WINNING_6_IDX)
        last_str_win = f"{r_win['last_wfe']:+.4f}" if r_win['last_wfe'] is not None else "  nan"
        print(f"{'':>6}   {'6-channel-win':<14} {len(X):>7} {r_win['mean_ic']:>+9.4f} "
              f"{r_win['ir']:>+7.2f} {r_win['mean_wfe']:>+10.4f} {last_str_win:>10}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
