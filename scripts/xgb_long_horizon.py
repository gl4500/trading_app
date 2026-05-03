"""
Long-horizon ablation: 60 / 90 / 120 / 180 day forward returns.

Sample size collapses hard at these horizons (data span = 459 days), so
results are noisy — caveats noted in output. Cash-flow translation included.

Usage from project root:
    PYTHONPATH='site-packages;backend' runtime/python/python.exe scripts/xgb_long_horizon.py
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

PARAMS = {
    "max_depth": 6, "eta": 0.05, "subsample": 0.8,
    "colsample_bytree": 0.8, "alpha": 0.1, "lambda": 1.0,
    "objective": "reg:squarederror", "eval_metric": "rmse",
    "tree_method": "hist", "seed": 42, "verbosity": 0,
}

# Per-horizon clip — cap returns at ~3 daily-std equivalents to control
# extreme outliers without throwing away genuine signal.
CLIP_BY_HORIZON: Dict[int, float] = {
    60:  1.00,   # ±100%
    90:  1.50,   # ±150%
    120: 1.50,
    180: 2.00,   # ±200% — 5x baggers exist
}


def compute_forward_return(df: pd.DataFrame, days: int) -> pd.Series:
    secs = days * 86_400.0
    out = pd.Series(np.nan, index=df.index, dtype=np.float64)
    for sym, grp in df.groupby("symbol", sort=False):
        g = grp.sort_values("snapshot_ts")
        ts = g["snapshot_ts"].values
        px = g["price"].values
        idx = g.index.values
        n = len(g)
        j_target = np.searchsorted(ts, ts + secs, side="left")
        valid = j_target < n
        for i in np.where(valid)[0]:
            j = j_target[i]
            if px[i] > 0 and not np.isnan(px[j]):
                out.at[idx[i]] = float(px[j] / px[i] - 1.0)
    return out


def fit_and_score(X: np.ndarray, y: np.ndarray, t: np.ndarray, cols: List[int]) -> Dict:
    Xs = X[:, cols]
    folds = walkforward_folds(t, n_folds=3, min_val_days=14, embargo_bars=1)
    if not folds:
        return {"folds": 0, "mean_ic": float("nan"), "ir": float("nan"),
                "mean_wfe": float("nan"), "last_wfe": None}
    ics: List[float] = []
    wfes: List[float] = []
    last_wfe = None
    for i, (tr, va) in enumerate(folds):
        if len(tr) < 50 or len(va) < 30:
            continue
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
        "folds": len(folds),
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
    print(f"  data span: {span_days:.0f} days")

    horizons = [60, 90, 120, 180]
    print(f"\nComputing forward returns for {horizons}...")
    t0 = time.perf_counter()
    label_cols: Dict[int, str] = {}
    for h in horizons:
        col = f"return_{h}d_exp"
        df[col] = compute_forward_return(df, h)
        label_cols[h] = col
        n_valid = int(df[col].notna().sum())
        std = float(df[col].dropna().std()) if n_valid > 0 else float("nan")
        print(f"  horizon={h:>3}d  valid={n_valid:>6}/{len(df)}  raw_std={std*100:>6.2f}%")
    print(f"  ({time.perf_counter()-t0:.1f}s)")

    print(f"\n{'horizon':>7} {'feat_set':<14} {'N':>6} {'folds':>5} "
          f"{'mean_IC':>9} {'IR':>7} {'mean_WFE':>9} {'last_WFE':>9} "
          f"{'xs_std':>6} {'EV/trade':>9} {'trades/yr':>9} "
          f"{'gross/yr':>10} {'fric/yr':>9} {'net/yr':>10}")
    print("-" * 145)

    for h in horizons:
        clip = CLIP_BY_HORIZON[h]
        df_h = df.copy()
        df_h["return_5d"] = np.clip(df[label_cols[h]], -clip, clip)

        X_3d, y, _w, t = build_training_windows(df_h, T=WINDOW_SIZE)
        if len(X_3d) < 200:
            print(f"{h:>5}d   (too few windows: {len(X_3d)})")
            continue
        X = last_timestep_features(X_3d)
        sigma_xs = float(np.std(y))

        for label, cols in [("19-channels", list(range(19)))]:
            r = fit_and_score(X, y, t, cols)
            last_wfe_str = f"{r['last_wfe']:+.4f}" if r['last_wfe'] is not None else "  nan"

            ic = r["mean_ic"]
            if not np.isnan(ic):
                ev_per_trade = ic * sigma_xs * 0.7   # |z_typical| ≈ 0.7
                trades_per_year = 252.0 / h
                # 5 names × $2,000 portfolio
                gross_per_year = ev_per_trade * trades_per_year * 5 * 2_000
                # Friction at this universe: ~0.15% round-trip
                fric_per_year = 0.0015 * trades_per_year * 5 * 2_000
                net_per_year = gross_per_year - fric_per_year
                ev_str    = f"{ev_per_trade*100:>+6.2f}%"
                tpy_str   = f"{trades_per_year:>5.1f}"
                gross_str = f"${gross_per_year:>+8.0f}"
                fric_str  = f"-${fric_per_year:>6.0f}"
                net_str   = f"${net_per_year:>+8.0f}"
            else:
                ev_str = tpy_str = gross_str = fric_str = net_str = "n/a"

            print(f"{h:>5}d  {label:<14} {len(X):>6} {r['folds']:>5} "
                  f"{r['mean_ic']:>+9.4f} {r['ir']:>+7.2f} {r['mean_wfe']:>+9.4f} "
                  f"{last_wfe_str:>9} {sigma_xs*100:>5.2f}% {ev_str:>9} "
                  f"{tpy_str:>9} {gross_str:>10} {fric_str:>9} {net_str:>10}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
