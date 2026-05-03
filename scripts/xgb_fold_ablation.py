"""
Walk-forward fold-configuration ablation for XGB-native production model.

Runs the same XGB-native fit (last-timestep features, 19 channels) under
many (n_folds, min_val_days, embargo_bars) combinations on the same data
and reports per-fold + aggregate metrics. Read-only — does not save any
production model.

Usage from project root:
    PYTHONPATH='site-packages;backend' runtime/python/python.exe scripts/xgb_fold_ablation.py
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
from data.signal_history import signal_history
from data.xgboost_model import last_timestep_features


def fit_one_config(
    X_native: np.ndarray, y: np.ndarray, t: np.ndarray,
    n_folds: int, min_val_days: int, embargo_bars: int,
) -> Dict:
    folds = walkforward_folds(
        t, n_folds=n_folds, min_val_days=min_val_days, embargo_bars=embargo_bars
    )
    if not folds:
        return {"folds_built": 0}

    params = {
        "max_depth": 6, "eta": 0.05, "subsample": 0.8,
        "colsample_bytree": 0.8, "alpha": 0.1, "lambda": 1.0,
        "objective": "reg:squarederror", "eval_metric": "rmse",
        "tree_method": "hist", "seed": 42, "verbosity": 0,
    }

    fold_results = []
    ics: List[float] = []
    wfes: List[float] = []
    last_wfe = None
    for i, (tr, va) in enumerate(folds):
        dtrain = xgb.DMatrix(X_native[tr], label=y[tr])
        dval = xgb.DMatrix(X_native[va], label=y[va])
        booster = xgb.train(
            params, dtrain, num_boost_round=500,
            evals=[(dval, "val")], early_stopping_rounds=30, verbose_eval=False,
        )
        vp = booster.predict(dval).astype(np.float32)
        vt = y[va].astype(np.float32)
        ic = compute_ic(vp, vt)
        wfe, _ = _compute_wfe(vt.tolist(), vp.tolist())
        fold_results.append({
            "fold": i, "n_train": len(tr), "n_val": len(va),
            "ic": ic, "wfe": wfe,
            "val_mse": float(np.mean((vp - vt) ** 2)),
        })
        ics.append(ic)
        if wfe is not None:
            wfes.append(wfe)
            last_wfe = wfe   # last fold = production model

    return {
        "folds_built": len(folds),
        "n_folds_arg": n_folds,
        "min_val_days": min_val_days,
        "embargo_bars": embargo_bars,
        "mean_ic": float(np.mean(ics)) if ics else float("nan"),
        "ir": compute_ir(ics),
        "mean_wfe": float(np.mean(wfes)) if wfes else float("nan"),
        "last_fold_wfe": last_wfe,
        "fold_results": fold_results,
    }


def main() -> int:
    print("Loading training data...")
    df = signal_history.get_training_data()
    print(f"  rows={len(df):,}  symbols={df['symbol'].nunique()}")

    print("Building (N, C=19, T=10) windows...")
    X, y, _w, t = build_training_windows(df, T=WINDOW_SIZE)
    X_native = last_timestep_features(X)   # (N, 19)
    print(f"  X_native.shape={X_native.shape}  y.shape={y.shape}")
    print(f"  date range: {pd.Timestamp(t.min(), unit='s')} -> {pd.Timestamp(t.max(), unit='s')}")
    print(f"  span (days): {(t.max() - t.min()) / 86400:.1f}")

    # Configurations to try
    configs: List[Tuple[int, int, int]] = [
        # (n_folds, min_val_days, embargo_bars)
        (3, 14, 1),     # current production
        (3, 30, 1),
        (3, 60, 1),
        (5, 14, 1),
        (5, 30, 1),
        (5, 7,  1),
        (7, 14, 1),
        (7, 7,  1),
        (10, 14, 1),
        (2, 30, 1),
        (2, 60, 1),
        # Embargo sweep on a stable base
        (3, 30, 0),
        (3, 30, 5),
        (5, 14, 0),
        (5, 14, 5),
    ]

    print(f"\n{'config':<22} {'folds':>5} {'mean_IC':>10} {'IR':>8} {'mean_WFE':>10} {'last_WFE':>10}  per-fold (n_val | IC | WFE)")
    print("-" * 130)

    results = []
    for n_folds, mvd, eb in configs:
        t0 = time.perf_counter()
        r = fit_one_config(X_native, y, t, n_folds, mvd, eb)
        elapsed = time.perf_counter() - t0
        cfg_str = f"f={n_folds} d={mvd} e={eb}"
        if r.get("folds_built", 0) == 0:
            print(f"{cfg_str:<22} {'  --':>5}  ! data too short for this config")
            continue
        per_fold = ", ".join(
            f"({fr['n_val']:>5} | {fr['ic']:+.3f} | {('%.3f' % fr['wfe']) if fr['wfe'] is not None else '   nan'})"
            for fr in r["fold_results"]
        )
        last_wfe_str = f"{r['last_fold_wfe']:+.4f}" if r["last_fold_wfe"] is not None else "   nan"
        print(f"{cfg_str:<22} {r['folds_built']:>5} {r['mean_ic']:>+10.4f} "
              f"{r['ir']:>+8.2f} {r['mean_wfe']:>+10.4f} {last_wfe_str:>10}  {per_fold}  ({elapsed:.1f}s)")
        results.append(r)

    # Pick best configs
    valid = [r for r in results if not np.isnan(r["mean_ic"])]
    if valid:
        best_meanic = max(valid, key=lambda r: r["mean_ic"])
        best_lastwfe = max(
            (r for r in valid if r["last_fold_wfe"] is not None),
            key=lambda r: r["last_fold_wfe"], default=None,
        )
        best_robust = max(
            valid,
            key=lambda r: (
                r["mean_ic"]
                + (r["last_fold_wfe"] if r["last_fold_wfe"] is not None else -10)
            ),
        )
        print()
        print(f"Best mean_IC      : f={best_meanic['n_folds_arg']} d={best_meanic['min_val_days']} e={best_meanic['embargo_bars']}  (mean_IC={best_meanic['mean_ic']:+.4f}, last_WFE={best_meanic['last_fold_wfe']})")
        if best_lastwfe is not None:
            print(f"Best last_WFE     : f={best_lastwfe['n_folds_arg']} d={best_lastwfe['min_val_days']} e={best_lastwfe['embargo_bars']}  (last_WFE={best_lastwfe['last_fold_wfe']:+.4f}, mean_IC={best_lastwfe['mean_ic']:+.4f})")
        print(f"Best mean_IC+lastWFE: f={best_robust['n_folds_arg']} d={best_robust['min_val_days']} e={best_robust['embargo_bars']}  (mean_IC={best_robust['mean_ic']:+.4f}, last_WFE={best_robust['last_fold_wfe']})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
