"""
Price-tier ablation: does the XGB model perform differently across
low-vs-high-price stocks?

Buckets symbols by their median observed price, refits the same XGB-native
walk-forward on each tier, and reports per-tier IC + cash-flow translation
using realistic per-tier friction estimates (round-trip bid-ask spread
scales inversely with price for retail brokers).

Usage from project root:
    PYTHONPATH='site-packages;backend' runtime/python/python.exe scripts/xgb_price_tier_ablation.py
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

PARAMS = {
    "max_depth": 6, "eta": 0.05, "subsample": 0.8,
    "colsample_bytree": 0.8, "alpha": 0.1, "lambda": 1.0,
    "objective": "reg:squarederror", "eval_metric": "rmse",
    "tree_method": "hist", "seed": 42, "verbosity": 0,
}

# Realistic round-trip friction (bid-ask spread + slippage) by price tier.
# Numbers are conservative-mid retail estimates; institutional desks see less.
ROUND_TRIP_FRICTION_PCT: Dict[str, float] = {
    "<$5":      0.020,   # 2.0% — wide spreads, often stale quotes
    "$5-$10":   0.010,   # 1.0%
    "$10-$25":  0.005,   # 0.5%
    "$25-$100": 0.002,   # 0.2%
    "$100-$500": 0.0015, # 0.15%
    ">$500":    0.0010,  # 0.10%
}
TIER_BOUNDS: List[Tuple[str, float, float]] = [
    ("<$5",        0,    5),
    ("$5-$10",     5,   10),
    ("$10-$25",   10,   25),
    ("$25-$100",  25,  100),
    ("$100-$500", 100, 500),
    (">$500",     500, 1e9),
]


def fit_and_score(X: np.ndarray, y: np.ndarray, t: np.ndarray) -> Dict:
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
        dtrain = xgb.DMatrix(X[tr], label=y[tr])
        dval = xgb.DMatrix(X[va], label=y[va])
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

    # Per-symbol median price
    median_price = df.groupby("symbol")["price"].median()
    print(f"\nPrice distribution across {len(median_price)} symbols:")
    for q in [0.05, 0.25, 0.5, 0.75, 0.95]:
        print(f"  p{int(q*100):>2}: ${median_price.quantile(q):>8.2f}")
    print(f"  min=${median_price.min():.2f}  max=${median_price.max():.2f}")

    print(f"\nSymbols per tier:")
    for label, lo, hi in TIER_BOUNDS:
        n = ((median_price >= lo) & (median_price < hi)).sum()
        print(f"  {label:<10}  {n} symbols")

    # Build features once on the full set; we'll filter the (X, y, t) per tier
    # to keep the 19-channel structure consistent.
    print("\nBuilding (N, C=19, T=10) windows on full set...")
    X_3d, y, _w, t = build_training_windows(df, T=WINDOW_SIZE)
    X = last_timestep_features(X_3d)
    # We need to know which tier each window belongs to. The window's tier
    # is determined by the LAST timestamp's symbol — recreate that mapping.
    # build_training_windows iterates per-symbol, in groupby("symbol") order,
    # which we can replicate to align indices.

    # Replicate the iteration to capture symbol-per-window
    print("Mapping windows back to symbols...")
    from data.signal_history import (
        SOURCE_COLUMNS, AGENT_COLUMNS, RV_COLUMNS, RETURN_COLUMNS,
        _MACRO_COLUMN_MAP, _apply_cnn_feature_transforms,
    )
    df2 = _apply_cnn_feature_transforms(df)
    macro_cols = list(_MACRO_COLUMN_MAP.values())
    feat_cols = (list(SOURCE_COLUMNS) + list(AGENT_COLUMNS)
                 + list(RV_COLUMNS) + list(RETURN_COLUMNS) + macro_cols)
    label_col = "return_5d"
    syms_per_window: List[str] = []
    win_prices: List[float] = []
    for sym, grp in df2.groupby("symbol"):
        grp = grp.sort_values("snapshot_ts").reset_index(drop=True)
        if not all(c in grp.columns for c in feat_cols):
            continue
        rets = grp[label_col].values.astype(np.float32)
        prices = grp["price"].values.astype(np.float32)
        for i in range(len(grp)):
            if np.isnan(rets[i]):
                continue
            if i + 1 < WINDOW_SIZE:
                pad = WINDOW_SIZE - (i + 1)
                if i + 1 == 0:
                    continue
                # Same handling as build_training_windows — pad creates a window
            syms_per_window.append(sym)
            win_prices.append(float(prices[i]))
    syms_per_window = np.array(syms_per_window)
    win_prices = np.array(win_prices)
    print(f"  windows={len(X)}  syms_mapped={len(syms_per_window)}")
    if len(X) != len(syms_per_window):
        print("  ! length mismatch — abort")
        return 1

    print(f"\n{'tier':<11} {'symbols':>8} {'windows':>8} {'mean_IC':>8} {'IR':>7} "
          f"{'mean_WFE':>9} {'last_WFE':>9} {'xs_std':>6} {'friction':>9} "
          f"{'EV/trade':>9} {'net/yr/$10k':>12}")
    print("-" * 130)
    for label, lo, hi in TIER_BOUNDS:
        in_tier = (win_prices >= lo) & (win_prices < hi)
        n_sym = ((median_price >= lo) & (median_price < hi)).sum()
        n_win = int(in_tier.sum())
        if n_win < 200:
            print(f"{label:<11} {n_sym:>8} {n_win:>8}  (too few windows)")
            continue
        Xs = X[in_tier]
        ys = y[in_tier]
        ts = t[in_tier]
        sigma_xs = float(np.std(ys))   # std of 5d returns in this tier
        r = fit_and_score(Xs, ys, ts)
        last_wfe_str = f"{r['last_wfe']:+.4f}" if r['last_wfe'] is not None else "  nan"

        # Cash-flow translation (5d horizon, $10k portfolio, 5 names, 50 trades/yr)
        ic = r["mean_ic"]
        if not np.isnan(ic):
            ev_per_trade = ic * sigma_xs * 0.7   # |z_typical| ≈ 0.7
            friction = ROUND_TRIP_FRICTION_PCT[label]
            net_per_trade = ev_per_trade - friction
            net_per_year = net_per_trade * 50 * 5 * 2_000   # 50 trades * 5 names * $2k
            net_str = f"${net_per_year:>+9.0f}"
            ev_str = f"{ev_per_trade*100:>+6.2f}%"
            fric_str = f"{friction*100:>5.2f}%"
        else:
            net_str = "n/a"
            ev_str = "n/a"
            fric_str = "n/a"

        print(f"{label:<11} {n_sym:>8} {n_win:>8} {r['mean_ic']:>+8.4f} "
              f"{r['ir']:>+7.2f} {r['mean_wfe']:>+9.4f} {last_wfe_str:>9} "
              f"{sigma_xs*100:>5.2f}% {fric_str:>9} {ev_str:>9} {net_str:>12}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
