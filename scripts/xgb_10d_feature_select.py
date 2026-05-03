"""
Forward feature selection at the 10d label horizon.

Mirrors xgb_channel_ablation.py but uses 10-day forward returns as the
label. Reports:
  - Forward-selection trajectory (peak IC + which channels)
  - Comparison of 5d vs 10d at the production-vs-best feature sets
  - Cash-flow translation for the final shortlist

Usage from project root:
    PYTHONPATH='site-packages;backend' runtime/python/python.exe scripts/xgb_10d_feature_select.py
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
        for i in np.where(j_target < n)[0]:
            j = j_target[i]
            if px[i] > 0 and not np.isnan(px[j]):
                out.at[idx[i]] = float(px[j] / px[i] - 1.0)
    return out


def fit_and_score(X: np.ndarray, y: np.ndarray, t: np.ndarray, cols: List[int]) -> Dict:
    if not cols:
        return {"mean_ic": float("nan"), "ir": float("nan"),
                "mean_wfe": float("nan"), "last_wfe": None}
    Xs = X[:, cols]
    folds = walkforward_folds(t, n_folds=3, min_val_days=14, embargo_bars=1)
    if not folds:
        return {"mean_ic": float("nan"), "ir": float("nan"),
                "mean_wfe": float("nan"), "last_wfe": None}
    ics: List[float] = []
    wfes: List[float] = []
    last_wfe = None
    for tr, va in folds:
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
        "mean_ic": float(np.mean(ics)),
        "ir": compute_ir(ics),
        "mean_wfe": float(np.mean(wfes)) if wfes else float("nan"),
        "last_wfe": last_wfe,
    }


def main() -> int:
    print("Loading training data...")
    df = signal_history.get_training_data()
    print(f"  rows={len(df):,}  symbols={df['symbol'].nunique()}")

    print("\nComputing 10d forward returns from price...")
    df["return_10d_exp"] = compute_forward_return(df, 10)
    n_valid = int(df["return_10d_exp"].notna().sum())
    sigma_xs_unclipped = float(df["return_10d_exp"].dropna().std())
    print(f"  valid={n_valid}/{len(df)}  raw_std={sigma_xs_unclipped*100:.2f}%")

    # Swap label
    df["return_5d"] = np.clip(df["return_10d_exp"], -0.30, 0.30)

    print("\nBuilding (N, 19, 10) windows with 10d labels...")
    X_3d, y, _w, t = build_training_windows(df, T=WINDOW_SIZE)
    X = last_timestep_features(X_3d)
    sigma_xs = float(np.std(y))
    print(f"  X.shape={X.shape}  sigma_xs (clipped)={sigma_xs*100:.2f}%")

    # Baseline: all 19 channels at 10d
    print("\n" + "=" * 92)
    print("BASELINE (all 19 channels at 10d)")
    print("=" * 92)
    base = fit_and_score(X, y, t, list(range(19)))
    print(f"  mean_IC={base['mean_ic']:+.4f}  IR={base['ir']:+.2f}  "
          f"mean_WFE={base['mean_wfe']:+.4f}  last_WFE={base['last_wfe']:+.4f}")

    # Forward selection
    print("\n" + "=" * 92)
    print("FORWARD SELECTION at 10d (greedy: add channel with best mean_IC each step)")
    print("=" * 92)
    print(f"{'step':>4}  {'add channel':<24} {'#feat':>5} {'mean_IC':>9} {'IR':>7} "
          f"{'mean_WFE':>10} {'last_WFE':>10}")
    print("-" * 92)
    selected: List[int] = []
    remaining = list(range(19))
    history: List[Tuple[int, List[int], Dict]] = []
    for step in range(19):
        best_idx = None
        best_r = None
        best_ic = float("-inf")
        for cand in remaining:
            cols = selected + [cand]
            r = fit_and_score(X, y, t, cols)
            if r["mean_ic"] > best_ic:
                best_ic = r["mean_ic"]
                best_idx = cand
                best_r = r
        if best_idx is None:
            break
        selected.append(best_idx)
        remaining.remove(best_idx)
        history.append((step + 1, list(selected), best_r))
        last_wfe_str = f"{best_r['last_wfe']:+.4f}" if best_r['last_wfe'] is not None else "  nan"
        print(f"{step+1:>4}  {CHANNEL_NAMES[best_idx]:<24} {len(selected):>5} "
              f"{best_r['mean_ic']:>+9.4f} {best_r['ir']:>+7.2f} "
              f"{best_r['mean_wfe']:>+10.4f} {last_wfe_str:>10}")

    # Find peak step (best mean_IC)
    peak_step, peak_cols, peak_r = max(history, key=lambda x: x[2]["mean_ic"])
    print("\n" + "=" * 92)
    print(f"PEAK at step {peak_step}: {len(peak_cols)} channels")
    print("=" * 92)
    for idx in peak_cols:
        print(f"  - {CHANNEL_NAMES[idx]}")
    print(f"  mean_IC={peak_r['mean_ic']:+.4f}  IR={peak_r['ir']:+.2f}  "
          f"mean_WFE={peak_r['mean_wfe']:+.4f}  last_WFE={peak_r['last_wfe']:+.4f}")

    # Cash-flow comparison: production-5d vs winning-5d-6ch vs winning-10d-best
    print("\n" + "=" * 92)
    print("CASH-FLOW COMPARISON (per $10k portfolio, 5 names × $2k, 0.15% friction round-trip)")
    print("=" * 92)
    print(f"{'config':<40} {'IC':>8} {'xs_std':>6} {'EV/trade':>9} {'tr/yr':>6} {'gross/yr':>9} {'net/yr':>9}")
    print("-" * 92)

    def cashflow(ic: float, sigma: float, horizon_days: int) -> Tuple[float, float, float, float]:
        ev_per_trade = ic * sigma * 0.7
        trades_per_year = 252.0 / horizon_days
        gross = ev_per_trade * trades_per_year * 5 * 2_000
        fric  = 0.0015 * trades_per_year * 5 * 2_000
        net   = gross - fric
        return ev_per_trade, trades_per_year, gross, net

    rows = [
        ("5d  · all 19 channels (current prod)", 0.082, 0.082, 5),
        ("5d  · 6-channel winner (rv_20d, iv_rv_score, r_120, r_5, rv_60d, agent_consensus)", 0.207, 0.082, 5),
        ("10d · all 19 channels", base["mean_ic"], sigma_xs, 10),
        (f"10d · {len(peak_cols)}-channel peak", peak_r["mean_ic"], sigma_xs, 10),
    ]
    for label, ic, sig, hor in rows:
        ev, tpy, gross, net = cashflow(ic, sig, hor)
        print(f"{label:<40} {ic:>+8.4f} {sig*100:>5.2f}% "
              f"{ev*100:>+8.2f}% {tpy:>6.1f} ${gross:>+8.0f} ${net:>+8.0f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
