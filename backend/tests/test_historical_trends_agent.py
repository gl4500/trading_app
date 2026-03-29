"""
Unit tests for agents/historical_trends_agent.py
Covers: _seasonal_score(), _channel_analysis(), _multi_period_momentum(),
        _long_term_volume_trend(), _generate_signal(), analyze() integration.
"""
import sys
import os
import unittest
import asyncio
from datetime import date

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

from agents.historical_trends_agent import HistoricalTrendsAgent, MONTHLY_SEASONAL_BIAS
from trading.portfolio import Position


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_bars(n=50, trend=0.5, start=100.0, flat=False):
    """Create sample OHLCV bars."""
    if not HAS_PANDAS:
        return None
    if flat:
        close = [start] * n
    else:
        close = [start + i * trend for i in range(n)]
    return pd.DataFrame({
        "open":   close,
        "high":   [c + 1.0 for c in close],
        "low":    [c - 1.0 for c in close],
        "close":  close,
        "volume": [1_000_000] * n,
    })


def _make_downtrend_bars(n=50, start=150.0):
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


# ── Seasonal score tests ───────────────────────────────────────────────────────

class TestSeasonalScore(unittest.TestCase):

    def setUp(self):
        self.agent = HistoricalTrendsAgent()

    def test_returns_tuple_of_float_and_string(self):
        score, reason = self.agent._seasonal_score(date(2026, 1, 15))
        self.assertIsInstance(score, float)
        self.assertIsInstance(reason, str)

    def test_january_positive_bias(self):
        score, _ = self.agent._seasonal_score(date(2026, 1, 15))
        # January has positive seasonal bias
        self.assertGreater(score, 0)

    def test_september_negative_bias(self):
        score, _ = self.agent._seasonal_score(date(2026, 9, 15))
        # September is historically the worst month
        self.assertLess(score, 0)

    def test_december_positive_bias(self):
        score, _ = self.agent._seasonal_score(date(2026, 12, 15))
        self.assertGreater(score, 0)

    def test_score_bounded(self):
        for month in range(1, 13):
            score, _ = self.agent._seasonal_score(date(2026, month, 15))
            self.assertGreaterEqual(score, -1.0)
            self.assertLessEqual(score, 1.0)

    def test_reason_contains_month_name(self):
        _, reason = self.agent._seasonal_score(date(2026, 11, 1))
        self.assertIn("November", reason)

    def test_all_months_covered(self):
        for month in range(1, 13):
            score, reason = self.agent._seasonal_score(date(2026, month, 15))
            self.assertIsNotNone(score)
            self.assertTrue(len(reason) > 0)


# ── Channel analysis tests ────────────────────────────────────────────────────

@unittest.skipUnless(HAS_PANDAS, "pandas not available")
class TestChannelAnalysis(unittest.TestCase):

    def setUp(self):
        self.agent = HistoricalTrendsAgent()

    def test_returns_tuple_of_float_and_string(self):
        bars = _make_bars(n=50)
        price = float(bars["close"].iloc[-1])
        score, reason = self.agent._channel_analysis(bars, price)
        self.assertIsInstance(score, float)
        self.assertIsInstance(reason, str)

    def test_price_at_period_low_bullish(self):
        bars = _make_bars(n=50, trend=0.5)
        # Use the period low (first bar's close) as current price
        low_price = float(bars["close"].iloc[0])
        score, _ = self.agent._channel_analysis(bars, low_price)
        # Near period low → positive (bullish) channel signal
        self.assertGreater(score, 0)

    def test_price_at_period_high_bearish(self):
        bars = _make_bars(n=50, trend=0.5)
        # Use the period high (last bar's close) as current price
        high_price = float(bars["close"].iloc[-1])
        score, _ = self.agent._channel_analysis(bars, high_price)
        # Near period high → negative (bearish) channel signal
        self.assertLess(score, 0)

    def test_score_bounded(self):
        bars = _make_bars(n=50, trend=1.0)
        price = float(bars["close"].iloc[-1])
        score, _ = self.agent._channel_analysis(bars, price)
        self.assertGreaterEqual(score, -1.0)
        self.assertLessEqual(score, 1.0)

    def test_flat_bars_mid_channel(self):
        bars = _make_bars(n=50, flat=True)
        # All prices identical — channel range is 0, should return gracefully
        score, reason = self.agent._channel_analysis(bars, 100.0)
        self.assertIsInstance(score, float)

    def test_reason_contains_position_info(self):
        bars = _make_bars(n=50, trend=0.5)
        price = float(bars["close"].iloc[-1])
        _, reason = self.agent._channel_analysis(bars, price)
        self.assertIn("channel", reason.lower())


# ── Multi-period momentum tests ───────────────────────────────────────────────

@unittest.skipUnless(HAS_PANDAS, "pandas not available")
class TestMultiPeriodMomentum(unittest.TestCase):

    def setUp(self):
        self.agent = HistoricalTrendsAgent()

    def test_returns_tuple_of_float_and_string(self):
        bars = _make_bars(n=50, trend=0.5)
        score, reason = self.agent._multi_period_momentum(bars)
        self.assertIsInstance(score, float)
        self.assertIsInstance(reason, str)

    def test_uptrend_positive_score(self):
        bars = _make_bars(n=50, trend=2.0)
        score, _ = self.agent._multi_period_momentum(bars)
        self.assertGreater(score, 0)

    def test_downtrend_negative_score(self):
        bars = _make_downtrend_bars(n=50)
        score, _ = self.agent._multi_period_momentum(bars)
        self.assertLess(score, 0)

    def test_score_bounded(self):
        bars = _make_bars(n=50, trend=5.0)
        score, _ = self.agent._multi_period_momentum(bars)
        self.assertGreaterEqual(score, -1.0)
        self.assertLessEqual(score, 1.0)

    def test_insufficient_bars_returns_zero(self):
        bars = _make_bars(n=3)
        score, reason = self.agent._multi_period_momentum(bars)
        self.assertEqual(score, 0.0)
        self.assertIn("Insufficient", reason)

    def test_reason_contains_period_data(self):
        bars = _make_bars(n=50, trend=1.0)
        _, reason = self.agent._multi_period_momentum(bars)
        # Should mention at least one period
        self.assertTrue(any(p in reason for p in ["5d", "10d", "20d", "40d"]))


# ── Volume trend tests ─────────────────────────────────────────────────────────

@unittest.skipUnless(HAS_PANDAS, "pandas not available")
class TestVolumeTrend(unittest.TestCase):

    def setUp(self):
        self.agent = HistoricalTrendsAgent()

    def test_returns_tuple(self):
        bars = _make_bars(n=50)
        score, reason = self.agent._long_term_volume_trend(bars)
        self.assertIsInstance(score, float)
        self.assertIsInstance(reason, str)

    def test_no_volume_column_returns_zero(self):
        bars = _make_bars(n=50)
        bars_no_vol = bars.drop(columns=["volume"])
        score, _ = self.agent._long_term_volume_trend(bars_no_vol)
        self.assertEqual(score, 0.0)

    def test_insufficient_bars_returns_zero(self):
        bars = _make_bars(n=5)
        score, _ = self.agent._long_term_volume_trend(bars)
        self.assertEqual(score, 0.0)

    def test_score_small_magnitude(self):
        bars = _make_bars(n=50, trend=1.0)
        score, _ = self.agent._long_term_volume_trend(bars)
        # Volume score is a small confirmation signal, not a large one
        self.assertLessEqual(abs(score), 0.2)


# ── _generate_signal tests ────────────────────────────────────────────────────

@unittest.skipUnless(HAS_PANDAS, "pandas not available")
class TestGenerateSignal(unittest.TestCase):

    def setUp(self):
        self.agent = HistoricalTrendsAgent()

    def _prices(self, symbol="AAPL", price=100.0):
        return {symbol: price}

    def test_all_bullish_scores_generates_buy(self):
        bars = _make_bars(n=50, trend=0.5)
        signal = self.agent._generate_signal(
            "AAPL",
            seasonal_score=0.5,
            channel_score=0.5,
            momentum_score=0.5,
            volume_score=0.1,
            reasons=["seasonal", "channel", "momentum"],
            prices=self._prices(),
            df=bars,
        )
        self.assertEqual(signal.action, "BUY")

    def test_all_bearish_with_position_generates_sell(self):
        bars = _make_bars(n=50, trend=0.5)
        self.agent.portfolio.positions["AAPL"] = Position("AAPL", 10, 100.0)
        signal = self.agent._generate_signal(
            "AAPL",
            seasonal_score=-0.5,
            channel_score=-0.5,
            momentum_score=-0.5,
            volume_score=-0.1,
            reasons=["seasonal", "channel", "momentum"],
            prices=self._prices(),
            df=bars,
        )
        self.assertEqual(signal.action, "SELL")

    def test_mixed_signals_generates_hold(self):
        bars = _make_bars(n=50)
        signal = self.agent._generate_signal(
            "AAPL",
            seasonal_score=0.1,
            channel_score=-0.1,
            momentum_score=0.05,
            volume_score=0.0,
            reasons=["seasonal", "channel", "momentum"],
            prices=self._prices(),
            df=bars,
        )
        self.assertEqual(signal.action, "HOLD")

    def test_zero_price_returns_hold(self):
        bars = _make_bars(n=50)
        bars_zero = bars.copy()
        bars_zero["close"] = [0.0] * len(bars_zero)
        signal = self.agent._generate_signal(
            "AAPL",
            seasonal_score=0.9,
            channel_score=0.9,
            momentum_score=0.9,
            volume_score=0.1,
            reasons=[],
            prices={"AAPL": 0.0},
            df=bars_zero,
        )
        self.assertEqual(signal.action, "HOLD")

    def test_bullish_buy_sets_shares_positive(self):
        bars = _make_bars(n=50, trend=0.5)
        signal = self.agent._generate_signal(
            "AAPL",
            seasonal_score=0.5,
            channel_score=0.5,
            momentum_score=0.5,
            volume_score=0.1,
            reasons=["seasonal", "channel", "momentum"],
            prices=self._prices("AAPL", 100.0),
            df=bars,
        )
        if signal.action == "BUY":
            self.assertGreater(signal.shares, 0)

    def test_reasoning_tagged_with_hist_trends(self):
        bars = _make_bars(n=50, trend=0.5)
        signal = self.agent._generate_signal(
            "AAPL",
            seasonal_score=0.5,
            channel_score=0.5,
            momentum_score=0.5,
            volume_score=0.1,
            reasons=["seasonal reason"],
            prices=self._prices(),
            df=bars,
        )
        self.assertIn("HIST", signal.reasoning)


# ── analyze() integration tests ───────────────────────────────────────────────

@unittest.skipUnless(HAS_PANDAS, "pandas not available")
class TestHistoricalTrendsAnalyze(unittest.TestCase):

    def setUp(self):
        self.agent = HistoricalTrendsAgent()

    def test_analyze_returns_signals_for_all_symbols(self):
        bars = _make_bars(n=50)
        ctx = {
            "AAPL": {"bars": bars, "price": float(bars["close"].iloc[-1])},
            "MSFT": {"bars": bars, "price": float(bars["close"].iloc[-1])},
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

    def test_analyze_insufficient_bars_returns_hold(self):
        bars = _make_bars(n=5)  # less than min_bars (30)
        ctx = {"AAPL": {"bars": bars, "price": 100.0}}
        signals = run(self.agent.analyze(ctx))
        self.assertEqual(signals[0].action, "HOLD")

    def test_analyze_skips_non_dict_context(self):
        bars = _make_bars(n=50)
        ctx = {
            "AAPL": {"bars": bars, "price": float(bars["close"].iloc[-1])},
            "__overnight_catalysts__": [{"headline": "test"}],
        }
        signals = run(self.agent.analyze(ctx))
        syms = [s.symbol for s in signals]
        self.assertNotIn("__overnight_catalysts__", syms)

    def test_analyze_signal_has_required_fields(self):
        bars = _make_bars(n=50)
        ctx = {"AAPL": {"bars": bars, "price": float(bars["close"].iloc[-1])}}
        signals = run(self.agent.analyze(ctx))
        s = signals[0]
        self.assertIn(s.action, ("BUY", "SELL", "HOLD"))
        self.assertIsNotNone(s.confidence)
        self.assertIsNotNone(s.reasoning)

    def test_analyze_empty_context_returns_empty(self):
        signals = run(self.agent.analyze({}))
        self.assertEqual(signals, [])

    def test_analyze_uptrend_in_november_likely_buy(self):
        """Strong uptrend + November (seasonal tailwind) should lean BUY."""
        import unittest.mock as mock
        bars = _make_bars(n=50, trend=3.0, start=50.0)
        price = float(bars["close"].iloc[-1])
        ctx = {"AAPL": {"bars": bars, "price": price}}
        # Patch datetime.now().date() to return November
        with mock.patch("agents.historical_trends_agent.datetime") as mock_dt:
            mock_dt.now.return_value.date.return_value = date(2026, 11, 15)
            signals = run(self.agent.analyze(ctx))
        self.assertEqual(len(signals), 1)
        # With strong uptrend + November, should be BUY or at minimum high confidence HOLD
        self.assertIn(signals[0].action, ("BUY", "HOLD"))


if __name__ == "__main__":
    unittest.main()
