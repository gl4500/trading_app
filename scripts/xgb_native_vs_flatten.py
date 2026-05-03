"""
A/B experiment: flatten-window (current production XGB) vs. last-timestep
tabular (XGB-native) on the same walk-forward folds.

The XGBoost backend currently feeds it (N, 19, T=10) windows flattened to
(N, 190) — a CNN-shaped input. The lagged-return channels (r_1..r_120)
already encode the temporal lookback natively, so the other 9 timesteps
of every channel are mostly redundant and dilute tree-split capacity.

This script uses backend.data.cnn_model.build_training_windows to produce
the same (X, y, w, t) tensor production XGBoost trains on, then runs two
feature variants through the identical walk-forward driver:
    A_flatten     — X.reshape(N, 190)        (current behaviour)
    B_last_t      — X[:, :, -1]              (proposed XGB-native)
    C_last_t_mean — concat(last, mean over T) (compromise: 38 features)

Usage from project root:
    PYTHONPATH='site-packages;backend' runtime/python/python.exe scripts/xgb_native_vs_flatten.py
"""
from __future__ import annotations

import glob
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
from data.signal_history import _attach_macro_features, _compute_return_features


def load_all_history() -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(_BACKEND, "data", "history", "*.parquet")))
    files = [f for f in files if not os.path.basename(f).startswith("__")]
    dfs = []
    for f in files:
        try:
            d = pd.read_parquet(f)
            if "return_5d" in d.columns:
                dfs.append(d)
        except Exception:
            pass
    df = pd.concat(dfs, ignore_index=True)
    df = df.sort_values(["symbol", "snapshot_ts"]).reset_index(drop=True)
    return df


def attach_features(df: pd.DataFrame) -> pd.DataFrame:
    df = _compute_return_features(df)
    df = _attach_macro_features(df)
    return df


def run_xgb_walkforward(
    X: np.ndarray, y: np.ndarray, t: np.ndarray,
    n_folds: int = 3, min_val_days: int = 14, embargo_bars: int = 1,
) -> Dict[str, float]:
    folds = walkforward_folds(t, n_folds=n_folds, min_val_days=min_val_days, embargo_bars=embargo_bars)
    if not folds:
        return {"folds": 0, "n_features": X.shape[1] if X.ndim > 1 else 0,
                "mean_ic": float("nan"), "ir": float("nan"),
                "mean_wfe": float("nan"), "mean_val_mse": float("nan")}

    params = {
        "max_depth":        6, "eta": 0.05, "subsample": 0.8,
        "colsample_bytree": 0.8, "alpha": 0.1, "lambda": 1.0,
        "objective": "reg:squarederror", "eval_metric": "rmse",
        "tree_method": "hist", "seed": 42, "verbosity": 0,
    }
    ics: List[float] = []; wfes: List[float] = []; mses: List[float] = []
    for tr, va in folds:
        dtrain = xgb.DMatrix(X[tr], label=y[tr])
        dval   = xgb.DMatrix(X[va], label=y[va])
        booster = xgb.train(
            params, dtrain, num_boost_round=500,
            evals=[(dval, "val")], early_stopping_rounds=30, verbose_eval=False,
        )
        vp = booster.predict(dval).astype(np.float32)
        vt = y[va].astype(np.float32)
        ics.append(compute_ic(vp, vt))
        wfe_val, _ = _compute_wfe(vt.tolist(), vp.tolist())
        if wfe_val is not None:
            wfes.append(wfe_val)
        mses.append(float(np.mean((vp - vt) ** 2)))

    return {
        "folds":         len(folds),
        "n_features":    X.shape[1],
        "mean_ic":       float(np.mean(ics)) if ics else float("nan"),
        "ir":            compute_ir(ics),
        "mean_wfe":      float(np.mean(wfes)) if wfes else float("nan"),
        "mean_val_mse":  float(np.mean(mses)) if mses else float("nan"),
    }


def main() -> int:
    print("Loading parquets + attaching return/macro features...")
    df = load_all_history()
    df = attach_features(df)
    print(f"  rows={len(df):,}  symbols={df['symbol'].nunique()}")

    print(f"\nBuilding (N, C=19, T={WINDOW_SIZE}) windows via cnn_model.build_training_windows...")
    t0 = time.perf_counter()
    X, y, _w, t = build_training_windows(df, T=WINDOW_SIZE)
    print(f"  X.shape={X.shape}  y.shape={y.shape}  ({time.perf_counter()-t0:.1f}s)")
    if X.ndim != 3 or X.shape[0] == 0:
        print("ERROR: empty or wrong-shape X — aborting")
        return 1

    N, C, T = X.shape
    print(f"\nVariants:")
    print(f"  A_flatten      : (N, C*T) = (N, {C*T})  [current production]")
    print(f"  B_last_t       : (N, C)   = (N, {C})    [XGB-native]")
    print(f"  C_last_plus_mean: (N, 2C) = (N, {2*C})  [last + mean over T]")

    variants: Dict[str, np.ndarray] = {
        "A_flatten":        X.reshape(N, C * T),
        "B_last_t":         X[:, :, -1],
        "C_last_plus_mean": np.concatenate([X[:, :, -1], X.mean(axis=2)], axis=1),
    }

    print(f"\n{'variant':<20} {'#feat':>6} {'folds':>6} {'mean_IC':>10} {'IR':>8} {'mean_WFE':>10} {'val_MSE':>12}")
    print("-" * 92)
    for name, Xv in variants.items():
        t0 = time.perf_counter()
        r = run_xgb_walkforward(Xv, y, t)
        elapsed = time.perf_counter() - t0
        print(f"{name:<20} {r['n_features']:>6} {r['folds']:>6} "
              f"{r['mean_ic']:>+10.4f} {r['ir']:>+8.2f} {r['mean_wfe']:>+10.4f} "
              f"{r['mean_val_mse']:>12.6f}  ({elapsed:.1f}s)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
