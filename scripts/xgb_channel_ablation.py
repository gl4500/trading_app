"""
Channel-by-channel ablation for the XGB-native production model.

Three experiments:
  1. LEAVE-ONE-OUT  — fit on 18 channels (drop one), report delta vs full-19
  2. GROUP ABLATION — drop a whole block (SOURCE/AGENT/RV/RETURNS/MACRO)
  3. FORWARD SELECTION — start empty, add the best-marginal channel each step

All use the same fold config (3 folds, 14d val, 1-bar embargo) — the
production setting that the fold-ablation experiment confirmed is optimal.

Usage from project root:
    PYTHONPATH='site-packages;backend' runtime/python/python.exe scripts/xgb_channel_ablation.py
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

# Channel order MUST match build_training_windows (cnn_model.py)
MACRO_CHANNEL_NAMES = list(_MACRO_COLUMN_MAP.values())
CHANNEL_NAMES: List[str] = (
    list(SOURCE_COLUMNS)         # 0..4
    + list(AGENT_COLUMNS)        # 5..6
    + list(RV_COLUMNS)           # 7..8
    + list(RETURN_COLUMNS)       # 9..13
    + MACRO_CHANNEL_NAMES        # 14..18
)
GROUPS: Dict[str, List[int]] = {
    "SOURCE":  list(range(0, 5)),
    "AGENT":   list(range(5, 7)),
    "RV":      list(range(7, 9)),
    "RETURNS": list(range(9, 14)),
    "MACRO":   list(range(14, 19)),
}

PARAMS = {
    "max_depth": 6, "eta": 0.05, "subsample": 0.8,
    "colsample_bytree": 0.8, "alpha": 0.1, "lambda": 1.0,
    "objective": "reg:squarederror", "eval_metric": "rmse",
    "tree_method": "hist", "seed": 42, "verbosity": 0,
}


def fit_and_score(
    X: np.ndarray, y: np.ndarray, t: np.ndarray, cols: List[int],
    n_folds: int = 3, min_val_days: int = 14, embargo_bars: int = 1,
) -> Dict:
    """Walk-forward XGB on X[:, cols]. Returns aggregate metrics."""
    if not cols:
        return {"mean_ic": float("nan"), "ir": float("nan"),
                "mean_wfe": float("nan"), "last_wfe": None, "last_ic": float("nan")}
    Xs = X[:, cols]
    folds = walkforward_folds(t, n_folds=n_folds, min_val_days=min_val_days, embargo_bars=embargo_bars)
    if not folds:
        return {"mean_ic": float("nan"), "ir": float("nan"),
                "mean_wfe": float("nan"), "last_wfe": None, "last_ic": float("nan")}

    ics: List[float] = []
    wfes: List[float] = []
    last_wfe = None
    last_ic = float("nan")
    for i, (tr, va) in enumerate(folds):
        dtrain = xgb.DMatrix(Xs[tr], label=y[tr])
        dval = xgb.DMatrix(Xs[va], label=y[va])
        booster = xgb.train(
            PARAMS, dtrain, num_boost_round=500,
            evals=[(dval, "val")], early_stopping_rounds=30, verbose_eval=False,
        )
        vp = booster.predict(dval).astype(np.float32)
        vt = y[va].astype(np.float32)
        ic = compute_ic(vp, vt)
        wfe, _ = _compute_wfe(vt.tolist(), vp.tolist())
        ics.append(ic)
        if wfe is not None:
            wfes.append(wfe)
            last_wfe = wfe
        if i == len(folds) - 1:
            last_ic = ic

    return {
        "mean_ic":  float(np.mean(ics)) if ics else float("nan"),
        "ir":       compute_ir(ics),
        "mean_wfe": float(np.mean(wfes)) if wfes else float("nan"),
        "last_wfe": last_wfe,
        "last_ic":  last_ic,
    }


def main() -> int:
    print("Loading training data...")
    df = signal_history.get_training_data()
    print(f"  rows={len(df):,}  symbols={df['symbol'].nunique()}")

    print("Building (N, C=19, T=10) windows...")
    X_3d, y, _w, t = build_training_windows(df, T=WINDOW_SIZE)
    X = last_timestep_features(X_3d)   # (N, 19)
    print(f"  X.shape={X.shape}  channels={CHANNEL_NAMES}")

    # Baseline: all 19 channels
    print("\n" + "=" * 95)
    print("BASELINE (all 19 channels)")
    print("=" * 95)
    base = fit_and_score(X, y, t, list(range(19)))
    print(f"  mean_IC={base['mean_ic']:+.4f}  IR={base['ir']:+.2f}  "
          f"mean_WFE={base['mean_wfe']:+.4f}  last_WFE={base['last_wfe']:+.4f}  last_IC={base['last_ic']:+.4f}")

    # ── Experiment 1: Leave-One-Out ────────────────────────────────────────
    print("\n" + "=" * 95)
    print("EXPERIMENT 1 — LEAVE-ONE-OUT (each row = drop that channel, keep other 18)")
    print("=" * 95)
    print(f"{'channel':<24} {'mean_IC':>9} {'d_IC':>10} {'IR':>7} {'mean_WFE':>10} {'last_WFE':>10}")
    print("-" * 95)
    loo_results = []
    for i, name in enumerate(CHANNEL_NAMES):
        cols = [c for c in range(19) if c != i]
        r = fit_and_score(X, y, t, cols)
        delta_ic = r["mean_ic"] - base["mean_ic"]
        last_wfe_str = f"{r['last_wfe']:+.4f}" if r['last_wfe'] is not None else "  nan"
        marker = ""
        if delta_ic > 0.001:
            marker = "  <-- drop helps"
        elif delta_ic < -0.005:
            marker = "  <-- drop hurts a lot"
        print(f"{name:<24} {r['mean_ic']:>+9.4f} {delta_ic:>+10.4f} {r['ir']:>+7.2f} "
              f"{r['mean_wfe']:>+10.4f} {last_wfe_str:>10}{marker}")
        loo_results.append((name, i, r, delta_ic))

    # ── Experiment 2: Group ablation ───────────────────────────────────────
    print("\n" + "=" * 95)
    print("EXPERIMENT 2 — GROUP ABLATION (drop the whole group, keep the rest)")
    print("=" * 95)
    print(f"{'drop group':<14} {'#chan':>5} {'mean_IC':>9} {'d_IC':>10} {'IR':>7} {'mean_WFE':>10} {'last_WFE':>10}")
    print("-" * 95)
    for gname, gcols in GROUPS.items():
        cols = [c for c in range(19) if c not in gcols]
        r = fit_and_score(X, y, t, cols)
        delta = r["mean_ic"] - base["mean_ic"]
        last_wfe_str = f"{r['last_wfe']:+.4f}" if r['last_wfe'] is not None else "  nan"
        print(f"{gname:<14} {len(cols):>5} {r['mean_ic']:>+9.4f} {delta:>+10.4f} {r['ir']:>+7.2f} "
              f"{r['mean_wfe']:>+10.4f} {last_wfe_str:>10}")

    # Single-group only
    print()
    print(f"{'only group':<14} {'#chan':>5} {'mean_IC':>9} {'d_IC':>10} {'IR':>7} {'mean_WFE':>10} {'last_WFE':>10}")
    print("-" * 95)
    for gname, gcols in GROUPS.items():
        r = fit_and_score(X, y, t, gcols)
        delta = r["mean_ic"] - base["mean_ic"]
        last_wfe_str = f"{r['last_wfe']:+.4f}" if r['last_wfe'] is not None else "  nan"
        print(f"{gname:<14} {len(gcols):>5} {r['mean_ic']:>+9.4f} {delta:>+10.4f} {r['ir']:>+7.2f} "
              f"{r['mean_wfe']:>+10.4f} {last_wfe_str:>10}")

    # ── Experiment 3: Forward selection ────────────────────────────────────
    print("\n" + "=" * 95)
    print("EXPERIMENT 3 — FORWARD SELECTION (greedy: add channel with best mean_IC each step)")
    print("=" * 95)
    print(f"{'step':>4}  {'add channel':<24} {'#feat':>5} {'mean_IC':>9} {'IR':>7} {'mean_WFE':>10} {'last_WFE':>10}")
    print("-" * 95)
    selected: List[int] = []
    remaining = list(range(19))
    best_ic_so_far = float("-inf")
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
        last_wfe_str = f"{best_r['last_wfe']:+.4f}" if best_r['last_wfe'] is not None else "  nan"
        peak = " <-- peak" if best_r["mean_ic"] > best_ic_so_far else ""
        if best_r["mean_ic"] > best_ic_so_far:
            best_ic_so_far = best_r["mean_ic"]
        print(f"{step+1:>4}  {CHANNEL_NAMES[best_idx]:<24} {len(selected):>5} "
              f"{best_r['mean_ic']:>+9.4f} {best_r['ir']:>+7.2f} "
              f"{best_r['mean_wfe']:>+10.4f} {last_wfe_str:>10}{peak}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
