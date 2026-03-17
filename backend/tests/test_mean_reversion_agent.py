"""
Unit tests for agents/mean_reversion_agent.py
Covers: _calculate_zscore(), _generate_signal(), analyze()
"""
import sys
import os
import unittest
import asyncio

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

from agents.mean_reversion_agent import MeanReversionAgent
from trading.portfolio import Position


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_bars(n=30, start=100.0, std=2.0, seed=42):
    """Generate bars with mild random noise around a flat mean — good for z-score tests."""
    if not HAS_PANDAS:
        return None
    rng = np.random.default_rng(seed)
    close = [start + rng.normal(0, std) for _ in range(n)]
    return pd.DataFrame({
        "open":   close,
        "high":   [c + abs(rng.normal(0, 0.5)) for c in close],
        "low":    [c - abs(rng.normal(0, 0.5)) for c in close],
        "close":  close,
        "volume": [1_000_000] * n,
    })


def _make_oversold_bars(n=30, mean=100.0, seed=7):
    """Last price well below 20-day mean → z-score < -1.5.
    Uses small noise throughout so rolling_std > 0, then drops last bar far below mean.
    """
    if not HAS_PANDAS:
        return None
    rng = np.random.default_rng(seed)
    close = [mean + rng.normal(0, 0.5) for _ in range(n - 1)] + [mean - 10.0]
    return pd.DataFrame({
        "open":   close,
        "high":   [c + 0.3 for c in close],
        "low":    [c - 0.3 for c in close],
        "close":  close,
        "volume": [1_000_000] * n,
    })


def _make_overbought_bars(n=30, mean=100.0, seed=13):
    """Last price well above 20-day mean → z-score > +1.5.
    Uses small noise throughout so rolling_std > 0, then spikes last bar far above mean.
    """
    if not HAS_PANDAS:
        return None
    rng = np.random.default_rng(seed)
    close = [mean + rng.normal(0, 0.5) for _ in range(n - 1)] + [mean + 10.0]
    return pd.DataFrame({
        "open":   close,
        "high":   [c + 0.3 for c in close],
        "low":    [c - 0.3 for c in close],
        "close":  close,
        "volume": [1_000_000] * n,
    })


# ── _calculate_zscore tests ───────────────────────────────────────────────────

@unittest.skipUnless(HAS_PANDAS, "pandas not available")
class TestCalculateZScore(unittest.TestCase):

    def setUp(self):
        self.agent = MeanReversionAgent()

    def test_none_returns_none(self):
        self.assertIsNone(self.agent._calculate_zscore(None))

    def test_too_few_bars_returns_none(self):
        bars = _make_bars(n=10)
        self.assertIsNone(self.agent._calculate_zscore(bars))

    def test_valid_bars_returns_dict(self):
        bars = _make_bars(n=30)
        result = self.agent._calculate_zscore(bars)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)

    def test_expected_keys_present(self):
        bars = _make_bars(n=30)
        result = self.agent._calculate_zscore(bars)
        for key in ("z_score", "rolling_mean", "rolling_std", "current_price",
                    "z_trend", "reversion_frequency", "bb_position", "atr_pct"):
            self.assertIn(key, result)

    def test_oversold_bar_produces_negative_z(self):
        bars = _make_oversold_bars()
        result = self.agent._calculate_zscore(bars)
        self.assertIsNotNone(result)
        self.assertLess(result["z_score"], -1.5)

    def test_overbought_bar_produces_positive_z(self):
        bars = _make_overbought_bars()
        result = self.agent._calculate_zscore(bars)
        self.assertIsNotNone(result)
        self.assertGreater(result["z_score"], 1.5)

    def test_constant_price_returns_none(self):
        """All closes identical → std == 0 → should return None."""
        close = [100.0] * 30
        bars = pd.DataFrame({"open": close, "high": close, "low": close,
                              "close": close, "volume": [1_000_000] * 30})
        self.assertIsNone(self.agent._calculate_zscore(bars))

    def test_bb_position_in_range(self):
        bars = _make_bars(n=30)
        result = self.agent._calculate_zscore(bars)
        # bb_position should be 0..1 for a price inside the bands
        self.assertGreaterEqual(result["bb_position"], 0.0)
        self.assertLessEqual(result["bb_position"], 1.0)


# ── _generate_signal tests ────────────────────────────────────────────────────

@unittest.skipUnless(HAS_PANDAS, "pandas not available")
class TestGenerateSignal(unittest.TestCase):

    def setUp(self):
        self.agent = MeanReversionAgent()

    def _stats(self, z=0.0, trend=0.0, mean=100.0, std=2.0):
        return {
            "z_score": z,
            "rolling_mean": mean,
            "rolling_std": std,
            "current_price": mean + z * std,
            "z_trend": trend,
            "reversion_frequency": 0.3,
            "bb_position": 0.5,
            "atr_pct": 0.01,
            "recent_z_scores": [z],
        }

    def test_zero_price_returns_hold(self):
        stats = self._stats(z=-2.0)
        signal = self.agent._generate_signal("AAPL", stats, {"AAPL": 0.0})
        self.assertEqual(signal.action, "HOLD")

    def test_oversold_no_position_returns_buy(self):
        stats = self._stats(z=-2.0, mean=100.0, std=2.0)
        prices = {"AAPL": 96.0}
        signal = self.agent._generate_signal("AAPL", stats, prices)
        self.assertEqual(signal.action, "BUY")

    def test_oversold_with_position_returns_hold_not_buy(self):
        """Already holding — should not double-buy."""
        self.agent.portfolio.positions["AAPL"] = Position("AAPL", 10, 98.0)
        stats = self._stats(z=-2.0, mean=100.0, std=2.0)
        prices = {"AAPL": 96.0}
        signal = self.agent._generate_signal("AAPL", stats, prices)
        self.assertNotEqual(signal.action, "BUY")

    def test_overbought_with_position_returns_sell(self):
        self.agent.portfolio.positions["AAPL"] = Position("AAPL", 10, 95.0)
        stats = self._stats(z=2.0, mean=100.0, std=2.0)
        prices = {"AAPL": 104.0}
        signal = self.agent._generate_signal("AAPL", stats, prices)
        self.assertEqual(signal.action, "SELL")

    def test_overbought_without_position_returns_hold(self):
        """Overbought but no position → nothing to sell."""
        stats = self._stats(z=2.0)
        prices = {"AAPL": 104.0}
        signal = self.agent._generate_signal("AAPL", stats, prices)
        self.assertNotEqual(signal.action, "SELL")

    def test_profit_take_near_mean(self):
        """z near 0 with a position at profit → SELL (take profit)."""
        self.agent.portfolio.positions["AAPL"] = Position("AAPL", 10, 95.0)
        # current price 101, avg cost 95 → ~6.3% gain; z near 0
        stats = self._stats(z=0.1, mean=100.0, std=2.0)
        prices = {"AAPL": 101.0}
        signal = self.agent._generate_signal("AAPL", stats, prices)
        self.assertEqual(signal.action, "SELL")

    def test_reverting_z_boosts_buy_confidence(self):
        """z_trend > 0 (rising from oversold) should boost confidence."""
        stats_no_trend  = self._stats(z=-2.0, trend=0.0)
        stats_reverting = self._stats(z=-2.0, trend=0.5)
        prices = {"AAPL": 96.0}
        sig_no  = self.agent._generate_signal("AAPL", stats_no_trend, prices)
        self.agent2 = MeanReversionAgent()
        sig_rev = self.agent2._generate_signal("AAPL", stats_reverting, prices)
        self.assertGreaterEqual(sig_rev.confidence, sig_no.confidence)

    def test_mid_z_no_position_returns_hold(self):
        stats = self._stats(z=-0.5)
        signal = self.agent._generate_signal("AAPL", stats, {"AAPL": 99.0})
        self.assertEqual(signal.action, "HOLD")


# ── analyze() integration tests ───────────────────────────────────────────────

@unittest.skipUnless(HAS_PANDAS, "pandas not available")
class TestMeanReversionAnalyze(unittest.TestCase):

    def setUp(self):
        self.agent = MeanReversionAgent()

    def test_returns_signal_for_each_symbol(self):
        bars = _make_bars(n=30)
        ctx = {
            "AAPL": {"bars": bars, "price": float(bars["close"].iloc[-1])},
            "MSFT": {"bars": bars, "price": float(bars["close"].iloc[-1])},
        }
        signals = run(self.agent.analyze(ctx))
        syms = {s.symbol for s in signals}
        self.assertIn("AAPL", syms)
        self.assertIn("MSFT", syms)

    def test_no_bars_returns_hold(self):
        ctx = {"AAPL": {"bars": None, "price": 150.0}}
        signals = run(self.agent.analyze(ctx))
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].action, "HOLD")

    def test_skips_non_dict_context(self):
        bars = _make_bars(n=30)
        ctx = {
            "AAPL": {"bars": bars, "price": float(bars["close"].iloc[-1])},
            "__overnight_catalysts__": [{"headline": "test"}],
        }
        signals = run(self.agent.analyze(ctx))
        syms = [s.symbol for s in signals]
        self.assertNotIn("__overnight_catalysts__", syms)

    def test_insufficient_bars_returns_hold(self):
        bars = _make_bars(n=5)   # too few for z-score
        ctx = {"AAPL": {"bars": bars, "price": 100.0}}
        signals = run(self.agent.analyze(ctx))
        self.assertEqual(signals[0].action, "HOLD")

    def test_oversold_symbol_generates_buy(self):
        bars = _make_oversold_bars(mean=100.0)
        price = float(bars["close"].iloc[-1])
        ctx = {"AAPL": {"bars": bars, "price": price}}
        signals = run(self.agent.analyze(ctx))
        self.assertEqual(signals[0].action, "BUY")


if __name__ == "__main__":
    unittest.main()
