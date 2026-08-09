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

import unittest.mock as mock

from agents.historical_trends_agent import HistoricalTrendsAgent, MONTHLY_SEASONAL_BIAS
from config import config
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
        from datetime import datetime, timezone
        bars = _make_bars(n=50, trend=3.0, start=50.0)
        price = float(bars["close"].iloc[-1])
        ctx = {"AAPL": {"bars": bars, "price": price}}
        # Inject the as-of clock so the seasonal pillar sees November. (Since the
        # clock seam landed, the date flows through self._now(), not module-level
        # datetime — patching the latter would silently no-op.)
        self.agent._clock = lambda: datetime(2026, 11, 15, tzinfo=timezone.utc)
        signals = run(self.agent.analyze(ctx))
        self.assertEqual(len(signals), 1)
        # With strong uptrend + November, should be BUY or at minimum high confidence HOLD
        self.assertIn(signals[0].action, ("BUY", "HOLD"))


# ── Fix 1: pre-arm stop — the trail-arm gap (ledger Iteration 15, H16) ────────
#
# A position that never reaches TRAIL_ARM_USD of peak unrealized profit is never
# protected by the trailing stop, so nothing stands between its entry and the
# -8% hard stop. That gap is 100% of this agent's realized loss column.
# HIST_PREARM_STOP_PCT installs a tighter provisional stop that applies ONLY
# while the trail is unarmed. Default 0.0 = disabled, behaviour unchanged.

class TestPreArmStop(unittest.TestCase):

    def setUp(self):
        self.agent = HistoricalTrendsAgent()
        self.agent.portfolio.positions["AAPL"] = Position("AAPL", 10, 100.0)
        self.agent.portfolio._position_peak_unrealized["AAPL"] = 0.0

    def test_disabled_by_default_returns_none(self):
        """Default config must not change live behaviour: no pre-arm stop fires."""
        self.assertEqual(config.HIST_PREARM_STOP_PCT, 0.0)
        self.assertIsNone(self.agent._prearm_stop_signal("AAPL", 80.0))

    def test_sells_unprotected_loser_while_trail_is_unarmed(self):
        with mock.patch.object(config, "HIST_PREARM_STOP_PCT", 0.04):
            signal = self.agent._prearm_stop_signal("AAPL", 95.0)   # down 5%
        self.assertIsNotNone(signal)
        self.assertEqual(signal.action, "SELL")
        self.assertEqual(signal.shares, 10)

    def test_holds_position_that_has_not_breached_the_stop(self):
        with mock.patch.object(config, "HIST_PREARM_STOP_PCT", 0.04):
            self.assertIsNone(self.agent._prearm_stop_signal("AAPL", 98.0))  # down 2%

    def test_defers_to_trailing_stop_once_armed(self):
        """Past TRAIL_ARM_USD the trailing stop owns the position — do not double up."""
        self.agent.portfolio._position_peak_unrealized["AAPL"] = config.TRAIL_ARM_USD + 1.0
        with mock.patch.object(config, "HIST_PREARM_STOP_PCT", 0.04):
            self.assertIsNone(self.agent._prearm_stop_signal("AAPL", 95.0))

    def test_no_position_returns_none(self):
        with mock.patch.object(config, "HIST_PREARM_STOP_PCT", 0.04):
            self.assertIsNone(self.agent._prearm_stop_signal("MSFT", 1.0))

    def test_analyze_emits_the_prearm_sell_instead_of_a_composite_signal(self):
        bars = _make_bars(n=50, trend=0.5)
        ctx = {"AAPL": {"bars": bars, "price": 95.0}}
        with mock.patch.object(config, "HIST_PREARM_STOP_PCT", 0.04):
            signals = run(self.agent.analyze(ctx))
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].action, "SELL")
        self.assertIn("PRE-ARM STOP", signals[0].reasoning)


# ── Fix 2: seasonal weight is configurable (H17) ──────────────────────────────
#
# The seasonal pillar is long-run S&P *index* seasonality applied to single
# names; on the live sample its sign is inverted. HIST_SEASONAL_WEIGHT makes it
# tunable. Zeroing it renormalises the remaining pillars so the composite stays
# on the same scale and the +/-0.25 thresholds keep their meaning.

class TestSeasonalWeightKnob(unittest.TestCase):

    def setUp(self):
        self.agent = HistoricalTrendsAgent()

    def test_default_weights_match_the_documented_mix(self):
        seasonal, channel, momentum, volume = self.agent._composite_weights()
        self.assertAlmostEqual(seasonal, 0.20)
        self.assertAlmostEqual(channel,  0.30)
        self.assertAlmostEqual(momentum, 0.40)
        self.assertAlmostEqual(volume,   0.10)

    def test_weights_always_sum_to_one(self):
        for weight in (0.0, 0.10, 0.20, 0.50):
            with mock.patch.object(config, "HIST_SEASONAL_WEIGHT", weight):
                self.assertAlmostEqual(sum(self.agent._composite_weights()), 1.0)

    def test_zeroing_seasonal_redistributes_proportionally(self):
        with mock.patch.object(config, "HIST_SEASONAL_WEIGHT", 0.0):
            seasonal, channel, momentum, volume = self.agent._composite_weights()
        self.assertAlmostEqual(seasonal, 0.0)
        self.assertAlmostEqual(channel,  0.375)   # 0.30 / 0.80
        self.assertAlmostEqual(momentum, 0.500)   # 0.40 / 0.80
        self.assertAlmostEqual(volume,   0.125)   # 0.10 / 0.80

    def test_zeroed_seasonal_score_cannot_move_the_composite(self):
        bars = _make_bars(n=50, trend=0.5)
        prices = {"AAPL": 100.0}
        with mock.patch.object(config, "HIST_SEASONAL_WEIGHT", 0.0):
            bullish = self.agent._generate_signal(
                "AAPL", seasonal_score=1.0, channel_score=0.1, momentum_score=0.1,
                volume_score=0.0, reasons=[], prices=prices, df=bars)
            bearish = self.agent._generate_signal(
                "AAPL", seasonal_score=-1.0, channel_score=0.1, momentum_score=0.1,
                volume_score=0.0, reasons=[], prices=prices, df=bars)
        self.assertAlmostEqual(bullish.confidence, bearish.confidence)


# ── Fix 3: sizing confidence cap (H17) ───────────────────────────────────────
#
# Size scales with confidence = |composite|, but composite > +0.60 is the only
# net-negative entry bucket — so the worst bucket gets the largest positions.
# HIST_CONFIDENCE_CAP caps the confidence used for SIZING only; the confidence
# reported on the signal stays honest. Default 0.0 = disabled.

class TestSizingConfidenceCap(unittest.TestCase):

    def setUp(self):
        self.agent = HistoricalTrendsAgent()
        self.bars = _make_bars(n=50, trend=0.5)
        self.prices = {"AAPL": 100.0}

    def _buy(self, score):
        return self.agent._generate_signal(
            "AAPL", seasonal_score=score, channel_score=score, momentum_score=score,
            volume_score=0.0, reasons=[], prices=self.prices, df=self.bars)

    def test_disabled_by_default(self):
        self.assertEqual(config.HIST_CONFIDENCE_CAP, 0.0)

    def test_cap_shrinks_a_high_conviction_position(self):
        uncapped = self._buy(0.9)
        with mock.patch.object(config, "HIST_CONFIDENCE_CAP", 0.45):
            capped = self.agent._generate_signal(
                "AAPL", seasonal_score=0.9, channel_score=0.9, momentum_score=0.9,
                volume_score=0.0, reasons=[], prices=self.prices, df=self.bars)
        self.assertEqual(uncapped.action, "BUY")
        self.assertEqual(capped.action, "BUY")
        self.assertLess(capped.shares, uncapped.shares)

    def test_cap_leaves_positions_below_the_cap_untouched(self):
        uncapped = self._buy(0.30)
        with mock.patch.object(config, "HIST_CONFIDENCE_CAP", 0.45):
            capped = self.agent._generate_signal(
                "AAPL", seasonal_score=0.30, channel_score=0.30, momentum_score=0.30,
                volume_score=0.0, reasons=[], prices=self.prices, df=self.bars)
        self.assertEqual(capped.shares, uncapped.shares)

    def test_reported_confidence_is_not_capped(self):
        """The cap governs sizing only — the signal must still report true conviction."""
        with mock.patch.object(config, "HIST_CONFIDENCE_CAP", 0.45):
            signal = self._buy(0.9)
        self.assertGreater(signal.confidence, 0.45)

if __name__ == "__main__":
    unittest.main()
