"""
XGBoost feature-set ablation experiment.

Compares the current 14-channel flat feature set against augmented variants
informed by docs/equity_feature_engineering.md. Uses signal_history's
existing parquets so no new data fetches needed.

Output: per-variant (mean_ic, ir, mean_wfe) on the same walk-forward folds.

Usage from project root:
    PYTHONPATH=site-packages:backend runtime/python/python.exe scripts/xgb_feature_experiment.py
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

# Add backend/ to import path so we can reuse cnn_evaluation primitives
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(os.path.dirname(_HERE), "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from data.cnn_evaluation import compute_ic, compute_ir, walkforward_folds
from data.cnn_model import _compute_wfe


# ── Data loading ──────────────────────────────────────────────────────────

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


# ── Feature builders ──────────────────────────────────────────────────────

def _per_symbol_returns(df: pd.DataFrame, periods: List[int]) -> pd.DataFrame:
    """For each (symbol), compute log return over `n` rows back for each n in periods.
    NB: rows are per-cycle snapshots (~hourly during market), not strictly daily,
    so 'n rows' is an approximation of n cycles, not n calendar days."""
    out = df.copy()
    for n in periods:
        col = f"r_{n}"
        out[col] = (
            out.groupby("symbol")["price"]
              .transform(lambda s: np.log(s / s.shift(n)))
        )
    return out


def _vol_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    # Use existing rv_20d / rv_60d. Add ratio + diff.
    out["vol_ratio_20_60"] = (out["rv_20d"] / out["rv_60d"]).replace([np.inf, -np.inf], np.nan)
    out["vol_diff_20_60"]  = out["rv_20d"] - out["rv_60d"]
    return out


def _cross_sectional_ranks(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    """Rank `cols` within each snapshot_ts bucket across symbols.
    Bucket by hour to allow snapshots within the same trading hour to share a peer set."""
    out = df.copy()
    # Round snapshot_ts to nearest hour for cross-sectional grouping
    out["_xs_bucket"] = (out["snapshot_ts"] // 3600).astype(np.int64)
    for col in cols:
        if col not in out.columns:
            continue
        rank_col = f"{col}_xs_rank"
        out[rank_col] = (
            out.groupby("_xs_bucket")[col]
               .transform(lambda s: s.rank(pct=True))
        )
    out = out.drop(columns=["_xs_bucket"])
    return out


def _calendar_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    ts = pd.to_datetime(out["snapshot_ts"], unit="s")
    out["dow"] = ts.dt.dayofweek.astype(np.float32)   # 0..6
    out["dom"] = ts.dt.day.astype(np.float32)          # 1..31
    out["mom"] = ts.dt.month.astype(np.float32)        # 1..12
    return out


def _calmar_momentum(df: pd.DataFrame) -> pd.DataFrame:
    """12-1 month momentum approximation: r_120 - r_20 (lookback - skip-month).
    With ~6mo of data per symbol this is the longest skip-window we can compute."""
    out = df.copy()
    if "r_120" in out.columns and "r_20" in out.columns:
        out["mom_120_20"] = out["r_120"] - out["r_20"]
    return out


# ── Feature-set assembly ──────────────────────────────────────────────────

BASE_COLS = [
    # Sources (5)
    "analyst_score", "earnings_score", "alpaca_score", "yahoo_score", "iv_rv_score",
    # Agent (2)
    "agent_consensus", "agent_agreement",
    # RV (2)
    "rv_20d", "rv_60d",
]


def assemble_variants(df_full: pd.DataFrame) -> Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Return {variant_name: (X, y, t)} for each feature set."""
    # Compute return features once (used by several variants)
    df = _per_symbol_returns(df_full, periods=[1, 5, 20, 60, 120])
    df = _vol_features(df)
    df = _calendar_features(df)
    df = _calmar_momentum(df)
    df = _cross_sectional_ranks(
        df,
        cols=["composite_score", "rv_20d", "analyst_score", "yahoo_score"],
    )
    # Earnings_score -> magnitude (matches the CNN's _apply_cnn_feature_transforms).
    # Coerce object-dtype Nones to NaN first.
    df["earnings_score"] = pd.to_numeric(df["earnings_score"], errors="coerce")
    df["earnings_mag"] = df["earnings_score"].abs()
    # Drop rows where label is NaN
    df = df.dropna(subset=["return_5d"]).reset_index(drop=True)
    # Clip target ±20% (matches build_training_windows)
    y_full = np.clip(df["return_5d"].values.astype(np.float32), -0.20, 0.20)
    t_full = df["snapshot_ts"].values.astype(np.float64)

    def take(cols: List[str]) -> np.ndarray:
        # Fill NaN with 0 (matches np.nan_to_num in build_training_windows)
        sub = df[cols].copy()
        sub = sub.replace([np.inf, -np.inf], np.nan).fillna(0.0)
        return sub.values.astype(np.float32)

    variants: Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray]] = {}

    # Variant A — baseline: current 9 per-row features (no temporal flatten —
    # we test the simpler tabular form, which is what the CNN→XGBoost flatten
    # collapses to anyway when window=1)
    base = BASE_COLS + ["earnings_mag"]
    variants["A_baseline"] = (take(base), y_full, t_full)

    # Variant B — + multi-horizon returns
    b_cols = base + ["r_1", "r_5", "r_20", "r_60", "r_120"]
    variants["B_plus_returns"] = (take(b_cols), y_full, t_full)

    # Variant C — + momentum (skip-1 style) + vol asymmetry
    c_cols = b_cols + ["mom_120_20", "vol_ratio_20_60", "vol_diff_20_60"]
    variants["C_plus_momentum_vol"] = (take(c_cols), y_full, t_full)

    # Variant D — + cross-sectional ranks
    d_cols = c_cols + [
        "composite_score_xs_rank", "rv_20d_xs_rank",
        "analyst_score_xs_rank", "yahoo_score_xs_rank",
    ]
    variants["D_plus_cross_section"] = (take(d_cols), y_full, t_full)

    # Variant E — + calendar
    e_cols = d_cols + ["dow", "dom", "mom"]
    variants["E_plus_calendar"] = (take(e_cols), y_full, t_full)

    return variants


# ── Walk-forward XGBoost driver ───────────────────────────────────────────

def run_xgb_walkforward(
    X: np.ndarray,
    y: np.ndarray,
    t: np.ndarray,
    n_folds: int = 3,
    min_val_days: int = 14,
    embargo_bars: int = 1,
) -> Dict[str, float]:
    folds = walkforward_folds(t, n_folds=n_folds, min_val_days=min_val_days, embargo_bars=embargo_bars)
    if not folds:
        return {"folds": 0, "mean_ic": float("nan"), "ir": float("nan"), "mean_wfe": float("nan")}

    params = {
        "max_depth":        6,
        "eta":              0.05,
        "subsample":        0.8,
        "colsample_bytree": 0.8,
        "alpha":            0.1,
        "lambda":           1.0,
        "objective":        "reg:squarederror",
        "eval_metric":      "rmse",
        "tree_method":      "hist",
        "seed":             42,
        "verbosity":        0,
    }
    ics: List[float] = []
    wfes: List[float] = []
    val_mses: List[float] = []
    for tr_idx, va_idx in folds:
        dtrain = xgb.DMatrix(X[tr_idx], label=y[tr_idx])
        dval   = xgb.DMatrix(X[va_idx], label=y[va_idx])
        booster = xgb.train(
            params, dtrain, num_boost_round=500,
            evals=[(dval, "val")],
            early_stopping_rounds=30,
            verbose_eval=False,
        )
        vp = booster.predict(dval).astype(np.float32)
        vt = y[va_idx].astype(np.float32)
        ics.append(compute_ic(vp, vt))
        wfe_val, _ = _compute_wfe(vt.tolist(), vp.tolist())
        if wfe_val is not None:
            wfes.append(wfe_val)
        val_mses.append(float(np.mean((vp - vt) ** 2)))

    return {
        "folds":    len(folds),
        "n_features": X.shape[1],
        "mean_ic":  float(np.mean(ics)) if ics else float("nan"),
        "ir":       compute_ir(ics),
        "mean_wfe": float(np.mean(wfes)) if wfes else float("nan"),
        "mean_val_mse": float(np.mean(val_mses)) if val_mses else float("nan"),
    }


# ── Entry ─────────────────────────────────────────────────────────────────

def main() -> int:
    print("Loading per-symbol parquets...")
    df = load_all_history()
    print(f"  total rows: {len(df):,} across {df['symbol'].nunique()} symbols")
    print(f"  date range: {pd.Timestamp(df.snapshot_ts.min(), unit='s')} -> {pd.Timestamp(df.snapshot_ts.max(), unit='s')}")

    print("\nAssembling variants...")
    t0 = time.perf_counter()
    variants = assemble_variants(df)
    print(f"  built {len(variants)} variants in {time.perf_counter()-t0:.1f}s")

    print(f"\n{'variant':<28} {'#feat':>6} {'folds':>6} {'mean_IC':>10} {'IR':>8} {'mean_WFE':>10} {'val_MSE':>12}")
    print("-" * 100)
    results: Dict[str, Dict] = {}
    for name, (X, y, t) in variants.items():
        t0 = time.perf_counter()
        r = run_xgb_walkforward(X, y, t)
        elapsed = time.perf_counter() - t0
        print(f"{name:<28} {r.get('n_features',0):>6} {r['folds']:>6} "
              f"{r['mean_ic']:>+10.4f} {r['ir']:>+8.2f} {r['mean_wfe']:>+10.4f} "
              f"{r['mean_val_mse']:>12.6f}  ({elapsed:.1f}s)")
        results[name] = r

    # Pick winner
    valid = {k: v for k, v in results.items() if not np.isnan(v["mean_ic"])}
    if valid:
        winner = max(valid.items(), key=lambda kv: kv[1]["mean_ic"])
        print(f"\nWinner by mean_IC: {winner[0]}  (mean_IC={winner[1]['mean_ic']:+.4f}, "
              f"IR={winner[1]['ir']:+.2f}, mean_WFE={winner[1]['mean_wfe']:+.4f})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
