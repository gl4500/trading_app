"""
Train K bootstrapped XGBoost boosters for ensemble uncertainty estimation.

Each booster trains on a bootstrap-with-replacement sample of the same
training data the production model uses. At inference time, running all
K boosters and reporting (mean, std) gives a per-prediction confidence
proxy: high std = boosters disagree = system is uncertain.

Saves to backend/data/models/signal_xgb_b{0..K-1}.json (XGB native format)
plus a single sidecar metadata file at signal_xgb_ensemble.meta.json.

The production model at signal_xgb.json is UNCHANGED — this is additive.
The live signal_model.predict() can opt into the ensemble by calling a
new ensemble_predict() method (Stage 3, separate PR).

Run from project root:
    PYTHONIOENCODING=utf-8 PYTHONPATH='site-packages;backend' \\
      runtime/python/python.exe scripts/train_xgb_ensemble.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Dict, List

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
from config import config

# Fallback filter when XGB_FEATURE_FILTER env is unset (used to be the live
# production filter; the env override now drives both the main model AND
# this ensemble so they stay consistent).
_FALLBACK_FILTER: List[str] = [
    "corr_spy_20d", "earnings_score", "hist_seasonal", "r_5", "r_20", "r_1",
    "hist_volume_pattern", "r_5d", "r_60d", "hist_momentum_alignment", "mom_12_1",
    "r_1d", "alpaca_score", "iv_rv_score", "r_20d", "agent_consensus",
]


def _resolve_filter() -> List[str]:
    """Read the live XGB_FEATURE_FILTER env (set by .env or shell). Falls
    back to the documented 16-ch peak only when the env is empty — the env
    is the single source of truth so this script never trains a different
    filter than the production model.
    """
    raw = os.getenv("XGB_FEATURE_FILTER", "").strip()
    if not raw:
        return list(_FALLBACK_FILTER)
    return [s.strip() for s in raw.split(",") if s.strip()]


ACTIVE_FILTER: List[str] = _resolve_filter()

# K boosters in the ensemble. 10 gives reasonable variance reduction;
# more gets diminishing returns and increased disk + inference cost.
K_BOOTSTRAP = 10

# Per-booster XGBoost hyperparameters — same as production training so
# (saved booster, ensemble booster) are comparable.
PARAMS = {
    "max_depth": 6, "eta": 0.05, "subsample": 0.8,
    "colsample_bytree": 0.8, "alpha": 0.1, "lambda": 1.0,
    "objective": "reg:squarederror", "eval_metric": "rmse",
    "tree_method": "hist", "verbosity": 0,
}

_MODEL_DIR = os.path.join(_BACKEND, "data", "models")
_ENSEMBLE_META = os.path.join(_MODEL_DIR, "signal_xgb_ensemble.meta.json")


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


def names_to_indices(names: List[str]) -> List[int]:
    return [list(ALL_CHANNEL_COLUMNS).index(n) for n in names]


def main() -> int:
    print(f"Bootstrap-ensemble training — K={K_BOOTSTRAP} boosters")
    print(f"Filter: {len(ACTIVE_FILTER)}-channel ({', '.join(ACTIVE_FILTER[:6])}, ...)")
    print("=" * 100)

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
    X_3d, y, _w, t_arr = build_training_windows(df, T=WINDOW_SIZE)
    X = last_timestep_features(X_3d)
    print(f"  X.shape={X.shape}  ({time.time()-t0:.1f}s)")

    cols = names_to_indices(ACTIVE_FILTER)
    Xs = X[:, cols]
    print(f"  filtered to {Xs.shape[1]} channels")

    # ── Use all data for training (live model gets fitted on full dataset)
    # ── For each booster, sample with replacement from the full training set
    n_total = len(Xs)
    print(f"\nTotal samples: {n_total:,}")
    print(f"Each booster trains on a bootstrap sample of size {n_total:,} (with replacement)")
    print()

    rng = np.random.default_rng(42)
    booster_metas: List[Dict] = []
    t0_train = time.time()

    for k in range(K_BOOTSTRAP):
        t_k = time.time()
        # Bootstrap sample for this booster
        sample_idx = rng.integers(0, n_total, size=n_total)
        X_boot = Xs[sample_idx]
        y_boot = y[sample_idx]

        # Use OOB rows as validation set for early stopping
        in_bag = np.zeros(n_total, dtype=bool)
        in_bag[sample_idx] = True
        oob_idx = np.where(~in_bag)[0]
        # If by some chance OOB is empty (rare with n>=10), fall back to a
        # random 10% holdout
        if len(oob_idx) < 100:
            oob_idx = rng.choice(n_total, size=max(int(0.1 * n_total), 100), replace=False)
        X_oob = Xs[oob_idx]
        y_oob = y[oob_idx]

        # Per-booster seed varies for additional diversity
        params = dict(PARAMS, seed=42 + k)
        dtrain = xgb.DMatrix(X_boot, label=y_boot)
        dval = xgb.DMatrix(X_oob, label=y_oob)
        booster = xgb.train(
            params, dtrain, num_boost_round=500,
            evals=[(dval, "oob")], early_stopping_rounds=30, verbose_eval=False,
        )

        # Spot-check IC on OOB
        oob_pred = booster.predict(dval).astype(np.float32)
        oob_ic = compute_ic(oob_pred, y_oob.astype(np.float32))

        # Save
        path = os.path.join(_MODEL_DIR, f"signal_xgb_b{k}.json")
        booster.save_model(path)

        meta = {
            "k": k,
            "seed": 42 + k,
            "n_train": int(len(X_boot)),
            "n_unique_train": int(in_bag.sum()),
            "n_oob_val": int(len(oob_idx)),
            "oob_ic": float(oob_ic),
            "best_iteration": int(getattr(booster, "best_iteration", -1)),
            "path": path,
        }
        booster_metas.append(meta)

        print(f"  k={k:>2}: n_train={meta['n_train']:>7,}  unique={meta['n_unique_train']:>7,} "
              f"({100*meta['n_unique_train']/n_total:>4.1f}%)  oob_n={meta['n_oob_val']:>7,}  "
              f"oob_IC={oob_ic:>+.4f}  best_iter={meta['best_iteration']:>3}  "
              f"({time.time()-t_k:.1f}s)")

    print(f"\nTraining complete in {time.time()-t0_train:.1f}s")

    # ── Save sidecar metadata for the ensemble ─────────────────────────────
    ensemble_meta = {
        "k": K_BOOTSTRAP,
        "channels": ACTIVE_FILTER,
        "n_channels": len(ACTIVE_FILTER),
        "params": PARAMS,
        "n_total": int(n_total),
        "label_horizon_col": "return_10d (clipped to ±30% as return_5d slot)",
        "y_std": float(np.std(y)),
        "boosters": booster_metas,
        "trained_at": time.time(),
    }
    with open(_ENSEMBLE_META, "w") as fh:
        json.dump(ensemble_meta, fh, indent=2)
    print(f"\nSidecar saved: {_ENSEMBLE_META}")

    # ── Quick aggregate sanity check ───────────────────────────────────────
    # Predict with each booster on 10% random holdout, check ensemble IC
    holdout_idx = rng.choice(n_total, size=int(0.1 * n_total), replace=False)
    Xh = Xs[holdout_idx]
    yh = y[holdout_idx]
    dh = xgb.DMatrix(Xh)

    preds = np.zeros((K_BOOTSTRAP, len(holdout_idx)), dtype=np.float32)
    for k in range(K_BOOTSTRAP):
        b = xgb.Booster()
        b.load_model(os.path.join(_MODEL_DIR, f"signal_xgb_b{k}.json"))
        preds[k] = b.predict(dh)

    mean_pred = preds.mean(axis=0)
    std_pred  = preds.std(axis=0)
    ensemble_ic = compute_ic(mean_pred, yh.astype(np.float32))

    print()
    print("=" * 100)
    print("ENSEMBLE QUICK SANITY (10% random holdout, OOB-leaky)")
    print("=" * 100)
    print(f"  ensemble_mean_IC = {ensemble_ic:+.4f}")
    print(f"  std distribution: min={std_pred.min():.5f}  median={np.median(std_pred):.5f}  "
          f"max={std_pred.max():.5f}  mean={std_pred.mean():.5f}")
    print(f"  Note: this holdout overlaps boosters' training samples; for true OOB")
    print(f"  evaluation, run scripts/calibrate_ensemble_std.py against fold-2 data.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
