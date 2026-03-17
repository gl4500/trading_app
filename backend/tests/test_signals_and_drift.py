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


if __name__ == "__main__":
    unittest.main()
