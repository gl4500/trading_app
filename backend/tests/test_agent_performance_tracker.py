"""
Unit tests for data/agent_performance_tracker.py
Covers: AgentPerformanceTracker.refresh, get_scores, consensus_score,
        agreement_fraction, top_agent, get_metrics_summary
"""
import asyncio
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import data.agent_performance_tracker as apt
from data.agent_performance_tracker import AgentPerformanceTracker, _DEFAULT_SCORE


class TestAgentPerformanceTrackerScores(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.tracker = AgentPerformanceTracker()

    async def test_get_scores_returns_default_when_no_db_data(self):
        """No DB data → all agents get _DEFAULT_SCORE."""
        with patch("data.agent_performance_tracker.aiosqlite") as mock_sql:
            mock_conn = AsyncMock()
            mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn.__aexit__ = AsyncMock(return_value=False)
            mock_cursor = AsyncMock()
            mock_cursor.fetchall = AsyncMock(return_value=[])
            mock_conn.execute = AsyncMock(return_value=mock_cursor)
            mock_sql.connect = MagicMock(return_value=mock_conn)

            scores = await self.tracker.get_scores()

        for name in apt._VOTER_AGENTS:
            self.assertIn(name, scores)
            self.assertEqual(scores[name], _DEFAULT_SCORE)

    async def test_get_scores_uses_win_rate_and_sharpe(self):
        """Agents with good win_rate and sharpe get scores above default."""
        self.tracker._metrics = {
            "ClaudeAgent": {
                "win_rate": 70.0,
                "sharpe_ratio": 1.5,
                "total_return_pct": 12.0,
                "trade_count": 50,
            }
        }
        self.tracker._scores = self.tracker._compute_scores(self.tracker._metrics)
        self.tracker._last_refresh = time.time()

        scores = await self.tracker.get_scores()
        self.assertGreater(scores.get("ClaudeAgent", 0), _DEFAULT_SCORE)

    async def test_get_scores_neutral_for_fewer_than_5_trades(self):
        """Agents with < 5 trades get neutral score regardless of win_rate."""
        self.tracker._metrics = {
            "TechAgent": {
                "win_rate": 95.0,
                "sharpe_ratio": 3.0,
                "total_return_pct": 50.0,
                "trade_count": 3,
            }
        }
        self.tracker._scores = self.tracker._compute_scores(self.tracker._metrics)
        self.tracker._last_refresh = time.time()

        scores = await self.tracker.get_scores()
        self.assertEqual(scores.get("TechAgent"), _DEFAULT_SCORE)

    async def test_scores_clamped_between_0_and_1(self):
        """Score is always in [0, 1] regardless of input extremes."""
        self.tracker._metrics = {
            "ClaudeAgent": {
                "win_rate": 200.0,   # invalid but should not crash
                "sharpe_ratio": 99.0,
                "total_return_pct": 999.0,
                "trade_count": 500,
            }
        }
        self.tracker._scores = self.tracker._compute_scores(self.tracker._metrics)
        self.tracker._last_refresh = time.time()

        scores = await self.tracker.get_scores()
        score = scores.get("ClaudeAgent", 0)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    async def test_cache_avoids_repeated_refresh(self):
        """Second call within REFRESH_INTERVAL does not re-query DB."""
        self.tracker._last_refresh = time.time()  # pretend just refreshed
        self.tracker._scores = {"ClaudeAgent": 0.77}

        with patch.object(self.tracker, "refresh", new_callable=AsyncMock) as mock_refresh:
            await self.tracker.get_scores()
            mock_refresh.assert_not_called()

    async def test_stale_cache_triggers_refresh(self):
        """Cache older than REFRESH_INTERVAL triggers a DB query."""
        self.tracker._last_refresh = time.time() - apt.REFRESH_INTERVAL - 1
        with patch.object(self.tracker, "refresh", new_callable=AsyncMock) as mock_refresh:
            await self.tracker.get_scores()
            mock_refresh.assert_called_once()


class TestConsensusScore(unittest.TestCase):

    def setUp(self):
        self.tracker = AgentPerformanceTracker()
        # Set known scores
        self.tracker._scores = {
            "ClaudeAgent":        0.70,
            "TechAgent":          0.60,
            "MomentumAgent":      0.50,
            "SentimentAgent":     0.40,
        }
        self.tracker._last_refresh = time.time()

    def test_all_buy_returns_positive(self):
        sigs = {
            "ClaudeAgent":    ("BUY", 0.8),
            "TechAgent":      ("BUY", 0.7),
            "MomentumAgent":  ("BUY", 0.6),
        }
        result = self.tracker.consensus_score(sigs)
        self.assertGreater(result, 0.0)

    def test_all_sell_returns_negative(self):
        sigs = {
            "ClaudeAgent":    ("SELL", 0.8),
            "TechAgent":      ("SELL", 0.7),
        }
        result = self.tracker.consensus_score(sigs)
        self.assertLess(result, 0.0)

    def test_all_hold_returns_zero(self):
        sigs = {
            "ClaudeAgent":    ("HOLD", 0.5),
            "TechAgent":      ("HOLD", 0.5),
        }
        result = self.tracker.consensus_score(sigs)
        self.assertAlmostEqual(result, 0.0, places=5)

    def test_high_scorer_buy_outweighs_low_scorer_sell(self):
        """ClaudeAgent (0.70) BUY should beat SentimentAgent (0.40) SELL."""
        sigs = {
            "ClaudeAgent":    ("BUY",  0.9),
            "SentimentAgent": ("SELL", 0.9),
        }
        result = self.tracker.consensus_score(sigs)
        self.assertGreater(result, 0.0)

    def test_result_clamped_to_minus1_to_plus1(self):
        sigs = {"ClaudeAgent": ("BUY", 1.0)}
        result = self.tracker.consensus_score(sigs)
        self.assertGreaterEqual(result, -1.0)
        self.assertLessEqual(result, 1.0)

    def test_empty_signals_returns_zero(self):
        result = self.tracker.consensus_score({})
        self.assertAlmostEqual(result, 0.0)


class TestAgreementFraction(unittest.TestCase):

    def setUp(self):
        self.tracker = AgentPerformanceTracker()

    def test_all_agree_buy_returns_one(self):
        sigs = {
            "ClaudeAgent":   ("BUY", 0.8),
            "TechAgent":     ("BUY", 0.7),
            "MomentumAgent": ("BUY", 0.6),
        }
        self.assertAlmostEqual(self.tracker.agreement_fraction(sigs), 1.0)

    def test_split_returns_fraction(self):
        sigs = {
            "ClaudeAgent":   ("BUY",  0.8),
            "TechAgent":     ("BUY",  0.7),
            "MomentumAgent": ("SELL", 0.6),
            "SentimentAgent":("SELL", 0.5),
        }
        result = self.tracker.agreement_fraction(sigs)
        self.assertAlmostEqual(result, 0.5)

    def test_empty_signals_returns_zero(self):
        self.assertAlmostEqual(self.tracker.agreement_fraction({}), 0.0)

    def test_three_way_split_returns_one_third(self):
        sigs = {
            "A": ("BUY",  0.8),
            "B": ("SELL", 0.7),
            "C": ("HOLD", 0.6),
        }
        result = self.tracker.agreement_fraction(sigs)
        self.assertAlmostEqual(result, 1.0 / 3.0, places=5)


class TestTopAgent(unittest.TestCase):

    def setUp(self):
        self.tracker = AgentPerformanceTracker()
        self.tracker._scores = {
            "ClaudeAgent":    0.70,
            "TechAgent":      0.60,
            "MomentumAgent":  0.50,
        }
        self.tracker._last_refresh = time.time()

    def test_returns_highest_scoring_non_hold_agent(self):
        sigs = {
            "ClaudeAgent":   ("BUY",  0.8),
            "TechAgent":     ("BUY",  0.7),
            "MomentumAgent": ("HOLD", 0.5),
        }
        name, action, conf = self.tracker.top_agent(sigs)
        self.assertEqual(name, "ClaudeAgent")
        self.assertEqual(action, "BUY")

    def test_returns_none_when_all_hold(self):
        sigs = {
            "ClaudeAgent": ("HOLD", 0.5),
            "TechAgent":   ("HOLD", 0.5),
        }
        result = self.tracker.top_agent(sigs)
        self.assertIsNone(result)

    def test_ignores_hold_prefers_sell_if_highest_score(self):
        self.tracker._scores["MomentumAgent"] = 0.90  # highest scorer says SELL
        sigs = {
            "ClaudeAgent":   ("BUY",  0.8),
            "MomentumAgent": ("SELL", 0.9),
        }
        name, action, _ = self.tracker.top_agent(sigs)
        self.assertEqual(name, "MomentumAgent")
        self.assertEqual(action, "SELL")

    def test_returns_none_for_empty_signals(self):
        result = self.tracker.top_agent({})
        self.assertIsNone(result)


class TestGetMetricsSummary(unittest.TestCase):

    def test_summary_contains_all_voter_agents(self):
        tracker = AgentPerformanceTracker()
        summary = tracker.get_metrics_summary()
        for name in apt._VOTER_AGENTS:
            self.assertIn(name, summary)

    def test_summary_keys_present(self):
        tracker = AgentPerformanceTracker()
        summary = tracker.get_metrics_summary()
        for name, info in summary.items():
            for key in ("win_rate", "sharpe_ratio", "trade_count", "score"):
                self.assertIn(key, info)


if __name__ == "__main__":
    unittest.main()
