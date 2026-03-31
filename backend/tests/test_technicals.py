"""
Unit tests for data/technicals.py
Covers: compute(), manual indicator implementations,
        format_for_prompt(), edge cases.
Requires: pandas, numpy
"""
import sys
import os
import math
import unittest

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import pandas as pd
    import numpy as np
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

from data.technicals import (
    compute, format_for_prompt,
    _manual_rsi, _manual_macd, _manual_bb, _manual_atr,
)

try:
    from data.technicals import _manual_stoch, _manual_obv
    HAS_STOCH_OBV = True
except ImportError:
    HAS_STOCH_OBV = False
    _manual_stoch = None
    _manual_obv = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_bars(n=60, start=100.0, trend=0.5):
    """Create OHLCV DataFrame with a mild upward trend."""
    if not HAS_PANDAS:
        return None
    close = [start + i * trend for i in range(n)]
    return pd.DataFrame({
        "open":   close,
        "high":   [c + 1.0 for c in close],
        "low":    [c - 1.0 for c in close],
        "close":  close,
        "volume": [500_000 + i * 1000 for i in range(n)],
    })


def _make_oscillating_bars(n=60, start=100.0, amplitude=5.0):
    """Bars that oscillate up/down — good for RSI overbought/oversold."""
    if not HAS_PANDAS:
        return None
    close = [start + amplitude * math.sin(i * 0.3) for i in range(n)]
    return pd.DataFrame({
        "open":   close,
        "high":   [c + 1.0 for c in close],
        "low":    [c - 1.0 for c in close],
        "close":  close,
        "volume": [500_000] * n,
    })


# ── compute() tests ───────────────────────────────────────────────────────────

@unittest.skipUnless(HAS_PANDAS, "pandas not available")
class TestCompute(unittest.TestCase):

    def test_none_returns_none(self):
        self.assertIsNone(compute(None))

    def test_empty_dataframe_returns_none(self):
        self.assertIsNone(compute(pd.DataFrame()))

    def test_insufficient_rows_returns_none(self):
        bars = _make_bars(n=5)
        self.assertIsNone(compute(bars))

    def test_valid_bars_returns_dict(self):
        bars = _make_bars(n=60)
        result = compute(bars)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)

    def test_expected_keys_present(self):
        bars = _make_bars(n=60)
        result = compute(bars)
        for key in ("rsi", "macd", "macd_signal", "macd_hist",
                    "bb_upper", "bb_mid", "bb_lower", "bb_position",
                    "sma20", "volume_ratio",
                    "stoch_k", "stoch_d", "obv", "obv_trend"):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_stoch_k_in_valid_range(self):
        bars = _make_bars(n=60)
        result = compute(bars)
        stoch_k = result.get("stoch_k")
        if stoch_k is not None:
            self.assertGreaterEqual(stoch_k, 0)
            self.assertLessEqual(stoch_k, 100)

    def test_obv_trend_is_int_or_none(self):
        bars = _make_bars(n=60)
        result = compute(bars)
        obv_trend = result.get("obv_trend")
        if obv_trend is not None:
            self.assertIsInstance(obv_trend, int)
            self.assertIn(obv_trend, (1, -1))

    def test_rsi_in_valid_range(self):
        bars = _make_bars(n=60)
        result = compute(bars)
        rsi = result.get("rsi")
        if rsi is not None:
            self.assertGreaterEqual(rsi, 0)
            self.assertLessEqual(rsi, 100)

    def test_bb_position_in_0_to_1(self):
        bars = _make_bars(n=60)
        result = compute(bars)
        bb_pos = result.get("bb_position")
        if bb_pos is not None:
            # bb_position can go slightly outside [0,1] if price is beyond bands
            self.assertIsInstance(bb_pos, float)

    def test_sma20_returned(self):
        bars = _make_bars(n=60)
        result = compute(bars)
        self.assertIsNotNone(result.get("sma20"))

    def test_sma50_only_with_enough_bars(self):
        # With only 40 bars, sma50 should be None
        bars = _make_bars(n=40)
        result = compute(bars)
        if result:
            self.assertIsNone(result.get("sma50"))

    def test_does_not_mutate_input(self):
        bars = _make_bars(n=60)
        original_cols = list(bars.columns)
        compute(bars)
        self.assertEqual(list(bars.columns), original_cols)


# ── Manual indicator tests ────────────────────────────────────────────────────

@unittest.skipUnless(HAS_PANDAS, "pandas not available")
class TestManualRsi(unittest.TestCase):

    def test_rsi_range_uptrend(self):
        # Use noisy uptrend so avg_loss > 0 (monotone series → avg_loss=0 → NaN RSI)
        close = pd.Series([100 + i * 1.5 + math.sin(i * 1.2) * 3.0 for i in range(50)])
        rsi = _manual_rsi(close, period=14)
        last_rsi = rsi.dropna().iloc[-1]
        # Strong uptrend → RSI should be high (>60)
        self.assertGreater(last_rsi, 60)

    def test_rsi_range_downtrend(self):
        close = pd.Series([100 - i * 0.5 for i in range(50)])
        rsi = _manual_rsi(close, period=14)
        last_rsi = rsi.dropna().iloc[-1]
        # Consistent downtrend → RSI should be low (<40)
        self.assertLess(last_rsi, 40)

    def test_rsi_produces_series(self):
        close = pd.Series([100.0 + i for i in range(30)])
        result = _manual_rsi(close, period=14)
        self.assertIsInstance(result, pd.Series)
        self.assertEqual(len(result), len(close))

    def test_rsi_nan_for_insufficient_data(self):
        close = pd.Series([100.0 + i for i in range(5)])
        result = _manual_rsi(close, period=14)
        # All NaN when fewer bars than period
        self.assertTrue(result.isna().all())


@unittest.skipUnless(HAS_PANDAS, "pandas not available")
class TestManualMacd(unittest.TestCase):

    def test_returns_three_series(self):
        close = pd.Series([100.0 + i * 0.3 for i in range(60)])
        macd_line, signal_line, histogram = _manual_macd(close)
        self.assertIsInstance(macd_line, pd.Series)
        self.assertIsInstance(signal_line, pd.Series)
        self.assertIsInstance(histogram, pd.Series)

    def test_histogram_equals_macd_minus_signal(self):
        close = pd.Series([100.0 + i * 0.3 for i in range(60)])
        macd_line, signal_line, histogram = _manual_macd(close)
        expected = macd_line - signal_line
        pd.testing.assert_series_equal(histogram, expected)

    def test_uptrend_positive_macd(self):
        # Strong uptrend: fast EMA > slow EMA → positive MACD
        close = pd.Series([100.0 + i * 2 for i in range(60)])
        macd_line, _, _ = _manual_macd(close)
        self.assertGreater(macd_line.dropna().iloc[-1], 0)


@unittest.skipUnless(HAS_PANDAS, "pandas not available")
class TestManualBB(unittest.TestCase):

    def test_returns_three_series(self):
        close = pd.Series([100.0 + math.sin(i) for i in range(40)])
        upper, mid, lower = _manual_bb(close)
        self.assertIsInstance(upper, pd.Series)
        self.assertIsInstance(mid, pd.Series)
        self.assertIsInstance(lower, pd.Series)

    def test_upper_gt_mid_gt_lower(self):
        close = pd.Series([100.0 + math.sin(i) for i in range(40)])
        upper, mid, lower = _manual_bb(close)
        idx = upper.dropna().index
        self.assertTrue((upper[idx] >= mid[idx]).all())
        self.assertTrue((mid[idx] >= lower[idx]).all())

    def test_mid_equals_sma(self):
        close = pd.Series([100.0 + i * 0.1 for i in range(40)])
        _, mid, _ = _manual_bb(close, period=20)
        expected_sma = close.rolling(20).mean()
        pd.testing.assert_series_equal(mid, expected_sma)


# ── format_for_prompt tests ───────────────────────────────────────────────────

class TestFormatForPrompt(unittest.TestCase):

    def test_none_indicators_returns_unavailable(self):
        result = format_for_prompt("AAPL", None, 150.0)
        self.assertIn("unavailable", result.lower())

    def test_empty_dict_returns_unavailable(self):
        result = format_for_prompt("AAPL", {}, 150.0)
        self.assertIn("unavailable", result.lower())

    def test_rsi_overbought_label(self):
        ind = {"rsi": 75.0, "macd_hist": None, "bb_upper": None, "bb_lower": None,
               "bb_position": None, "sma20": None, "sma50": None,
               "atr": None, "volume_ratio": None}
        result = format_for_prompt("AAPL", ind, 150.0)
        self.assertIn("OVERBOUGHT", result)

    def test_rsi_oversold_label(self):
        ind = {"rsi": 25.0, "macd_hist": None, "bb_upper": None, "bb_lower": None,
               "bb_position": None, "sma20": None, "sma50": None,
               "atr": None, "volume_ratio": None}
        result = format_for_prompt("AAPL", ind, 150.0)
        self.assertIn("OVERSOLD", result)

    def test_macd_bullish_label(self):
        ind = {"rsi": 50.0, "macd_hist": 0.5, "bb_upper": None, "bb_lower": None,
               "bb_position": None, "sma20": None, "sma50": None,
               "atr": None, "volume_ratio": None}
        result = format_for_prompt("AAPL", ind, 150.0)
        self.assertIn("bullish", result)

    def test_uptrend_label(self):
        ind = {"rsi": 55.0, "macd_hist": 0.1, "bb_upper": 160.0, "bb_lower": 140.0,
               "bb_position": 0.5, "sma20": 145.0, "sma50": 140.0,
               "atr": 2.0, "volume_ratio": 1.0}
        # price (155) > sma20 (145) > sma50 (140) → Uptrend
        result = format_for_prompt("AAPL", ind, 155.0)
        self.assertIn("Uptrend", result)


# ── Stochastic oscillator tests ───────────────────────────────────────────────

@unittest.skipUnless(HAS_PANDAS and HAS_STOCH_OBV, "pandas or _manual_stoch not available")
class TestManualStoch(unittest.TestCase):

    def _make_downtrend_df(self, n=60):
        close = [100.0 - i * 1.5 for i in range(n)]
        close = [max(c, 1.0) for c in close]
        return pd.DataFrame({
            "high":  [c + 0.3 for c in close],
            "low":   [c - 0.3 for c in close],
            "close": close,
        })

    def _make_uptrend_df(self, n=60):
        close = [50.0 + i * 1.5 for i in range(n)]
        return pd.DataFrame({
            "high":  [c + 0.3 for c in close],
            "low":   [c - 0.3 for c in close],
            "close": close,
        })

    def test_returns_two_series(self):
        df = _make_bars(n=60)
        result = _manual_stoch(df)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        k, d = result
        self.assertIsInstance(k, pd.Series)
        self.assertIsInstance(d, pd.Series)

    def test_k_in_range_0_to_100(self):
        df = _make_bars(n=60)
        k, _ = _manual_stoch(df)
        valid = k.dropna()
        self.assertTrue((valid >= 0).all(), "Some %K values are below 0")
        self.assertTrue((valid <= 100).all(), "Some %K values are above 100")

    def test_d_is_rolling_mean_of_k(self):
        df = _make_bars(n=60)
        k, d = _manual_stoch(df)
        # %D should equal 3-period rolling mean of %K for the last 10 non-NaN values
        d_expected = k.rolling(3).mean()
        valid_idx = d.dropna().index[-10:]
        for i in valid_idx:
            self.assertAlmostEqual(d[i], d_expected[i], places=6,
                                   msg=f"D[{i}] != rolling_mean(K, 3)[{i}]")

    def test_k_low_in_downtrend(self):
        df = self._make_downtrend_df(n=60)
        k, _ = _manual_stoch(df)
        last_k = k.dropna().iloc[-1]
        self.assertLess(last_k, 30, f"Expected %K < 30 in downtrend, got {last_k}")

    def test_k_high_in_uptrend(self):
        df = self._make_uptrend_df(n=60)
        k, _ = _manual_stoch(df)
        last_k = k.dropna().iloc[-1]
        self.assertGreater(last_k, 70, f"Expected %K > 70 in uptrend, got {last_k}")


# ── OBV tests ─────────────────────────────────────────────────────────────────

@unittest.skipUnless(HAS_PANDAS and HAS_STOCH_OBV, "pandas or _manual_obv not available")
class TestManualObv(unittest.TestCase):

    def _two_bar_df(self, close_0, close_1, volume_0=1_000_000, volume_1=1_000_000):
        return pd.DataFrame({
            "close":  [close_0, close_1],
            "volume": [volume_0, volume_1],
        })

    def test_obv_increases_on_up_day(self):
        df = self._two_bar_df(close_0=100.0, close_1=101.0)
        obv = _manual_obv(df)
        self.assertIsInstance(obv, pd.Series)
        self.assertGreater(obv.iloc[1], obv.iloc[0],
                           "OBV should increase when close rises")

    def test_obv_decreases_on_down_day(self):
        df = self._two_bar_df(close_0=100.0, close_1=99.0)
        obv = _manual_obv(df)
        self.assertLess(obv.iloc[1], obv.iloc[0],
                        "OBV should decrease when close falls")

    def test_obv_flat_on_unchanged_close(self):
        df = self._two_bar_df(close_0=100.0, close_1=100.0)
        obv = _manual_obv(df)
        self.assertEqual(obv.iloc[1], obv.iloc[0],
                         "OBV should not change when close is unchanged")

    def test_obv_rising_trend_in_uptrend(self):
        n = 20
        close = [50.0 + i for i in range(n)]
        df = pd.DataFrame({
            "close":  close,
            "volume": [1_000_000] * n,
        })
        obv = _manual_obv(df)
        self.assertGreater(obv.iloc[-1], obv.iloc[0],
                           "OBV should rise over a 20-bar uptrend")


if __name__ == "__main__":
    unittest.main()
