"""
Unit tests for:
  - agents/base_agent.py :: Signal.is_actionable()
  - data/drift_detector.py :: win_rate, avg_pnl_pct, drift detection logic
"""
import sys
import os
import unittest
from datetime import datetime

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agents.base_agent import Signal
from trading.portfolio import TradeRecord
from data import drift_detector
from data.drift_detector import (
    DriftReport, check_drift, _win_rate, _avg_pnl_pct,
    WIN_RATE_DROP_THRESHOLD, AVG_PNL_DROP_THRESHOLD,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_sell(price, pnl, shares=10):
    return TradeRecord(
        symbol="TEST", action="SELL",
        shares=shares, price=price,
        timestamp=datetime.utcnow(), pnl=pnl,
    )


def _make_buy(price, shares=10):
    return TradeRecord(
        symbol="TEST", action="BUY",
        shares=shares, price=price,
        timestamp=datetime.utcnow(),
    )


class MockPortfolio:
    def __init__(self, trades):
        self.trade_history = trades


class MockAgent:
    def __init__(self, name, trades):
        self.name = name
        self.portfolio = MockPortfolio(trades)


# ── Signal.is_actionable tests ───────────────────────────────────────────────

class TestSignalIsActionable(unittest.TestCase):

    def test_buy_with_shares_and_confidence_is_actionable(self):
        s = Signal(action="BUY", symbol="AAPL", confidence=0.8, shares=10.0, reasoning="")
        self.assertTrue(s.is_actionable())

    def test_sell_with_shares_and_confidence_is_actionable(self):
        s = Signal(action="SELL", symbol="AAPL", confidence=0.7, shares=5.0, reasoning="")
        self.assertTrue(s.is_actionable())

    def test_hold_is_not_actionable(self):
        s = Signal(action="HOLD", symbol="AAPL", confidence=0.5, shares=0, reasoning="")
        self.assertFalse(s.is_actionable())

    def test_buy_zero_shares_not_actionable(self):
        s = Signal(action="BUY", symbol="AAPL", confidence=0.8, shares=0, reasoning="")
        self.assertFalse(s.is_actionable())

    def test_buy_zero_confidence_not_actionable(self):
        s = Signal(action="BUY", symbol="AAPL", confidence=0.0, shares=10.0, reasoning="")
        self.assertFalse(s.is_actionable())

    def test_sell_zero_shares_not_actionable(self):
        s = Signal(action="SELL", symbol="AAPL", confidence=0.8, shares=0, reasoning="")
        self.assertFalse(s.is_actionable())


# ── _win_rate tests ──────────────────────────────────────────────────────────

class TestWinRate(unittest.TestCase):

    def test_empty_list_returns_zero(self):
        self.assertEqual(_win_rate([]), 0.0)

    def test_all_winners(self):
        trades = [_make_sell(110, 100) for _ in range(5)]  # pnl > 0
        self.assertAlmostEqual(_win_rate(trades), 100.0)

    def test_all_losers(self):
        trades = [_make_sell(90, -100) for _ in range(5)]  # pnl < 0
        self.assertAlmostEqual(_win_rate(trades), 0.0)

    def test_mixed_50_50(self):
        trades = [_make_sell(110, 100), _make_sell(90, -100)]
        self.assertAlmostEqual(_win_rate(trades), 50.0)


# ── _avg_pnl_pct tests ───────────────────────────────────────────────────────

class TestAvgPnlPct(unittest.TestCase):

    def test_empty_list_returns_zero(self):
        self.assertEqual(_avg_pnl_pct([]), 0.0)

    def test_correct_pct_calculation(self):
        # sell_price=110, pnl=100, shares=10 → buy_price = 110 - 100/10 = 100
        # pnl_pct = 100 / (100 * 10) * 100 = 10%
        trade = _make_sell(price=110, pnl=100, shares=10)
        result = _avg_pnl_pct([trade])
        self.assertAlmostEqual(result, 10.0, places=1)

    def test_negative_pnl(self):
        # sell_price=90, pnl=-100, shares=10 → buy_price = 90 - (-100/10) = 100
        # pnl_pct = -100 / (100*10) * 100 = -10%
        trade = _make_sell(price=90, pnl=-100, shares=10)
        result = _avg_pnl_pct([trade])
        self.assertAlmostEqual(result, -10.0, places=1)


# ── check_drift tests ────────────────────────────────────────────────────────

class TestCheckDrift(unittest.TestCase):

    def test_not_enough_trades_no_drift(self):
        agent = MockAgent("TestAgent", [_make_buy(100), _make_sell(110, 100)])
        report = check_drift(agent)
        self.assertFalse(report.is_drifting)
        self.assertEqual(len(report.alerts), 1)
        self.assertIn("Not enough trades", report.alerts[0])

    def test_no_drift_when_consistent(self):
        # 10 winning trades — no drift
        sells = [_make_sell(110, 100) for _ in range(10)]
        agent = MockAgent("TestAgent", sells)
        report = check_drift(agent)
        self.assertFalse(report.is_drifting)

    def test_win_rate_drift_detected(self):
        # First 5 trades: 100% win rate (baseline)
        # Last 10 trades (recent): 0% win rate → big drop
        good = [_make_sell(110, 100) for _ in range(5)]
        bad  = [_make_sell(90, -100) for _ in range(10)]
        agent = MockAgent("TestAgent", good + bad)
        report = check_drift(agent)
        self.assertTrue(report.is_drifting)
        self.assertTrue(any("Win rate" in a for a in report.alerts))

    def test_avg_pnl_drift_detected(self):
        # All winners but recent trades have near-zero gains
        good = [_make_sell(200, 1000, shares=10) for _ in range(5)]   # big profits
        weak = [_make_sell(110, 1, shares=10) for _ in range(10)]     # tiny profits
        agent = MockAgent("TestAgent", good + weak)
        report = check_drift(agent)
        self.assertTrue(report.is_drifting)
        self.assertTrue(any("PnL" in a for a in report.alerts))

    def test_report_dict_has_expected_keys(self):
        sells = [_make_sell(110, 100) for _ in range(10)]
        agent = MockAgent("TestAgent", sells)
        d = check_drift(agent).to_dict()
        for key in ("agent_name", "is_drifting", "alerts", "baseline_win_rate",
                    "recent_win_rate", "total_trades"):
            self.assertIn(key, d)

    def test_report_agent_name(self):
        sells = [_make_sell(110, 100) for _ in range(10)]
        agent = MockAgent("MyAgent", sells)
        report = check_drift(agent)
        self.assertEqual(report.agent_name, "MyAgent")


# ── _last_signals pruning tests ──────────────────────────────────────────────

import asyncio
from unittest.mock import patch


class _StubAgent:
    """Minimal concrete stand-in that exercises BaseAgent.run_cycle pruning."""

    def __init__(self, signals_to_return):
        from agents.base_agent import BaseAgent, Signal
        from config import config

        class _Concrete(BaseAgent):
            def __init__(self, sigs):
                self._sigs = sigs
                with patch("agents.base_agent.BaseAgent._load_picks"):
                    super().__init__("StubAgent", "stub")

            async def analyze(self, market_context):
                return self._sigs

        self._agent = _Concrete(signals_to_return)

    @property
    def agent(self):
        return self._agent


class TestLastSignalsPruning(unittest.IsolatedAsyncioTestCase):

    def _make_signal(self, symbol, action="HOLD"):
        return Signal(action=action, symbol=symbol, confidence=0.5, shares=0, reasoning="")

    def _make_ctx(self, *symbols):
        return {sym: {"price": 100.0, "bars": None, "news": []} for sym in symbols}

    async def test_stale_symbol_pruned_from_last_signals(self):
        """Symbol removed from market_context must be pruned from _last_signals."""
        from agents.base_agent import Signal

        sig_aapl = self._make_signal("AAPL")
        stub = _StubAgent([sig_aapl])
        agent = stub.agent

        # Seed stale entry for MSFT
        agent._last_signals["MSFT"] = self._make_signal("MSFT")

        ctx = self._make_ctx("AAPL")
        prices = {"AAPL": 100.0}

        with patch.object(agent, "_execute_signal", return_value=False), \
             patch.object(agent.portfolio, "reset_daily_tracking"), \
             patch.object(agent.portfolio, "record_value"), \
             patch.object(agent.risk_manager, "check_daily_loss", return_value=True), \
             patch.object(agent, "_save_picks"):
            await agent.run_cycle(ctx, prices)

        self.assertNotIn("MSFT", agent._last_signals)
        self.assertIn("AAPL", agent._last_signals)

    async def test_current_symbol_kept_in_last_signals(self):
        """Symbols still in market_context must remain in _last_signals."""
        from agents.base_agent import Signal

        sigs = [self._make_signal("AAPL"), self._make_signal("GOOG")]
        stub = _StubAgent(sigs)
        agent = stub.agent

        ctx = self._make_ctx("AAPL", "GOOG")
        prices = {"AAPL": 100.0, "GOOG": 200.0}

        with patch.object(agent, "_execute_signal", return_value=False), \
             patch.object(agent.portfolio, "reset_daily_tracking"), \
             patch.object(agent.portfolio, "record_value"), \
             patch.object(agent.risk_manager, "check_daily_loss", return_value=True), \
             patch.object(agent, "_save_picks"):
            await agent.run_cycle(ctx, prices)

        self.assertIn("AAPL", agent._last_signals)
        self.assertIn("GOOG", agent._last_signals)

    async def test_non_dict_context_values_excluded_from_current_symbols(self):
        """__overnight_catalysts__ (list) must not count as a current symbol."""
        from agents.base_agent import Signal

        sig_aapl = self._make_signal("AAPL")
        stub = _StubAgent([sig_aapl])
        agent = stub.agent

        ctx = {
            "AAPL": {"price": 100.0, "bars": None, "news": []},
            "__overnight_catalysts__": [{"headline": "big news"}],
        }
        prices = {"AAPL": 100.0}
        # Seed stale MSFT entry
        agent._last_signals["MSFT"] = self._make_signal("MSFT")

        with patch.object(agent, "_execute_signal", return_value=False), \
             patch.object(agent.portfolio, "reset_daily_tracking"), \
             patch.object(agent.portfolio, "record_value"), \
             patch.object(agent.risk_manager, "check_daily_loss", return_value=True), \
             patch.object(agent, "_save_picks"):
            await agent.run_cycle(ctx, prices)

        self.assertNotIn("MSFT", agent._last_signals)
        self.assertIn("AAPL", agent._last_signals)


class TestCheckHourlyRateLimit(unittest.TestCase):
    """BaseAgent._check_hourly_rate_limit enforces the sliding-window call cap."""

    def _make_agent(self):
        from unittest.mock import patch
        from agents.base_agent import BaseAgent

        class _Stub(BaseAgent):
            def __init__(self):
                with patch("agents.base_agent.BaseAgent._load_picks"):
                    super().__init__("StubAgent", "stub")
            async def analyze(self, ctx):
                return []

        return _Stub()

    def test_under_limit_returns_true(self):
        agent = self._make_agent()
        self.assertTrue(agent._check_hourly_rate_limit(2))

    def test_at_limit_returns_false(self):
        import time
        agent = self._make_agent()
        now = time.time()
        agent._call_timestamps = [now - 100, now - 200]   # 2 recent calls
        self.assertFalse(agent._check_hourly_rate_limit(2))

    def test_expired_timestamps_not_counted(self):
        import time
        agent = self._make_agent()
        agent._call_timestamps = [time.time() - 7200, time.time() - 3700]  # both > 1h old
        self.assertTrue(agent._check_hourly_rate_limit(2))

    def test_mixed_fresh_and_expired(self):
        import time
        agent = self._make_agent()
        # 1 expired, 1 fresh — under limit of 2
        agent._call_timestamps = [time.time() - 7200, time.time() - 60]
        self.assertTrue(agent._check_hourly_rate_limit(2))


class TestBayesEarlyExit(unittest.IsolatedAsyncioTestCase):
    """BaseAgent._check_bayes_exits sells positions whose bayes_confidence
    has dropped far enough below entry_confidence."""

    def _make_agent_with_position(self, entry_conf=0.75, bayes_conf=0.75):
        from agents.base_agent import BaseAgent as _BaseAgent

        class _StubAgent(_BaseAgent):
            async def analyze(self, ctx):
                return []

        agent = _StubAgent("TestAgent", "stub")
        agent.portfolio.execute_buy("AAPL", 10, 100.0, entry_confidence=entry_conf)
        # Override bayes_confidence directly to simulate drift
        agent.portfolio.positions["AAPL"].bayes_confidence = bayes_conf
        return agent

    async def test_no_exit_when_confidence_stable(self):
        """Entry=0.75, bayes=0.72 — drop < threshold → no exit."""
        agent = self._make_agent_with_position(entry_conf=0.75, bayes_conf=0.72)
        prices = {"AAPL": 105.0}
        exits = await agent._check_bayes_exits(prices)
        self.assertEqual(exits, [])
        self.assertIn("AAPL", agent.portfolio.positions)

    async def test_exit_triggered_when_confidence_drops(self):
        """Entry=0.75, bayes=0.40 — drop > 0.30 threshold → exit fired."""
        agent = self._make_agent_with_position(entry_conf=0.75, bayes_conf=0.40)
        prices = {"AAPL": 95.0}
        exits = await agent._check_bayes_exits(prices)
        self.assertEqual(len(exits), 1)
        self.assertEqual(exits[0].symbol, "AAPL")
        self.assertEqual(exits[0].action, "SELL")
        self.assertNotIn("AAPL", agent.portfolio.positions)

    async def test_exit_reason_mentions_bayes(self):
        """Sell reasoning must mention Bayesian confidence values."""
        agent = self._make_agent_with_position(entry_conf=0.80, bayes_conf=0.35)
        prices = {"AAPL": 90.0}
        exits = await agent._check_bayes_exits(prices)
        self.assertGreater(len(exits), 0)
        self.assertIn("bayes", exits[0].reasoning.lower())

    async def test_no_exit_without_price(self):
        """No price available → skip the position gracefully."""
        agent = self._make_agent_with_position(entry_conf=0.75, bayes_conf=0.30)
        exits = await agent._check_bayes_exits({})   # empty prices
        self.assertEqual(exits, [])
        self.assertIn("AAPL", agent.portfolio.positions)

    async def test_no_exit_when_no_positions(self):
        from agents.base_agent import BaseAgent as _BaseAgent

        class _StubAgent(_BaseAgent):
            async def analyze(self, ctx):
                return []

        agent = _StubAgent("TestAgent", "stub")
        exits = await agent._check_bayes_exits({"AAPL": 100.0})
        self.assertEqual(exits, [])

    async def test_bayes_exits_called_in_run_cycle(self):
        """run_cycle must call _check_bayes_exits each cycle."""
        from unittest.mock import AsyncMock, patch
        from agents.base_agent import BaseAgent as _BaseAgent

        class _StubAgent(_BaseAgent):
            async def analyze(self, ctx):
                return []

        agent = _StubAgent("TestAgent", "stub")
        prices = {"AAPL": 100.0}
        ctx = {"AAPL": {"price": 100.0, "bars": None, "stats": {}, "news": []}}

        with patch.object(agent, "_check_bayes_exits", new=AsyncMock(return_value=[])) as mock_bayes, \
             patch.object(agent, "_check_trailing_stops", new=AsyncMock(return_value=[])), \
             patch.object(agent.portfolio, "record_value"), \
             patch.object(agent.portfolio, "reset_daily_tracking"), \
             patch.object(agent.risk_manager, "check_daily_loss", return_value=True), \
             patch.object(agent, "_save_picks"):
            await agent.run_cycle(ctx, prices)

        mock_bayes.assert_called_once_with(prices)


class TestTrailingStopExit(unittest.IsolatedAsyncioTestCase):
    """BaseAgent._check_trailing_stops sells positions that have given back
    >= TRAIL_GIVEBACK_PCT of their peak unrealized profit."""

    def _make_agent_with_position(self, shares=10, entry_price=100.0):
        from agents.base_agent import BaseAgent as _BaseAgent

        class _StubAgent(_BaseAgent):
            async def analyze(self, ctx):
                return []

        agent = _StubAgent("TestAgent", "stub")
        agent.portfolio.execute_buy("AAPL", shares, entry_price)
        return agent

    async def test_no_exit_when_peak_below_arm_threshold(self):
        """Tiny peak ($10) below TRAIL_ARM_USD ($25) → trailing not armed."""
        agent = self._make_agent_with_position(shares=10, entry_price=100.0)
        # Push price up briefly: peak = 10 × $1 = $10 (below $25 arm)
        agent.portfolio.record_value({"AAPL": 101.0})
        # Drop back hard
        exits = await agent._check_trailing_stops({"AAPL": 95.0})
        self.assertEqual(exits, [])
        self.assertIn("AAPL", agent.portfolio.positions)

    async def test_no_exit_when_giveback_below_threshold(self):
        """Peak $300, current $250 — gave back $50 = 17% < 20% threshold → hold."""
        agent = self._make_agent_with_position(shares=10, entry_price=100.0)
        agent.portfolio.record_value({"AAPL": 130.0})  # peak = $300
        exits = await agent._check_trailing_stops({"AAPL": 125.0})  # gave back $50
        self.assertEqual(exits, [])
        self.assertIn("AAPL", agent.portfolio.positions)

    async def test_exit_when_giveback_meets_threshold(self):
        """Peak $300, current $240 — gave back $60 = 20% = threshold → SELL."""
        agent = self._make_agent_with_position(shares=10, entry_price=100.0)
        agent.portfolio.record_value({"AAPL": 130.0})  # peak = $300
        exits = await agent._check_trailing_stops({"AAPL": 124.0})  # gave back $60
        self.assertEqual(len(exits), 1)
        self.assertEqual(exits[0].symbol, "AAPL")
        self.assertEqual(exits[0].action, "SELL")
        self.assertNotIn("AAPL", agent.portfolio.positions)

    async def test_exit_reasoning_mentions_trail_amounts(self):
        agent = self._make_agent_with_position(shares=10, entry_price=100.0)
        agent.portfolio.record_value({"AAPL": 140.0})  # peak = $400
        exits = await agent._check_trailing_stops({"AAPL": 110.0})  # gave back $300
        self.assertGreater(len(exits), 0)
        self.assertIn("Trailing stop", exits[0].reasoning)
        self.assertIn("peak", exits[0].reasoning.lower())

    async def test_exit_when_position_drops_below_entry(self):
        """ASML-like scenario: peak +$1000, now −$500 → 100%+ giveback → SELL."""
        agent = self._make_agent_with_position(shares=10, entry_price=1000.0)
        agent.portfolio.record_value({"AAPL": 1100.0})  # peak = +$1000
        exits = await agent._check_trailing_stops({"AAPL": 950.0})  # now −$500
        self.assertEqual(len(exits), 1)
        self.assertEqual(exits[0].action, "SELL")

    async def test_no_exit_when_position_never_armed(self):
        """Position is underwater the entire time — never armed → never exits."""
        agent = self._make_agent_with_position(shares=10, entry_price=100.0)
        agent.portfolio.record_value({"AAPL": 90.0})
        exits = await agent._check_trailing_stops({"AAPL": 85.0})
        self.assertEqual(exits, [])
        self.assertIn("AAPL", agent.portfolio.positions)

    async def test_no_exit_without_price(self):
        agent = self._make_agent_with_position()
        agent.portfolio.record_value({"AAPL": 200.0})  # arm with high peak
        exits = await agent._check_trailing_stops({})  # no price available
        self.assertEqual(exits, [])

    async def test_trailing_called_in_run_cycle(self):
        """run_cycle must call _check_trailing_stops each cycle."""
        from unittest.mock import AsyncMock, patch
        from agents.base_agent import BaseAgent as _BaseAgent

        class _StubAgent(_BaseAgent):
            async def analyze(self, ctx):
                return []

        agent = _StubAgent("TestAgent", "stub")
        prices = {"AAPL": 100.0}
        ctx = {"AAPL": {"price": 100.0, "bars": None, "stats": {}, "news": []}}

        with patch.object(agent, "_check_bayes_exits", new=AsyncMock(return_value=[])), \
             patch.object(agent, "_check_trailing_stops", new=AsyncMock(return_value=[])) as mock_trail, \
             patch.object(agent, "_check_hard_stops", new=AsyncMock(return_value=[])), \
             patch.object(agent.portfolio, "record_value"), \
             patch.object(agent.portfolio, "reset_daily_tracking"), \
             patch.object(agent.risk_manager, "check_daily_loss", return_value=True), \
             patch.object(agent, "_save_picks"):
            await agent.run_cycle(ctx, prices)

        mock_trail.assert_called_once_with(prices)


class TestHardStopExit(unittest.IsolatedAsyncioTestCase):
    """BaseAgent._check_hard_stops sells positions that have dropped
    HARD_STOP_PCT or more from entry — defensive floor."""

    def _make_agent(self):
        from agents.base_agent import BaseAgent as _BaseAgent

        class _StubAgent(_BaseAgent):
            async def analyze(self, ctx):
                return []

        return _StubAgent("TestAgent", "stub")

    async def test_no_exit_above_threshold(self):
        """Position down 5% — below 8% threshold → hold."""
        agent = self._make_agent()
        agent.portfolio.execute_buy("AAPL", 10, 100.0)
        exits = await agent._check_hard_stops({"AAPL": 95.0})  # -5%
        self.assertEqual(exits, [])
        self.assertIn("AAPL", agent.portfolio.positions)

    async def test_exit_at_threshold(self):
        """Position down exactly 8% (threshold) → SELL."""
        agent = self._make_agent()
        agent.portfolio.execute_buy("AAPL", 10, 100.0)
        exits = await agent._check_hard_stops({"AAPL": 92.0})  # -8%
        self.assertEqual(len(exits), 1)
        self.assertEqual(exits[0].action, "SELL")
        self.assertNotIn("AAPL", agent.portfolio.positions)

    async def test_exit_far_below_threshold(self):
        """Position down 20% → SELL."""
        agent = self._make_agent()
        agent.portfolio.execute_buy("AAPL", 10, 100.0)
        exits = await agent._check_hard_stops({"AAPL": 80.0})  # -20%
        self.assertEqual(len(exits), 1)

    async def test_no_exit_for_profitable_position(self):
        """Position up 10% — never triggers hard stop."""
        agent = self._make_agent()
        agent.portfolio.execute_buy("AAPL", 10, 100.0)
        exits = await agent._check_hard_stops({"AAPL": 110.0})
        self.assertEqual(exits, [])

    async def test_reasoning_mentions_drawdown(self):
        agent = self._make_agent()
        agent.portfolio.execute_buy("AAPL", 10, 100.0)
        exits = await agent._check_hard_stops({"AAPL": 85.0})
        self.assertGreater(len(exits), 0)
        self.assertIn("Hard stop", exits[0].reasoning)
        self.assertIn("entry", exits[0].reasoning)

    async def test_disabled_when_threshold_zero(self):
        """HARD_STOP_PCT=0 disables the gate entirely."""
        from unittest.mock import patch
        agent = self._make_agent()
        agent.portfolio.execute_buy("AAPL", 10, 100.0)
        with patch("config.config.HARD_STOP_PCT", 0.0):
            exits = await agent._check_hard_stops({"AAPL": 50.0})  # -50%
        self.assertEqual(exits, [])
        self.assertIn("AAPL", agent.portfolio.positions)

    async def test_no_exit_without_price(self):
        agent = self._make_agent()
        agent.portfolio.execute_buy("AAPL", 10, 100.0)
        exits = await agent._check_hard_stops({})
        self.assertEqual(exits, [])

    async def test_hard_stop_called_in_run_cycle(self):
        """run_cycle must call _check_hard_stops each cycle."""
        from unittest.mock import AsyncMock, patch
        from agents.base_agent import BaseAgent as _BaseAgent

        class _StubAgent(_BaseAgent):
            async def analyze(self, ctx):
                return []

        agent = _StubAgent("TestAgent", "stub")
        prices = {"AAPL": 100.0}
        ctx = {"AAPL": {"price": 100.0, "bars": None, "stats": {}, "news": []}}

        with patch.object(agent, "_check_bayes_exits", new=AsyncMock(return_value=[])), \
             patch.object(agent, "_check_trailing_stops", new=AsyncMock(return_value=[])), \
             patch.object(agent, "_check_hard_stops", new=AsyncMock(return_value=[])) as mock_hard, \
             patch.object(agent.portfolio, "record_value"), \
             patch.object(agent.portfolio, "reset_daily_tracking"), \
             patch.object(agent.risk_manager, "check_daily_loss", return_value=True), \
             patch.object(agent, "_save_picks"):
            await agent.run_cycle(ctx, prices)

        mock_hard.assert_called_once_with(prices)

    async def test_hard_stop_runs_after_agent_signals(self):
        """Hard stop is a FALLBACK — must run AFTER agent signals execute,
        so the agent's primary decision (e.g., averaging down) gets a chance
        to lower avg_cost out of the danger zone before the mechanical floor
        fires. This is the order contract that makes the hard stop a safety
        net, not a primary trigger."""
        from unittest.mock import AsyncMock, patch
        from agents.base_agent import BaseAgent as _BaseAgent
        from agents.base_agent import Signal as _Signal

        order_log = []

        class _StubAgent(_BaseAgent):
            async def analyze(self, ctx):
                # Simulate the agent's primary decision arriving as a signal.
                # The signal is non-actionable here (HOLD) so we don't need
                # to fully exercise the executor; we just record that the
                # analyze step was reached.
                order_log.append("analyze")
                return [_Signal(action="HOLD", symbol="AAPL", confidence=0.5,
                                shares=0, reasoning="primary decision")]

        agent = _StubAgent("TestAgent", "stub")
        prices = {"AAPL": 100.0}
        ctx = {"AAPL": {"price": 100.0, "bars": None, "stats": {}, "news": []}}

        async def _hard_stop_marker(_):
            order_log.append("hard_stop")
            return []

        with patch.object(agent, "_check_bayes_exits", new=AsyncMock(return_value=[])), \
             patch.object(agent, "_check_trailing_stops", new=AsyncMock(return_value=[])), \
             patch.object(agent, "_check_hard_stops", side_effect=_hard_stop_marker), \
             patch.object(agent.portfolio, "record_value"), \
             patch.object(agent.portfolio, "reset_daily_tracking"), \
             patch.object(agent.risk_manager, "check_daily_loss", return_value=True), \
             patch.object(agent, "_save_picks"):
            await agent.run_cycle(ctx, prices)

        # The contract: analyze must precede hard_stop in the call order.
        self.assertIn("analyze", order_log)
        self.assertIn("hard_stop", order_log)
        self.assertLess(
            order_log.index("analyze"),
            order_log.index("hard_stop"),
            "hard stop must run AFTER agent signals (primary decision); current order: " + str(order_log),
        )


if __name__ == "__main__":
    unittest.main()
