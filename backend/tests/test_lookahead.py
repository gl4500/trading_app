"""Lookahead-leak regression test for the feature pipeline.

For every feature column, the value at row t must NOT depend on data with
snapshot_ts > t. This is the single most important pipeline test per
docs/feature_engineering_pipeline.md Stage 4.

Method: synthesize a multi-symbol df, run each transform on the FULL df
and on the TRUNCATED df (`df[df.snapshot_ts <= t]`), then assert the row
at t produces identical values either way.

Catches:
- Forward-looking joins (the macro 5d-forward bug, Task #24, that flipped
  val WFE from -0.034 to -0.346 in production)
- Centered rolling windows that peek ahead
- Per-symbol grouped transforms that accidentally use future rows
- Cross-symbol joins that resolve to a future timestamp

Does NOT cover (these are intentionally forward-looking labels, not features):
  - return_1d, return_5d, return_10d
"""
from __future__ import annotations

import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# Channels we expect to be backward-looking (must satisfy lookahead-freedom).
# Excludes the 3 forward-return labels (return_1d/5d/10d).
LOOKAHEAD_FREE_CHANNELS = [
    # Source — snapshot values at time t
    "analyst_score", "earnings_score", "alpaca_score", "yahoo_score", "iv_rv_score",
    # Agent — snapshot values at time t
    "agent_consensus", "agent_agreement",
    # Realized vol — computed at write time from past prices
    "rv_20d", "rv_60d",
    # Lagged returns (hourly grid) — explicitly backward
    "r_1", "r_5", "r_20", "r_60", "r_120",
    # Macro — joined as-of, must use trailing values only
    "macro_vix_norm", "macro_gld_5d_back", "macro_tlt_5d_back",
    "macro_spy_5d_back", "macro_breadth_back",
    # Sprint 0: daily-resampled lagged returns — backward shift on
    # per-symbol, per-trading-day series, then forward-filled to hourly rows
    "r_1d", "r_5d", "r_20d", "r_60d", "r_120d", "r_252d",
    # Sprint 2-B: derived momentum (mom_12_1 = r_252d - r_20d) — pure
    # subtraction of two lookahead-free channels = lookahead-free.
    "mom_12_1",
]


def _make_multi_symbol_df(n_per_sym: int = 150, seed: int = 0) -> pd.DataFrame:
    """Build a synthetic 2-symbol df with all 19 raw channel columns plus
    the prerequisites for compute_return_features and attach_macro_features.
    Timestamps are spread over real calendar days so macro merge_asof has
    a defined join basis if __MACRO__.parquet exists, and degrades to
    zero-fills if it doesn't."""
    rng = np.random.default_rng(seed)
    rows = []
    base_ts = 1_704_067_200.0   # 2024-01-01 00:00 UTC
    for sym_i, sym in enumerate(("AAPL", "MSFT")):
        prices = 100.0 + np.cumsum(rng.standard_normal(n_per_sym) * 0.5)
        rows.append(pd.DataFrame({
            "symbol":          [sym] * n_per_sym,
            "snapshot_ts":     base_ts + np.arange(n_per_sym, dtype=np.float64) * 86_400.0,
            "price":           prices,
            "analyst_score":   rng.standard_normal(n_per_sym) * 0.1,
            "earnings_score":  rng.standard_normal(n_per_sym) * 0.1,
            "alpaca_score":    rng.standard_normal(n_per_sym) * 0.1,
            "yahoo_score":     rng.standard_normal(n_per_sym) * 0.1,
            "iv_rv_score":     rng.standard_normal(n_per_sym) * 0.1,
            "agent_consensus": rng.standard_normal(n_per_sym) * 0.5,
            "agent_agreement": np.abs(rng.standard_normal(n_per_sym)),
            "rv_20d":          0.20 + np.abs(rng.standard_normal(n_per_sym)) * 0.05,
            "rv_60d":          0.20 + np.abs(rng.standard_normal(n_per_sym)) * 0.05,
            "return_1d":       np.full(n_per_sym, 0.001),
            "return_5d":       np.full(n_per_sym, 0.005),
            "return_10d":      np.full(n_per_sym, 0.010),
        }))
    return pd.concat(rows, ignore_index=True)


def _full_pipeline(df: pd.DataFrame) -> pd.DataFrame:
    """Run the canonical transform stack, return df with all 25 channels
    populated (Sprint 0 added the 6 daily-resampled returns)."""
    from data.signal_history import (
        _apply_cnn_feature_transforms, _compute_return_features,
        _attach_macro_features, _compute_daily_return_features,
    )
    out = _apply_cnn_feature_transforms(df)
    out = _compute_return_features(out)
    out = _attach_macro_features(out)
    out = _compute_daily_return_features(out)
    return out


class TestLookaheadFreedom(unittest.TestCase):
    """Every feature at row t must equal itself when computed on
    df[df.snapshot_ts <= t]. If equality breaks for ANY channel, the
    pipeline is leaking future information into training."""

    @classmethod
    def setUpClass(cls):
        cls.df = _make_multi_symbol_df(n_per_sym=150, seed=42)

    def _lookup(self, df: pd.DataFrame, sym: str, ts: float, col: str):
        """Find the row matching (symbol, snapshot_ts) and return its value
        in `col`. _attach_macro_features re-sorts the df, so positional
        indices change — always look up by (symbol, ts) which are stable."""
        mask = (df["symbol"] == sym) & (df["snapshot_ts"] == ts)
        if not mask.any():
            return None
        return df.loc[mask, col].iloc[0]

    def _check_channel_no_leak(self, channel: str, sample_keys: list):
        """For each (symbol, ts) key, compute the channel value two ways and
        assert equality. sample_keys is a list of (symbol, snapshot_ts) tuples."""
        df_full = _full_pipeline(self.df)
        if channel not in df_full.columns:
            self.skipTest(f"{channel} not present in pipeline output (likely "
                          "macro file absent — degrades to zero-fill, lookahead-safe by definition)")
            return

        for sym, ts in sample_keys:
            v_full = self._lookup(df_full, sym, ts, channel)
            self.assertIsNotNone(v_full, f"target row missing in full df for {channel}")

            truncated  = self.df[self.df["snapshot_ts"] <= ts].copy()
            trunc_full = _full_pipeline(truncated)
            v_trunc    = self._lookup(trunc_full, sym, ts, channel)
            self.assertIsNotNone(v_trunc,
                f"target row missing in truncated df for {channel} "
                f"(sym={sym}, ts={ts})")

            # Allow NaN==NaN; otherwise exact equality (deterministic transforms).
            if pd.isna(v_full) and pd.isna(v_trunc):
                continue
            self.assertEqual(
                v_full, v_trunc,
                f"LOOKAHEAD LEAK in '{channel}' at (sym={sym}, ts={ts}): "
                f"full-df value {v_full!r} ≠ truncated-df value {v_trunc!r}",
            )

    def test_no_lookahead_in_any_channel(self):
        """One subtest per channel — easy failure isolation."""
        # Sample timestamps deep enough into each symbol that r_120 has
        # meaningful history AND shallow enough that data after t exists
        # to make the truncation actually drop rows.
        sample_keys = []
        for sym in ("AAPL", "MSFT"):
            sym_rows = self.df[self.df["symbol"] == sym]
            for pos in (130, 145):
                sample_keys.append((sym, float(sym_rows.iloc[pos]["snapshot_ts"])))
        for channel in LOOKAHEAD_FREE_CHANNELS:
            with self.subTest(channel=channel):
                self._check_channel_no_leak(channel, sample_keys)

    def test_label_columns_are_excluded_from_features(self):
        """Forward-return labels (return_1d/5d/10d) MAY differ when truncated —
        that's their job. Pin this so a future refactor doesn't accidentally
        promote them into the feature set."""
        from data.cnn_model import ALL_CHANNEL_COLUMNS
        for label_col in ("return_1d", "return_5d", "return_10d"):
            self.assertNotIn(
                label_col, ALL_CHANNEL_COLUMNS,
                f"{label_col} is a forward label and must NEVER appear in "
                f"ALL_CHANNEL_COLUMNS (would inject lookahead at training time)",
            )


if __name__ == "__main__":
    unittest.main()
