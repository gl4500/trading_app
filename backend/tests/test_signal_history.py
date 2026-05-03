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


if __name__ == "__main__":
    unittest.main()
