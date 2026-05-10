"""
Bootstrap CI on the 16-channel model's IC.

Loads the same training data + 16-channel filter as production, runs
walk-forward CV once to get (val_pred, val_actual) tuples per fold, then
bootstrap-resamples the validation predictions to get a distribution of
IC values. Reports 95% CI per fold and overall.

Tells us whether the +0.2549 mean_IC is structural or fold-luck.

Run from project root:
    PYTHONIOENCODING=utf-8 PYTHONPATH='site-packages;backend' \\
      runtime/python/python.exe scripts/bootstrap_ic_ci.py
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

os.environ["MODEL_BACKEND"] = "xgboost"

from data.cnn_evaluation import compute_ic, walkforward_folds
from data.cnn_model import build_training_windows, ALL_CHANNEL_COLUMNS, WINDOW_SIZE
from data.signal_history import signal_history
from data.xgboost_model import last_timestep_features

# Same 16-channel peak from forward selection 2026-05-09
PEAK_16: List[str] = [
    "corr_spy_20d", "earnings_score", "hist_seasonal", "r_5", "r_20", "r_1",
    "hist_volume_pattern", "r_5d", "r_60d", "hist_momentum_alignment", "mom_12_1",
    "r_1d", "alpaca_score", "iv_rv_score", "r_20d", "agent_consensus",
]
# Old production filter for direct comparison
OLD_8: List[str] = [
    "analyst_score", "earnings_score", "alpaca_score", "iv_rv_score",
    "r_120", "macro_vix_norm", "macro_spy_5d_back", "macro_breadth_back",
]

PARAMS = {
    "max_depth": 6, "eta": 0.05, "subsample": 0.8,
    "colsample_bytree": 0.8, "alpha": 0.1, "lambda": 1.0,
    "objective": "reg:squarederror", "eval_metric": "rmse",
    "tree_method": "hist", "seed": 42, "verbosity": 0,
}

N_BOOTSTRAP = 1000
RNG_SEED = 42


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


def run_walkforward_with_predictions(
    X: np.ndarray, y: np.ndarray, t: np.ndarray, cols: List[int]
) -> List[Tuple[np.ndarray, np.ndarray]]:
    """Run 3-fold walk-forward CV. Return (val_pred, val_actual) per fold."""
    Xs = X[:, cols]
    folds = walkforward_folds(t, n_folds=3, min_val_days=14, embargo_bars=1)
    fold_preds: List[Tuple[np.ndarray, np.ndarray]] = []
    for tr, va in folds:
        dtrain = xgb.DMatrix(Xs[tr], label=y[tr])
        dval = xgb.DMatrix(Xs[va], label=y[va])
        booster = xgb.train(
            PARAMS, dtrain, num_boost_round=500,
            evals=[(dval, "val")], early_stopping_rounds=30, verbose_eval=False,
        )
        vp = booster.predict(dval).astype(np.float32)
        vt = y[va].astype(np.float32)
        fold_preds.append((vp, vt))
    return fold_preds


def bootstrap_ic(
    pred: np.ndarray, actual: np.ndarray, n_boot: int = N_BOOTSTRAP,
    seed: int = RNG_SEED,
) -> Dict[str, float]:
    """Bootstrap N_BOOTSTRAP times: resample (pred, actual) with replacement, compute IC."""
    rng = np.random.default_rng(seed)
    n = len(pred)
    ics = np.empty(n_boot, dtype=np.float64)
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        ics[i] = compute_ic(pred[idx], actual[idx])
    return {
        "mean":  float(np.mean(ics)),
        "std":   float(np.std(ics)),
        "p2_5":  float(np.percentile(ics,  2.5)),
        "p50":   float(np.percentile(ics, 50.0)),
        "p97_5": float(np.percentile(ics, 97.5)),
        "p_pos": float((ics > 0).mean()),
    }


def names_to_indices(names: List[str]) -> List[int]:
    return [list(ALL_CHANNEL_COLUMNS).index(n) for n in names]


def main() -> int:
    print(f"Bootstrap IC CI — N_BOOTSTRAP={N_BOOTSTRAP}")
    print("=" * 92)

    print("\nLoading training data...")
    t0 = time.time()
    df = signal_history.get_training_data()
    print(f"  rows={len(df):,}  symbols={df['symbol'].nunique()}  ({time.time()-t0:.1f}s)")

    print("\nComputing 10d forward returns...")
    t0 = time.time()
    df["return_10d_exp"] = compute_forward_return(df, 10)
    df["return_5d"] = np.clip(df["return_10d_exp"], -0.30, 0.30)
    print(f"  ({time.time()-t0:.1f}s)")

    print(f"\nBuilding (N, 38, {WINDOW_SIZE}) windows...")
    t0 = time.time()
    X_3d, y, _w, t = build_training_windows(df, T=WINDOW_SIZE)
    X = last_timestep_features(X_3d)
    print(f"  X.shape={X.shape}  ({time.time()-t0:.1f}s)")

    print()
    for label, names in (("OLD 8-ch baseline", OLD_8), ("NEW 16-ch peak", PEAK_16)):
        print("=" * 92)
        print(f"{label}: {len(names)} channels")
        print("=" * 92)

        cols = names_to_indices(names)
        print(f"Running walk-forward CV...")
        t0 = time.time()
        fold_preds = run_walkforward_with_predictions(X, y, t, cols)
        print(f"  trained {len(fold_preds)} folds in {time.time()-t0:.1f}s")

        # Per-fold bootstrap
        print(f"\nPer-fold IC bootstrap CI ({N_BOOTSTRAP} resamples):")
        print(f"  {'fold':<6} {'n_val':>8} {'mean':>9} {'std':>8} {'95% CI':>22} {'P(IC>0)':>9}")
        all_pred, all_actual = [], []
        for f, (vp, vt) in enumerate(fold_preds):
            stats = bootstrap_ic(vp, vt)
            print(f"  fold {f:<2} {len(vp):>8} {stats['mean']:>+9.4f} {stats['std']:>+8.4f} "
                  f"  [{stats['p2_5']:>+7.4f}, {stats['p97_5']:>+7.4f}] {stats['p_pos']*100:>7.1f}%")
            all_pred.append(vp)
            all_actual.append(vt)

        # Pooled bootstrap (treat all val rows as one sample)
        pred_all = np.concatenate(all_pred)
        actual_all = np.concatenate(all_actual)
        pooled = bootstrap_ic(pred_all, actual_all)
        print(f"\n  POOLED  {len(pred_all):>8} {pooled['mean']:>+9.4f} {pooled['std']:>+8.4f} "
              f"  [{pooled['p2_5']:>+7.4f}, {pooled['p97_5']:>+7.4f}] {pooled['p_pos']*100:>7.1f}%")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
