"""CLI - Monte Carlo backtest comparing candidate XGB filter variants.

Usage from project root:
    PYTHONPATH='site-packages;backend' runtime/python/python.exe \\
      scripts/mc_backtest_filters.py \\
      --variants "current=analyst_score,earnings_score,alpaca_score,iv_rv_score,r_120,macro_vix_norm,macro_spy_5d_back,macro_breadth_back" \\
                 "swap_both=analyst_score,earnings_score,alpaca_score,iv_rv_score,r_120,macro_vix_norm,macro_spy_10d_back,macro_breadth_10d_back" \\
      --n-paths 1000 --path-days 252 --block-size 10 --seed 42

Outputs:
    scripts/logs/mc_backtest_<timestamp>.md      (Markdown table)
    scripts/logs/mc_backtest_<timestamp>.jsonl   (raw per-(variant,sim) outcomes)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime

import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(os.path.dirname(_HERE), "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

os.environ.setdefault("MODEL_BACKEND", "xgboost")

from data.signal_history import signal_history
from data.cnn_model import build_training_windows, ALL_CHANNEL_COLUMNS
from data.xgboost_model import SignalXGBoost
from data.mc_backtester import (
    BootstrapConfig, FilterVariant, run_variant_comparison,
    render_markdown, write_jsonl,
)


def _parse_variant_arg(spec: str) -> tuple[str, list[str]]:
    """'name=ch1,ch2,...' -> ('name', ['ch1', 'ch2', ...])"""
    if "=" not in spec:
        raise ValueError(f"variant must be 'name=ch1,ch2,...' - got: {spec}")
    name, channels = spec.split("=", 1)
    return name.strip(), [c.strip() for c in channels.split(",") if c.strip()]


def _train_variant(name: str, channel_names: list[str]) -> SignalXGBoost:
    """Train one fresh SignalXGBoost with the given feature filter."""
    print(f"\n  -- training variant '{name}' ({len(channel_names)} channels)...")
    # Temporarily set the env so SignalXGBoost picks up the filter at init
    os.environ["XGB_FEATURE_FILTER"] = ",".join(channel_names)
    model = SignalXGBoost()
    df = signal_history.get_training_data()
    X, y, w, t = build_training_windows(df)
    t0 = time.time()
    model.fit(X, y, t, sample_weights=w)
    print(f"  -- '{name}' fit in {time.time()-t0:.1f}s  mean_IC={model.training_summary()['mean_ic']:+.4f}")
    return model


async def _main_async(args: argparse.Namespace) -> int:
    print("Loading historical data once (shared across variants)...")
    historical = signal_history.get_training_data()
    print(f"  rows={len(historical):,}  symbols={historical['symbol'].nunique() if len(historical) else 0}")

    # Train one model per variant
    variants: list[FilterVariant] = []
    for spec in args.variants:
        name, channels = _parse_variant_arg(spec)
        model = _train_variant(name, channels)
        variants.append(FilterVariant(name=name, model=model))

    # Run the comparison
    print(f"\n  -- simulating: {args.n_paths} paths x {args.path_days} days x {len(variants)} variants...")
    cfg = BootstrapConfig(
        expected_block_size=args.block_size,
        n_paths=args.n_paths,
        path_length_days=args.path_days,
        seed=args.seed,
    )
    # Simulator needs MultiIndex (date, symbol) — signal_history uses snapshot_ts
    # so rename to match the sampler's hardcoded "date" level name.
    if not isinstance(historical.index, pd.MultiIndex):
        if "snapshot_ts" in historical.columns and "date" not in historical.columns:
            historical = historical.rename(columns={"snapshot_ts": "date"})
        historical = historical.set_index(["date", "symbol"])
    # Filter to ONLY the model's channel columns + price.
    # SignalXGBoost.predict has a shape-guard: x.shape[0] must equal _n_channels.
    # If we leave extra metadata columns (return_5d, snapshot_ts numeric, etc.) in
    # the path, replay_one_path's window will be the wrong shape and predict()
    # silently returns (0.0, "neutral", 0.0) → zero trades, zero metrics.
    keep_cols = [c for c in ALL_CHANNEL_COLUMNS if c in historical.columns]
    if "price" in historical.columns and "price" not in keep_cols:
        keep_cols.append("price")
    print(f"  Filtered historical to {len(keep_cols)} columns "
          f"({len(ALL_CHANNEL_COLUMNS)} model channels + 'price')")
    historical = historical[keep_cols]
    report, outcomes = await run_variant_comparison(variants, historical, cfg)

    # Write outputs
    os.makedirs(os.path.join(_HERE, "logs"), exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = os.path.join(_HERE, "logs", f"mc_backtest_{ts}.md")
    jsonl_path = os.path.join(_HERE, "logs", f"mc_backtest_{ts}.jsonl")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(report))
    write_jsonl(outcomes, jsonl_path)

    print(f"\nReport written:")
    print(f"  Markdown: {md_path}")
    print(f"  JSONL:    {jsonl_path}")
    print()
    print(render_markdown(report))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variants", nargs="+", required=True,
                        help="One or more 'name=ch1,ch2,...' specs")
    parser.add_argument("--n-paths", type=int, default=1000)
    parser.add_argument("--path-days", type=int, default=252)
    parser.add_argument("--block-size", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    sys.exit(main())
