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


if __name__ == "__main__":
    unittest.main()
