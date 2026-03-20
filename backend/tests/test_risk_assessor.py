"""
Unit tests for data/risk_assessor.py
Covers: churn detection, regime accuracy tracking, assessment context.
"""
import sys
import os
import unittest
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import data.risk_assessor as ra
from data.risk_assessor import (
    record_trade, record_regime, assess_churn, assess_regime_accuracy,
    get_assessment_context, update_regime_outcomes,
)


class RiskAssessorTestBase(unittest.TestCase):
    def setUp(self):
        self.tmpfile = tempfile.mktemp(suffix=".json")
        self.patcher = patch.object(ra, "ASSESSMENT_FILE", self.tmpfile)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        if os.path.exists(self.tmpfile):
            os.remove(self.tmpfile)


class TestRecordTrade(RiskAssessorTestBase):

    def test_trade_stored_in_log(self):
        record_trade("MomentumAgent", "MU", "BUY")
        d = ra._get_data()
        self.assertIn("MomentumAgent:MU", d["trade_log"])
        self.assertEqual(len(d["trade_log"]["MomentumAgent:MU"]), 1)

    def test_multiple_trades_accumulated(self):
        record_trade("MomentumAgent", "MU", "BUY")
        record_trade("MomentumAgent", "MU", "SELL")
        record_trade("MomentumAgent", "MU", "BUY")
        d = ra._get_data()
        self.assertEqual(len(d["trade_log"]["MomentumAgent:MU"]), 3)


class TestAssessChurn(RiskAssessorTestBase):

    def test_churn_detected_at_threshold(self):
        for action in ["BUY", "SELL", "BUY"]:
            record_trade("MomentumAgent", "MU", action)
        issues = assess_churn(window_minutes=60)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["agent"], "MomentumAgent")
        self.assertEqual(issues[0]["symbol"], "MU")

    def test_churn_not_detected_below_threshold(self):
        record_trade("MomentumAgent", "MU", "BUY")
        record_trade("MomentumAgent", "MU", "SELL")
        issues = assess_churn(window_minutes=60)
        self.assertEqual(len(issues), 0)

    def test_old_trades_excluded_from_window(self):
        for action in ["BUY", "SELL", "BUY"]:
            record_trade("MomentumAgent", "MU", action)
        # Backdate 2 entries
        d = ra._get_data()
        old_ts = (datetime.utcnow() - timedelta(hours=2)).isoformat()
        d["trade_log"]["MomentumAgent:MU"][0]["timestamp"] = old_ts
        d["trade_log"]["MomentumAgent:MU"][1]["timestamp"] = old_ts
        ra._save(d)
        issues = assess_churn(window_minutes=60)
        self.assertEqual(len(issues), 0)

    def test_different_agents_assessed_independently(self):
        for action in ["BUY", "SELL", "BUY"]:
            record_trade("ClaudeAgent", "AAPL", action)
        issues = assess_churn(window_minutes=60)
        self.assertEqual(issues[0]["agent"], "ClaudeAgent")
        self.assertEqual(issues[0]["symbol"], "AAPL")


class TestRegimeAccuracy(RiskAssessorTestBase):

    def test_false_trending_call_detected(self):
        record_regime("trending", {"SPY": 450.0})
        d = ra._get_data()
        d["regime_log"][0]["outcome_pct"] = -3.5
        ra._save(d)
        issues = assess_regime_accuracy()
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "false_trending")

    def test_correct_trending_not_flagged(self):
        record_regime("trending", {"SPY": 450.0})
        d = ra._get_data()
        d["regime_log"][0]["outcome_pct"] = 2.5
        ra._save(d)
        issues = assess_regime_accuracy()
        self.assertEqual(len(issues), 0)

    def test_ranging_call_never_flagged(self):
        record_regime("ranging", {"SPY": 450.0})
        d = ra._get_data()
        d["regime_log"][0]["outcome_pct"] = -5.0
        ra._save(d)
        issues = assess_regime_accuracy()
        self.assertEqual(len(issues), 0)


class TestAssessmentContext(RiskAssessorTestBase):

    def test_empty_context_when_no_issues(self):
        ctx = get_assessment_context()
        self.assertEqual(ctx, "")

    def test_churn_appears_in_context(self):
        for action in ["BUY", "SELL", "BUY"]:
            record_trade("MomentumAgent", "MU", action)
        ctx = get_assessment_context()
        self.assertIn("MU", ctx)
        self.assertIn("MomentumAgent", ctx)

    def test_false_trending_appears_in_context(self):
        record_regime("trending", {"SPY": 450.0})
        d = ra._get_data()
        d["regime_log"][0]["outcome_pct"] = -4.0
        ra._save(d)
        ctx = get_assessment_context()
        self.assertIn("TRENDING", ctx.upper())


if __name__ == "__main__":
    unittest.main()
