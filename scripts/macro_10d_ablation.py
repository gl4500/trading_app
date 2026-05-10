"""
Targeted MACRO_10D ablation (Sprint 8 #67 follow-up).

Tests whether the new 10-day macro channels earn a slot in the production
XGB filter. Much faster than full forward selection (~30 min vs ~12 hours)
because we only test variants of the existing 8-channel production filter
rather than re-doing the full search across 38 channels.

Variants tested (all measured via 3-fold walk-forward IC at the 10d label):
  Baseline:  PRODUCTION_XGB_FILTER (8 channels)
  Add-each:  baseline + one MACRO_10D channel  (5 variants)
  Swap-5d:   baseline with macro_spy_5d_back -> macro_spy_10d_back
             baseline with macro_breadth_back -> macro_breadth_10d_back
  Swap-both: both swaps simultaneously
  All-10d:   baseline + all 5 MACRO_10D channels

Delta-IC vs baseline tells us whether to:
  (a) Add a 10d channel as a 9th feature (positive delta on add-each)
  (b) Replace a 5d channel with its 10d sibling (positive delta on swap-*)
  (c) Skip — 10d adds noise without lift (zero or negative delta)

Run from project root:
    PYTHONPATH='site-packages;backend' runtime/python/python.exe scripts/macro_10d_ablation.py
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
from data.cnn_model import _compute_wfe, build_training_windows, WINDOW_SIZE, ALL_CHANNEL_COLUMNS
from data.signal_history import signal_history
from data.xgboost_model import last_timestep_features

CHANNEL_NAMES: List[str] = list(ALL_CHANNEL_COLUMNS)
N_CHANNELS = len(CHANNEL_NAMES)

# Production XGB filter — 8 channels, currently in live use
PRODUCTION_8: List[str] = [
    "analyst_score", "earnings_score", "alpaca_score", "iv_rv_score",
    "r_120", "macro_vix_norm", "macro_spy_5d_back", "macro_breadth_back",
]

MACRO_10D: List[str] = [
    "macro_gld_10d_back", "macro_tlt_10d_back", "macro_spy_10d_back",
    "macro_breadth_10d_back", "macro_dji_10d_back",
]

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


def names_to_indices(names: List[str]) -> List[int]:
    return [CHANNEL_NAMES.index(n) for n in names]


def fmt_row(label: str, r: Dict, baseline_ic: float = None) -> str:
    delta = r["mean_ic"] - baseline_ic if baseline_ic is not None else 0.0
    delta_str = f"{delta:+.4f}" if baseline_ic is not None else "  base"
    last_wfe = f"{r['last_wfe']:+.4f}" if r['last_wfe'] is not None else "  nan"
    return (f"  {label:<48} mean_IC={r['mean_ic']:+.4f}  "
            f"dIC={delta_str}  IR={r['ir']:+.2f}  "
            f"mean_WFE={r['mean_wfe']:+.4f}  last_WFE={last_wfe}")


def main() -> int:
    print(f"MACRO_10D ablation — {N_CHANNELS}-channel catalog, production 8-ch baseline")
    print("=" * 100)

    print("\nLoading training data...")
    t0 = time.time()
    df = signal_history.get_training_data()
    print(f"  rows={len(df):,}  symbols={df['symbol'].nunique()}  ({time.time()-t0:.1f}s)")

    print("\nComputing 10d forward returns from price...")
    t0 = time.time()
    df["return_10d_exp"] = compute_forward_return(df, 10)
    n_valid = int(df["return_10d_exp"].notna().sum())
    print(f"  valid={n_valid:,}/{len(df):,}  ({time.time()-t0:.1f}s)")

    df["return_5d"] = np.clip(df["return_10d_exp"], -0.30, 0.30)

    print(f"\nBuilding (N, {N_CHANNELS}, {WINDOW_SIZE}) windows with 10d labels...")
    t0 = time.time()
    X_3d, y, _w, t = build_training_windows(df, T=WINDOW_SIZE)
    X = last_timestep_features(X_3d)
    print(f"  X.shape={X.shape}  y_std={float(np.std(y))*100:.2f}%  ({time.time()-t0:.1f}s)")

    # ── Variants to test ──────────────────────────────────────────────────
    variants: List[Tuple[str, List[str]]] = [
        ("BASELINE (production 8-ch filter)",            PRODUCTION_8),
    ]
    # Add-each: baseline + one 10d channel
    for ch in MACRO_10D:
        variants.append((f"BASELINE + {ch}",             PRODUCTION_8 + [ch]))
    # Swap-5d-to-10d siblings (where applicable)
    swap_spy   = [c if c != "macro_spy_5d_back"  else "macro_spy_10d_back"     for c in PRODUCTION_8]
    swap_brd   = [c if c != "macro_breadth_back" else "macro_breadth_10d_back" for c in PRODUCTION_8]
    swap_both  = [c if c != "macro_spy_5d_back"  else "macro_spy_10d_back"     for c in swap_brd]
    variants.append(("SWAP macro_spy_5d_back -> macro_spy_10d_back",          swap_spy))
    variants.append(("SWAP macro_breadth_back -> macro_breadth_10d_back",     swap_brd))
    variants.append(("SWAP both spy_5d & breadth_5d -> 10d siblings",         swap_both))
    # All-10d on top of baseline
    variants.append(("BASELINE + all 5 MACRO_10D channels (13-ch)",           PRODUCTION_8 + MACRO_10D))

    print(f"\nRunning {len(variants)} variants ({len(variants) * 3} XGBoost fits, ~3-fold CV each)")
    print("=" * 100)

    results: List[Tuple[str, Dict]] = []
    baseline_ic = None
    t0_total = time.time()
    for i, (label, names) in enumerate(variants, 1):
        cols = names_to_indices(names)
        t_start = time.time()
        r = fit_and_score(X, y, t, cols)
        elapsed = time.time() - t_start
        if baseline_ic is None:
            baseline_ic = r["mean_ic"]
            print(fmt_row(label, r))
        else:
            print(fmt_row(label, r, baseline_ic))
        print(f"    [{i}/{len(variants)}] elapsed={elapsed:.1f}s  total={time.time()-t0_total:.1f}s")
        results.append((label, r))

    # ── Summary ──────────────────────────────────────────────────────────
    print("\n" + "=" * 100)
    print("VERDICT")
    print("=" * 100)
    base_r = results[0][1]
    print(f"  baseline mean_IC = {base_r['mean_ic']:+.4f}, last_WFE = "
          f"{base_r['last_wfe']:+.4f}" if base_r['last_wfe'] is not None
          else f"  baseline mean_IC = {base_r['mean_ic']:+.4f}, last_WFE = nan")

    print("\nVariants ranked by mean_IC delta vs baseline:")
    ranked = sorted(results[1:], key=lambda kv: -kv[1]["mean_ic"])
    for label, r in ranked:
        delta = r["mean_ic"] - base_r["mean_ic"]
        flag = "  WIN" if delta > 0.005 else ("  TIE" if abs(delta) < 0.005 else "  LOSS")
        print(f"  {flag}  dIC={delta:+.4f}  {label}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
