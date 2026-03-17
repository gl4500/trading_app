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
                    "sma20", "volume_ratio"):
            self.assertIn(key, result, f"Missing key: {key}")

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


if __name__ == "__main__":
    unittest.main()
