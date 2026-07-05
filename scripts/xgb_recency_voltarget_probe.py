"""
H4 + H5 sidecar probe — recency-weighted training & vol-scaled target.

Both are magnitude-axis hypotheses from docs/model_improvement_ledger.md that
test whether a cheap change lifts the *most-recent-fold* WFE (`last_WFE`) above
zero — the same bar the production WFE gate uses to (un)block BUYs.

  H4  Recency-weighted / time-decay training. Current sample_weights only
      up-weight top-agent-correct rows, not recency. Add exp time-decay
      weight = 0.5 ** (age_days / halflife) within each training fold and
      compare last-fold WFE. Halflife swept over {90, 180, 365} days.

  H5  Target transform: predict vol-scaled return y' = y / rv_20d, invert the
      prediction (pred = pred' * rv_20d, rv_20d is a trailing feature known at
      snapshot → no leakage) and compare WFE against the raw target.

Read-only: loads production parquets via signal_history, writes NOTHING to
trading.db or the production model. Uses the leak-free embargo (embargo_days =
LABEL_HORIZON_DAYS) shipped in the H1 fix, so every config is honest.

Usage from project root:
    PYTHONPATH='site-packages;backend' runtime/python/python.exe \
        scripts/xgb_recency_voltarget_probe.py
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(os.path.dirname(_HERE), "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import xgboost as xgb  # noqa: E402

from data.cnn_evaluation import compute_ic, compute_ir, walkforward_folds  # noqa: E402
from data.cnn_model import (  # noqa: E402
    _compute_wfe, build_training_windows, WINDOW_SIZE,
    ALL_CHANNEL_COLUMNS, LABEL_HORIZON_DAYS,
)
from data.signal_history import signal_history  # noqa: E402
from data.xgboost_model import last_timestep_features  # noqa: E402

CHANNEL_NAMES: List[str] = list(ALL_CHANNEL_COLUMNS)
N_CHANNELS = len(CHANNEL_NAMES)
# rv_20d is *annualized* realized vol (median ~0.30), not a raw 20d sigma, so a
# fixed 0.01 floor is 30x below scale and lets low-/zero-rv rows explode y/rv.
# The floor is data-driven (5th pctile of positive rv) and set in main().

PARAMS = {
    "max_depth": 6, "eta": 0.05, "subsample": 0.8,
    "colsample_bytree": 0.8, "alpha": 0.1, "lambda": 1.0,
    "objective": "reg:squarederror", "eval_metric": "rmse",
    "tree_method": "hist", "seed": 42, "verbosity": 0,
}


def compute_forward_return(df, days: int):
    import pandas as pd
    secs = days * 86_400.0
    out = pd.Series(np.nan, index=df.index, dtype=np.float64)
    for _sym, grp in df.groupby("symbol", sort=False):
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


def score_config(
    X: np.ndarray, y: np.ndarray, t: np.ndarray,
    rv: Optional[np.ndarray] = None,
    halflife_days: Optional[float] = None,
    vol_scale: bool = False,
    rv_floor: float = 0.05,
) -> Dict:
    """One walk-forward pass. Optionally recency-weighted and/or vol-scaled."""
    folds = walkforward_folds(
        t, n_folds=3, min_val_days=14,
        embargo_bars=1, embargo_days=LABEL_HORIZON_DAYS,
    )
    if not folds:
        return {"mean_ic": float("nan"), "ir": float("nan"),
                "mean_wfe": float("nan"), "last_wfe": None, "n_folds": 0}
    ics: List[float] = []
    wfes: List[float] = []
    last_wfe = None
    for tr, va in folds:
        Xtr, Xva = X[tr], X[va]
        # Target: raw or vol-scaled (invert prediction back to raw scale).
        if vol_scale:
            rv_tr = np.maximum(rv[tr], rv_floor)
            ytr_fit = y[tr] / rv_tr
        else:
            ytr_fit = y[tr]
        # Weights: uniform or exponential recency decay within the fold.
        if halflife_days is not None:
            age_days = (t[tr].max() - t[tr]) / 86_400.0
            wtr = np.power(0.5, age_days / halflife_days).astype(np.float32)
        else:
            wtr = None
        dtrain = xgb.DMatrix(Xtr, label=ytr_fit, weight=wtr)
        dval = xgb.DMatrix(Xva)
        booster = xgb.train(PARAMS, dtrain, num_boost_round=500, verbose_eval=False)
        vp = booster.predict(dval).astype(np.float32)
        if vol_scale:
            vp = vp * np.maximum(rv[va], rv_floor).astype(np.float32)
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
        "n_folds": len(folds),
    }


def _fmt(r: Dict) -> str:
    lw = f"{r['last_wfe']:+.4f}" if r["last_wfe"] is not None else "  nan"
    return (f"mean_IC={r['mean_ic']:+.4f}  IR={r['ir']:+.2f}  "
            f"mean_WFE={r['mean_wfe']:+.4f}  last_WFE={lw}  folds={r['n_folds']}")


def main() -> int:
    print("Loading training data...")
    df = signal_history.get_training_data()
    print(f"  rows={len(df):,}  symbols={df['symbol'].nunique()}")

    print("\nComputing 10d forward returns from price...")
    df["return_10d_exp"] = compute_forward_return(df, 10)
    df["return_5d"] = np.clip(df["return_10d_exp"], -0.30, 0.30)  # label slot

    print(f"\nBuilding (N, {N_CHANNELS}, {WINDOW_SIZE}) windows...")
    X_3d, y, _w, t = build_training_windows(df, T=WINDOW_SIZE)
    X = last_timestep_features(X_3d)
    rv_idx = CHANNEL_NAMES.index("rv_20d")
    rv = X[:, rv_idx].astype(np.float64)
    rv_floor = float(np.percentile(rv[rv > 0], 5))  # data-driven, not 30x below scale
    print(f"  X.shape={X.shape}  rv_20d idx={rv_idx}  "
          f"rv median={np.median(rv):.4f}  rv>0 frac={np.mean(rv > 0):.3f}  "
          f"rv_floor(p05)={rv_floor:.4f}")

    print("\n" + "=" * 78)
    print("BASELINE — uniform weights, raw target (leak-free embargo=10d)")
    print("=" * 78)
    base = score_config(X, y, t)
    print("  " + _fmt(base))

    print("\n" + "=" * 78)
    print("H4 — recency-weighted training (halflife sweep)")
    print("=" * 78)
    h4_results = {}
    for hl in (90.0, 180.0, 365.0):
        r = score_config(X, y, t, halflife_days=hl)
        h4_results[hl] = r
        print(f"  halflife={hl:>5.0f}d  " + _fmt(r))
    h4_best_hl = max(h4_results, key=lambda k: (h4_results[k]["last_wfe"] or -9))
    h4_best = h4_results[h4_best_hl]

    print("\n" + "=" * 78)
    print(f"H5 — vol-scaled target  y' = y / max(rv_20d, {rv_floor:.4f}), inverted")
    print("=" * 78)
    h5 = score_config(X, y, t, rv=rv, vol_scale=True, rv_floor=rv_floor)
    print("  " + _fmt(h5))

    def verdict(name: str, r: Dict, extra: str = "") -> None:
        b_lw = base["last_wfe"] if base["last_wfe"] is not None else float("nan")
        r_lw = r["last_wfe"] if r["last_wfe"] is not None else float("nan")
        passed = (r["last_wfe"] is not None) and (r["last_wfe"] > 0)
        beats = r_lw - b_lw
        tag = "GO" if passed else "NO-GO (FALSIFIED)"
        print(f"  {name}: last_WFE={r_lw:+.4f} (baseline {b_lw:+.4f}, "
              f"delta {beats:+.4f}) {extra}  -> {tag}")

    print("\n" + "=" * 78)
    print("VERDICT  (falsifier: last_WFE must rise above 0 to unblock the gate)")
    print("=" * 78)
    verdict("H4", h4_best, extra=f"[best halflife={h4_best_hl:.0f}d]")
    verdict("H5", h5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
