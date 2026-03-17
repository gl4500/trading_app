"""
Unit tests for agents/momentum_agent.py
Covers: _calculate_momentum(), _check_trailing_stop(), _generate_signal(),
        full analyze() cycle.
Requires: pandas
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
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

from agents.momentum_agent import MomentumAgent
from trading.portfolio import Position


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_bars(n=30, start=100.0, trend=0.5):
    if not HAS_PANDAS:
        return None
    close = [start + i * trend for i in range(n)]
    return pd.DataFrame({
        "open":   close,
        "high":   [c + 1.0 for c in close],
        "low":    [c - 1.0 for c in close],
        "close":  close,
        "volume": [1_000_000] * n,
    })


def _make_downtrend_bars(n=30, start=100.0):
    if not HAS_PANDAS:
        return None
    close = [start - i * 0.8 for i in range(n)]
    return pd.DataFrame({
        "open":   close,
        "high":   [c + 0.5 for c in close],
        "low":    [c - 0.5 for c in close],
        "close":  close,
        "volume": [1_000_000] * n,
    })


# ── _calculate_momentum tests ─────────────────────────────────────────────────

@unittest.skipUnless(HAS_PANDAS, "pandas not available")
class TestCalculateMomentum(unittest.TestCase):

    def setUp(self):
        self.agent = MomentumAgent()

    def test_none_bars_returns_none(self):
        result = self.agent._calculate_momentum(None)
        self.assertIsNone(result)

    def test_insufficient_bars_returns_none(self):
        bars = _make_bars(n=5)
        result = self.agent._calculate_momentum(bars)
        self.assertIsNone(result)

    def test_valid_bars_returns_dict(self):
        bars = _make_bars(n=30)
        result = self.agent._calculate_momentum(bars)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)

    def test_expected_keys_present(self):
        bars = _make_bars(n=30)
        result = self.agent._calculate_momentum(bars)
        for key in ("mom_short", "mom_mid", "mom_long", "vw_momentum",
                    "trend_consistency", "volume_ratio", "ma_trend", "current_price"):
            self.assertIn(key, result)

    def test_uptrend_positive_short_momentum(self):
        bars = _make_bars(n=30, trend=2.0)   # strong uptrend
        result = self.agent._calculate_momentum(bars)
        self.assertGreater(result["mom_short"], 0)

    def test_downtrend_negative_short_momentum(self):
        bars = _make_downtrend_bars(n=30)
        result = self.agent._calculate_momentum(bars)
        self.assertLess(result["mom_short"], 0)

    def test_trend_consistency_uptrend(self):
        bars = _make_bars(n=30, trend=1.0)
        result = self.agent._calculate_momentum(bars)
        # Every day is up → trend_consistency should be close to 1.0
        self.assertGreater(result["trend_consistency"], 0.8)


# ── _check_trailing_stop tests ────────────────────────────────────────────────

class TestTrailingStop(unittest.TestCase):

    def setUp(self):
        self.agent = MomentumAgent()

    def test_no_position_returns_false(self):
        result = self.agent._check_trailing_stop("AAPL", 150.0)
        self.assertFalse(result)

    def test_price_at_high_water_mark_no_stop(self):
        self.agent.portfolio.positions["AAPL"] = Position("AAPL", 10, 100.0)
        self.agent._high_water_marks["AAPL"] = 150.0
        result = self.agent._check_trailing_stop("AAPL", 150.0)
        self.assertFalse(result)

    def test_small_drop_no_stop(self):
        self.agent.portfolio.positions["AAPL"] = Position("AAPL", 10, 100.0)
        self.agent._high_water_marks["AAPL"] = 150.0
        # 1% drop — below trailing_stop threshold of 3%
        result = self.agent._check_trailing_stop("AAPL", 148.5)
        self.assertFalse(result)

    def test_large_drop_triggers_stop(self):
        self.agent.portfolio.positions["AAPL"] = Position("AAPL", 10, 100.0)
        self.agent._high_water_marks["AAPL"] = 150.0
        # 5% drop from high water mark (150 → 142.5) — exceeds 3% trailing stop
        result = self.agent._check_trailing_stop("AAPL", 142.5)
        self.assertTrue(result)

    def test_new_high_updates_water_mark(self):
        self.agent.portfolio.positions["AAPL"] = Position("AAPL", 10, 100.0)
        self.agent._high_water_marks["AAPL"] = 150.0
        # Price exceeds old high water mark → updates it, no stop
        result = self.agent._check_trailing_stop("AAPL", 160.0)
        self.assertFalse(result)
        self.assertEqual(self.agent._high_water_marks["AAPL"], 160.0)


# ── _generate_signal tests ────────────────────────────────────────────────────

@unittest.skipUnless(HAS_PANDAS, "pandas not available")
class TestGenerateSignal(unittest.TestCase):

    def setUp(self):
        self.agent = MomentumAgent()

    def test_strong_uptrend_generates_buy(self):
        bars = _make_bars(n=30, trend=3.0)   # steep uptrend
        indicators = self.agent._calculate_momentum(bars)
        prices = {"AAPL": float(bars["close"].iloc[-1])}
        signal = self.agent._generate_signal("AAPL", indicators, prices)
        self.assertEqual(signal.action, "BUY")

    def test_strong_downtrend_with_position_generates_sell(self):
        bars = _make_downtrend_bars(n=30)
        self.agent.portfolio.positions["AAPL"] = Position("AAPL", 10, 110.0)
        indicators = self.agent._calculate_momentum(bars)
        prices = {"AAPL": float(bars["close"].iloc[-1])}
        signal = self.agent._generate_signal("AAPL", indicators, prices)
        self.assertEqual(signal.action, "SELL")

    def test_zero_price_returns_hold(self):
        bars = _make_bars(n=30, trend=1.0)
        indicators = self.agent._calculate_momentum(bars)
        signal = self.agent._generate_signal("AAPL", indicators, {"AAPL": 0.0})
        self.assertEqual(signal.action, "HOLD")

    def test_trailing_stop_overrides_buy_score(self):
        bars = _make_bars(n=30, trend=1.0)
        # Set up position + high water mark well above current price
        current_price = float(bars["close"].iloc[-1])
        self.agent.portfolio.positions["AAPL"] = Position("AAPL", 10, current_price * 1.10)
        self.agent._high_water_marks["AAPL"] = current_price * 1.10
        indicators = self.agent._calculate_momentum(bars)
        prices = {"AAPL": current_price}
        signal = self.agent._generate_signal("AAPL", indicators, prices)
        # Trailing stop triggered (> 3% drop from high water) → SELL
        self.assertEqual(signal.action, "SELL")


# ── analyze() integration test ────────────────────────────────────────────────

@unittest.skipUnless(HAS_PANDAS, "pandas not available")
class TestMomentumAnalyze(unittest.TestCase):

    def setUp(self):
        self.agent = MomentumAgent()

    def test_analyze_returns_signals_for_all_symbols(self):
        bars = _make_bars(n=30)
        ctx = {
            "AAPL": {"bars": bars, "price": 115.0},
            "MSFT": {"bars": bars, "price": 310.0},
        }
        signals = run(self.agent.analyze(ctx))
        syms = {s.symbol for s in signals}
        self.assertIn("AAPL", syms)
        self.assertIn("MSFT", syms)

    def test_analyze_no_bars_returns_hold(self):
        ctx = {"AAPL": {"bars": None, "price": 150.0}}
        signals = run(self.agent.analyze(ctx))
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].action, "HOLD")

    def test_analyze_skips_non_dict_context(self):
        ctx = {
            "AAPL": {"bars": _make_bars(30), "price": 115.0},
            "__overnight_catalysts__": [{"headline": "test"}],
        }
        signals = run(self.agent.analyze(ctx))
        syms = [s.symbol for s in signals]
        self.assertNotIn("__overnight_catalysts__", syms)


if __name__ == "__main__":
    unittest.main()
