"""Tests for data/signal_history.py — return feature augmentation."""
import unittest

import numpy as np


class TestComputeReturnFeatures(unittest.TestCase):
    """Lagged log-return feature builder — Tier 1 from
    docs/equity_feature_engineering_audit.md."""

    def _make_df(self, prices, symbol="AAPL"):
        import pandas as pd
        return pd.DataFrame({
            "symbol":      [symbol] * len(prices),
            "snapshot_ts": np.arange(len(prices), dtype=np.float64) * 86400.0,
            "price":       np.asarray(prices, dtype=np.float64),
        })

    def test_adds_five_return_columns(self):
        from data.signal_history import _compute_return_features, RETURN_COLUMNS
        df = self._make_df([100.0] * 200)  # flat prices
        out = _compute_return_features(df)
        for col in RETURN_COLUMNS:
            self.assertIn(col, out.columns)

    def test_log_return_math_correct(self):
        """r_5 at row N = log(price[N] / price[N-5])."""
        from data.signal_history import _compute_return_features
        prices = np.linspace(100.0, 200.0, 200)
        df = self._make_df(prices)
        out = _compute_return_features(df)
        # Pick row 50 — five rows back is row 45
        expected = float(np.log(prices[50] / prices[45]))
        self.assertAlmostEqual(float(out["r_5"].iloc[50]), expected, places=6)

    def test_first_n_rows_have_nan(self):
        """For r_5, the first 5 rows can't compute a 5-row lookback."""
        from data.signal_history import _compute_return_features
        prices = np.linspace(100.0, 200.0, 200)
        df = self._make_df(prices)
        out = _compute_return_features(df)
        self.assertTrue(out["r_5"].iloc[:5].isna().all())
        self.assertFalse(out["r_5"].iloc[5:].isna().any())

    def test_per_symbol_isolation(self):
        """Returns for AAPL must not leak into MSFT and vice versa."""
        from data.signal_history import _compute_return_features
        import pandas as pd
        df = pd.concat([
            self._make_df(np.linspace(100, 200, 100), symbol="AAPL"),
            self._make_df(np.linspace(300, 400, 100), symbol="MSFT"),
        ], ignore_index=True)
        out = _compute_return_features(df)
        # MSFT row 0 must be NaN for r_1 — there's no prior MSFT row, even though
        # the AAPL block above it has prices.
        msft = out[out["symbol"] == "MSFT"].reset_index(drop=True)
        self.assertTrue(np.isnan(msft["r_1"].iloc[0]))

    def test_returns_copy_not_inplace(self):
        """The helper must not mutate the caller's df."""
        from data.signal_history import _compute_return_features, RETURN_COLUMNS
        df = self._make_df([100.0] * 50)
        before_cols = set(df.columns)
        _compute_return_features(df)
        self.assertEqual(set(df.columns), before_cols,
                         "caller's df must keep its original columns")

    def test_handles_zero_or_negative_prices_safely(self):
        """log(price/0) is undefined — must not crash."""
        from data.signal_history import _compute_return_features
        df = self._make_df([100.0, 110.0, 0.0, 120.0, 130.0, 140.0, 150.0])
        out = _compute_return_features(df)
        # No exception raised. Resulting NaN/inf is fine — downstream zero-fills.
        self.assertEqual(len(out), 7)


class TestGetTrainingDataIncludesReturns(unittest.TestCase):
    """get_training_data must yield the 5 lagged-return columns alongside
    the existing source/agent/rv/macro columns."""

    def test_returns_columns_present(self):
        from data.signal_history import (
            signal_history, RETURN_COLUMNS,
        )
        from unittest.mock import patch
        import pandas as pd

        # Synthesise a small per-symbol df with enough rows for r_5
        rows = 50
        synthetic = pd.DataFrame({
            "symbol":          ["AAPL"] * rows,
            "snapshot_ts":     np.arange(rows, dtype=np.float64) * 86400.0,
            "analyst_score":   np.zeros(rows),
            "earnings_score":  np.zeros(rows),
            "alpaca_score":    np.zeros(rows),
            "yahoo_score":     np.zeros(rows),
            "iv_rv_score":     np.zeros(rows),
            "price":           np.linspace(100, 150, rows),
            "return_1d":       np.full(rows, 0.001),
            "return_5d":       np.full(rows, 0.005),
        })

        # Patch symbols_with_data + _load to return our synthetic frame
        with patch.object(signal_history, "symbols_with_data",
                          return_value=["AAPL"]), \
             patch("data.signal_history._load", return_value=synthetic):
            df = signal_history.get_training_data()

        for col in RETURN_COLUMNS:
            self.assertIn(col, df.columns,
                          f"get_training_data must include {col}")


class TestGetRecentWindowReturns19Channels(unittest.TestCase):
    """get_recent_window must return a (19, T) array matching training shape:
    5 source + 2 agent + 2 rv + 5 returns + 5 macro."""

    def test_recent_window_has_19_rows(self):
        from data.signal_history import signal_history
        from unittest.mock import patch
        import pandas as pd

        # Need at least T+max_lag=10+120=130 rows for full r_120 coverage,
        # but the helper handles partial coverage with NaN→0 fill.
        rows = 130
        synthetic = pd.DataFrame({
            "symbol":          ["AAPL"] * rows,
            "snapshot_ts":     np.arange(rows, dtype=np.float64) * 86400.0,
            "analyst_score":   np.zeros(rows),
            "earnings_score":  np.zeros(rows),
            "alpaca_score":    np.zeros(rows),
            "yahoo_score":     np.zeros(rows),
            "iv_rv_score":     np.zeros(rows),
            "agent_consensus": np.zeros(rows),
            "agent_agreement": np.zeros(rows),
            "rv_20d":          np.full(rows, 0.20),
            "rv_60d":          np.full(rows, 0.20),
            "price":           np.linspace(100, 150, rows),
            "return_1d":       np.full(rows, 0.001),
            "return_5d":       np.full(rows, 0.005),
        })
        with patch("data.signal_history._load", return_value=synthetic):
            window = signal_history.get_recent_window("AAPL", T=10)

        self.assertIsNotNone(window, "window must not be None for 130-row symbol")
        self.assertEqual(window.shape, (19, 10),
                         f"expected (19, 10), got {window.shape}")


class TestReturn10dSchema(unittest.IsolatedAsyncioTestCase):
    """return_10d as a first-class outcome alongside return_1d and return_5d.
    Required for the 10d label-horizon switch (XGBoost ablation showed
    10d 8-channel produces mean_IC=+0.40, last_WFE=+0.25 vs 5d's +0.21/+0.07)."""

    def test_return_10d_in_dtype_map(self):
        """The persistence schema must declare return_10d so existing
        parquets pick up the column on next write/read."""
        from data.signal_history import _DTYPE_MAP
        self.assertIn("return_10d", _DTYPE_MAP,
                      "_DTYPE_MAP must declare return_10d alongside return_1d/return_5d")
        self.assertEqual(_DTYPE_MAP["return_10d"], "float64")

    async def test_record_snapshot_writes_return_10d_nan(self):
        """A freshly recorded snapshot has return_10d=NaN — we don't know
        the future yet."""
        import tempfile, os, pandas as pd
        from unittest.mock import patch
        from data.signal_history import SignalHistoryStore

        with tempfile.TemporaryDirectory() as td:
            with patch("data.signal_history._HISTORY_DIR", td):
                store = SignalHistoryStore()
                await store.record_snapshot(
                    symbol="AAPL",
                    scores={"analyst_recommendations": 0.5},
                    composite_score=0.3,
                    price=100.0,
                    rv_20d=0.20,
                    rv_60d=0.25,
                )
                df = pd.read_parquet(os.path.join(td, "AAPL.parquet"))
                self.assertIn("return_10d", df.columns,
                              "record_snapshot must persist return_10d column")
                self.assertTrue(pd.isna(df["return_10d"].iloc[0]),
                                "return_10d must be NaN at write time")

    async def test_update_outcomes_fills_return_10d_after_10_days(self):
        """update_outcomes must populate return_10d for any snapshot
        whose 10-day window has elapsed."""
        import tempfile, os, time, pandas as pd
        from unittest.mock import patch
        from data.signal_history import SignalHistoryStore, _DTYPE_MAP

        with tempfile.TemporaryDirectory() as td:
            with patch("data.signal_history._HISTORY_DIR", td):
                # Build a parquet with one snapshot 11 days old; price=100.
                # Return columns intentionally start NaN.
                eleven_days_ago = time.time() - 11 * 86_400
                # Use full _DTYPE_MAP columns so the round-trip preserves dtypes
                row = {col: pd.NA for col in _DTYPE_MAP}
                row.update({
                    "symbol":     "AAPL",
                    "snapshot_ts": eleven_days_ago,
                    "price":      100.0,
                })
                df = pd.DataFrame([row])
                df.to_parquet(os.path.join(td, "AAPL.parquet"), index=False)

                store = SignalHistoryStore()
                # Current price is 110 → 10% return
                updated = await store.update_outcomes(symbol="AAPL", current_price=110.0)
                self.assertGreater(updated, 0)

                df_after = pd.read_parquet(os.path.join(td, "AAPL.parquet"))
                self.assertIn("return_10d", df_after.columns)
                self.assertAlmostEqual(
                    float(df_after["return_10d"].iloc[0]), 0.10, places=4,
                    msg="11-day-old snapshot should have return_10d ≈ +10%",
                )


if __name__ == "__main__":
    unittest.main()
