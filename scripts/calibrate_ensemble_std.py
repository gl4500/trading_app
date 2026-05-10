"""
Ensemble-std calibration check.

Loads the K bootstrapped boosters from train_xgb_ensemble.py and
evaluates whether the per-prediction ensemble std is a useful
confidence proxy. Specifically:

  1. Re-run walk-forward CV using the SAME data + filter as the
     ensemble was trained on, but evaluate the ensemble (not a single
     booster) on each fold's validation rows.
  2. For each val row, compute (ensemble_mean, ensemble_std, residual).
  3. Bin val rows by std percentile (deciles). For each bin, report
     mean(|residual|), IC, and what fraction of trades crossed +/- the
     direction threshold. If high-std bins have higher |residual| AND
     lower IC, std is a CALIBRATED confidence signal worth using.
  4. Spearman correlation between std and |residual| across all val
     rows — single number summary.

Calibration outcome:
  - rho(std, |residual|) > +0.10  → calibrated, std is useful
  - rho ~ 0                       → std is uninformative (don't gate
                                    on it; ensemble still useful as
                                    a mean-prediction averager)
  - rho < 0                       → broken (high-std predictions
                                    are MORE accurate — investigate)

Run from project root:
    PYTHONIOENCODING=utf-8 PYTHONPATH='site-packages;backend' \\
      runtime/python/python.exe scripts/calibrate_ensemble_std.py
"""
from __future__ import annotations

import json
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

PEAK_16: List[str] = [
    "corr_spy_20d", "earnings_score", "hist_seasonal", "r_5", "r_20", "r_1",
    "hist_volume_pattern", "r_5d", "r_60d", "hist_momentum_alignment", "mom_12_1",
    "r_1d", "alpaca_score", "iv_rv_score", "r_20d", "agent_consensus",
]

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


def spearman_rho(a: np.ndarray, b: np.ndarray) -> float:
    """Spearman rank correlation, no scipy dependency."""
    if len(a) < 2 or len(b) < 2:
        return float("nan")
    ra = pd.Series(a).rank().values
    rb = pd.Series(b).rank().values
    return float(np.corrcoef(ra, rb)[0, 1])


def load_ensemble(k: int) -> List[xgb.Booster]:
    """Load K trained boosters from disk."""
    boosters = []
    for i in range(k):
        path = os.path.join(_MODEL_DIR, f"signal_xgb_b{i}.json")
        if not os.path.exists(path):
            raise FileNotFoundError(f"Missing booster: {path}")
        b = xgb.Booster()
        b.load_model(path)
        boosters.append(b)
    return boosters


def main() -> int:
    print("Ensemble-std calibration check")
    print("=" * 100)

    # Load ensemble metadata
    if not os.path.exists(_ENSEMBLE_META):
        print(f"ERROR: ensemble meta not found at {_ENSEMBLE_META}")
        print("Run scripts/train_xgb_ensemble.py first.")
        return 1
    with open(_ENSEMBLE_META) as fh:
        meta = json.load(fh)
    K = int(meta["k"])
    print(f"  K={K} boosters from {meta['trained_at']}")

    print(f"\nLoading the K={K} boosters...")
    t0 = time.time()
    boosters = load_ensemble(K)
    print(f"  loaded in {time.time()-t0:.1f}s")

    # ── Re-load training data for walk-forward eval ────────────────────────
    # The ensemble was trained on bootstrap samples of the FULL dataset, so
    # there's no truly clean OOB region. Instead, use walk-forward folds:
    # train K NEW boosters on each fold's train set (with bootstrap sampling
    # WITHIN that fold), then evaluate on val. This matches how the live
    # system would behave in production — each fold's val is "future" data
    # the ensemble hasn't seen.

    print("\nLoading training data for walk-forward calibration...")
    t0 = time.time()
    df = signal_history.get_training_data()
    df["return_10d_exp"] = compute_forward_return(df, 10)
    df["return_5d"] = np.clip(df["return_10d_exp"], -0.30, 0.30)
    X_3d, y, _w, t_arr = build_training_windows(df, T=WINDOW_SIZE)
    X = last_timestep_features(X_3d)
    cols = names_to_indices(PEAK_16)
    Xs = X[:, cols]
    print(f"  X.shape={Xs.shape}  ({time.time()-t0:.1f}s)")

    folds = walkforward_folds(t_arr, n_folds=3, min_val_days=14, embargo_bars=1)
    print(f"  {len(folds)} walk-forward folds")

    # ── Per-fold: fit K new boosters on bootstrap samples of that fold's
    # ── train set, evaluate ensemble on val
    print("\nPer-fold ensemble eval:")
    print(f"  {'fold':<5} {'n_train':>8} {'n_val':>8} {'mean_IC':>9} {'std (mean)':>12} "
          f"{'rho(std,|res|)':>16} {'P(IC>0|low std)':>17}")

    rng = np.random.default_rng(42)
    all_pred_mean: List[np.ndarray] = []
    all_pred_std:  List[np.ndarray] = []
    all_actual:    List[np.ndarray] = []

    for f, (tr, va) in enumerate(folds):
        # Train K boosters on K bootstrap samples of TR
        tr_idx_array = np.asarray(tr)
        n_tr = len(tr_idx_array)
        n_va = len(va)
        preds = np.zeros((K, n_va), dtype=np.float32)
        for k in range(K):
            sample_idx = rng.integers(0, n_tr, size=n_tr)
            X_boot = Xs[tr_idx_array[sample_idx]]
            y_boot = y[tr_idx_array[sample_idx]]
            in_bag = np.zeros(n_tr, dtype=bool)
            in_bag[sample_idx] = True
            oob_local = np.where(~in_bag)[0]
            if len(oob_local) < 100:
                oob_local = rng.choice(n_tr, size=max(int(0.1 * n_tr), 100),
                                       replace=False)
            X_oob = Xs[tr_idx_array[oob_local]]
            y_oob = y[tr_idx_array[oob_local]]
            params = dict(PARAMS, seed=42 + k + 1000 * f)
            dtrain = xgb.DMatrix(X_boot, label=y_boot)
            dval = xgb.DMatrix(X_oob, label=y_oob)
            booster = xgb.train(
                params, dtrain, num_boost_round=500,
                evals=[(dval, "oob")], early_stopping_rounds=30, verbose_eval=False,
            )
            dva = xgb.DMatrix(Xs[va])
            preds[k] = booster.predict(dva)
        pred_mean = preds.mean(axis=0)
        pred_std  = preds.std(axis=0)
        actual    = y[va].astype(np.float32)
        residual  = pred_mean - actual

        ensemble_ic = compute_ic(pred_mean, actual)
        rho = spearman_rho(pred_std, np.abs(residual))

        # IC restricted to lowest-std third of predictions
        n3 = max(int(0.33 * n_va), 100)
        order = np.argsort(pred_std)
        low_std_idx = order[:n3]
        low_std_ic = compute_ic(pred_mean[low_std_idx], actual[low_std_idx])

        print(f"  f={f:<3} {n_tr:>8,} {n_va:>8,} {ensemble_ic:>+9.4f} {pred_std.mean():>+12.5f} "
              f"{rho:>+16.4f}  {low_std_ic:>+15.4f}")

        all_pred_mean.append(pred_mean)
        all_pred_std.append(pred_std)
        all_actual.append(actual)

    # ── Aggregate across folds ───────────────────────────────────────────
    pm = np.concatenate(all_pred_mean)
    ps = np.concatenate(all_pred_std)
    ac = np.concatenate(all_actual)
    res = np.abs(pm - ac)

    print("\n" + "=" * 100)
    print("AGGREGATE (all folds pooled)")
    print("=" * 100)
    print(f"  n_predictions   = {len(pm):,}")
    print(f"  ensemble IC     = {compute_ic(pm, ac):+.4f}")
    print(f"  std mean        = {ps.mean():+.5f}")
    print(f"  std std         = {ps.std():+.5f}")
    print(f"  rho(std, |res|) = {spearman_rho(ps, res):+.4f}")
    print(f"  rho(|mean|,|res|)={spearman_rho(np.abs(pm), res):+.4f}  (sanity — bigger predictions = bigger errors?)")

    # ── Std deciles: does higher-std bin have higher mean |residual|? ───
    deciles = np.percentile(ps, np.arange(10, 101, 10))
    print(f"\nStd deciles (low → high) and their mean |residual|:")
    print(f"  {'decile':>7} {'std_max':>10} {'n':>7} {'mean|res|':>11} {'IC':>9}")
    sort_idx = np.argsort(ps)
    chunk = max(len(ps) // 10, 1)
    for d in range(10):
        slc = sort_idx[d*chunk:(d+1)*chunk] if d < 9 else sort_idx[d*chunk:]
        if len(slc) == 0:
            continue
        d_ic = compute_ic(pm[slc], ac[slc])
        print(f"  {d+1:>7} {ps[slc].max():>+10.5f} {len(slc):>7,} "
              f"{res[slc].mean():>+11.5f} {d_ic:>+9.4f}")

    # ── Verdict ───────────────────────────────────────────────────────────
    rho = spearman_rho(ps, res)
    print("\n" + "=" * 100)
    print("VERDICT")
    print("=" * 100)
    if rho > 0.10:
        print(f"  rho(std, |residual|) = {rho:+.4f}  →  CALIBRATED")
        print("  Safe to gate position size by ensemble std. Higher-std predictions")
        print("  are reliably less accurate — downsizing them reduces variance without")
        print("  giving up much expected return.")
    elif rho > 0.05:
        print(f"  rho(std, |residual|) = {rho:+.4f}  →  WEAKLY CALIBRATED")
        print("  Std has some signal but is noisy. Consider using std as a soft")
        print("  multiplier (e.g., 1 - 0.5*z(std)) rather than a hard gate.")
    elif rho > -0.05:
        print(f"  rho(std, |residual|) = {rho:+.4f}  →  UNINFORMATIVE")
        print("  Std doesn't predict residual size. Don't gate on it. Ensemble mean")
        print("  is still useful as a variance-reduced predictor (vs single booster).")
    else:
        print(f"  rho(std, |residual|) = {rho:+.4f}  →  BROKEN / INVERSE")
        print("  High-std predictions are MORE accurate — investigate before using.")
        print("  Could be a numerical bug or a regime where booster disagreement")
        print("  signals genuine ambiguity that the ensemble mean handles well.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
