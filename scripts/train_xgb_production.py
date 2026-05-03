"""
One-shot production XGBoost training run.

Mirrors agents/cnn_reasoning_agent._train_blocking but runs synchronously
without the cross-app GPU mutex (XGBoost is CPU-only, no GPU contention).

Usage from project root:
    set MODEL_BACKEND=xgboost
    PYTHONPATH='site-packages;backend' runtime/python/python.exe scripts/train_xgb_production.py
"""
from __future__ import annotations

import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(os.path.dirname(_HERE), "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

# Force xgboost backend before any signal_model import resolves the selector
os.environ["MODEL_BACKEND"] = "xgboost"


def main() -> int:
    from data.signal_history import signal_history
    from data.cnn_model import build_training_windows
    from data.signal_model import signal_model
    from config import config

    print(f"MODEL_BACKEND        = {config.MODEL_BACKEND}")
    print(f"signal_model class   = {type(signal_model).__name__}")

    print("\nLoading training data...")
    t0 = time.perf_counter()
    df = signal_history.get_training_data()
    print(f"  rows={len(df):,}  symbols={df['symbol'].nunique() if len(df) else 0}  "
          f"({time.perf_counter()-t0:.1f}s)")
    if df.empty or len(df) < 100:
        print(f"  ! too few rows ({len(df)}) — aborting")
        return 1

    print("\nBuilding training windows...")
    t0 = time.perf_counter()
    X, y, w, t = build_training_windows(df)
    print(f"  X.shape={X.shape}  y.shape={y.shape}  ({time.perf_counter()-t0:.1f}s)")
    if len(X) < 100:
        print(f"  ! too few windows ({len(X)}) — aborting")
        return 1

    print("\nFitting SignalXGBoost (walk-forward 3-fold CV)...")
    t0 = time.perf_counter()
    signal_model.fit(X, y, t, sample_weights=w)
    print(f"  fit complete in {time.perf_counter()-t0:.1f}s")

    print("\nSaving model + sidecar metadata...")
    signal_model.save()

    summary = signal_model.training_summary()
    print("\n=== Training summary ===")
    print(f"  trained          : {summary['trained']}")
    print(f"  n_channels       : {summary['n_channels']}")
    print(f"  n_train (last)   : {summary['n_train']}")
    print(f"  n_val   (last)   : {summary['n_val']}")
    print(f"  mean_IC          : {summary['mean_ic']:+.4f}")
    print(f"  IR               : {summary['ir']:+.2f}")
    print(f"  mean_WFE         : {summary['mean_wfe']}")
    print(f"  last fold WFE    : {summary['walk_forward_efficiency']} [{summary['wfe_status']}]")
    print(f"  final_train_mse  : {summary['final_train_mse']:.6f}")
    print(f"  final_val_mse    : {summary['final_val_mse']:.6f}")
    print(f"\n  per-fold:")
    for fm in summary["fold_metrics"]:
        print(f"    fold {fm['fold']}: n_train={fm['n_train']} n_val={fm['n_val']} "
              f"IC={fm['ic']:+.4f} WFE={fm['wfe']} val_MSE={fm['val_mse']:.6f}")

    print(f"\n  learned weights:")
    for k, v in summary["learned_weights"].items():
        print(f"    {k:<20} {v:.4f}")

    # Inspect the on-disk sidecar
    meta_path = os.path.join(_BACKEND, "data", "models", "signal_xgb.json.meta.json")
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        print(f"\n=== Sidecar at {os.path.relpath(meta_path)} ===")
        for k in ("trained", "n_channels", "T", "mean_ic", "ir", "mean_wfe", "wfe_status"):
            print(f"  {k:<14} {meta.get(k)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
