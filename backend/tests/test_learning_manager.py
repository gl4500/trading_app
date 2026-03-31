"""
Unit tests for data/learning_manager.py
Covers: record_trade(), get_learning_summary().
Each test class redirects LEARNING_FILE to a temporary path so the real
learning.json is never touched.
"""
import sys
import os
import json
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import data.learning_manager as lm


class LearningManagerBase(unittest.TestCase):
    """Redirect the learning file to a temp path before each test."""

    def setUp(self):
        fd, self.tmp_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.tmp_path)          # Remove so _load() sees "file not found"
        self._orig_path = lm.LEARNING_FILE
        lm.LEARNING_FILE = self.tmp_path

    def tearDown(self):
        lm.LEARNING_FILE = self._orig_path
        try:
            os.unlink(self.tmp_path)
        except OSError:
            pass


# ── record_trade tests ────────────────────────────────────────────────────────

class TestRecordTrade(LearningManagerBase):

    def _record(self, symbol="AAPL", buy=100.0, sell=110.0,
                pnl=1000.0, pnl_pct=10.0,
                buy_reason="Strong momentum", sell_reason="Target hit",
                agent="ClaudeAgent"):
        lm.record_trade(symbol, buy, sell, pnl, pnl_pct,
                        buy_reason, sell_reason, agent)

    def test_profitable_trade_saved_to_file(self):
        self._record(pnl=500.0, pnl_pct=5.0)
        with open(lm.LEARNING_FILE) as f:
            data = json.load(f)
        self.assertEqual(len(data["profitable_trades"]), 1)

    def test_loss_trade_saved_to_loss_list(self):
        self._record(pnl=-200.0, pnl_pct=-2.0)
        with open(lm.LEARNING_FILE) as f:
            data = json.load(f)
        self.assertEqual(len(data["loss_trades"]), 1)

    def test_profitable_trade_not_in_loss_list(self):
        self._record(pnl=500.0, pnl_pct=5.0)
        with open(lm.LEARNING_FILE) as f:
            data = json.load(f)
        self.assertEqual(len(data["loss_trades"]), 0)

    def test_entry_has_expected_fields(self):
        self._record()
        with open(lm.LEARNING_FILE) as f:
            data = json.load(f)
        entry = data["profitable_trades"][0]
        for field in ("symbol", "buy_price", "sell_price", "pnl",
                      "pnl_pct", "buy_reasoning", "sell_reasoning", "agent", "date"):
            self.assertIn(field, entry)

    def test_symbol_preserved(self):
        self._record(symbol="MSFT")
        with open(lm.LEARNING_FILE) as f:
            data = json.load(f)
        self.assertEqual(data["profitable_trades"][0]["symbol"], "MSFT")

    def test_profitable_trades_sorted_best_first(self):
        self._record(symbol="AAPL", pnl=100.0, pnl_pct=1.0)
        self._record(symbol="MSFT", pnl=500.0, pnl_pct=5.0)
        self._record(symbol="GOOGL", pnl=300.0, pnl_pct=3.0)
        with open(lm.LEARNING_FILE) as f:
            data = json.load(f)
        pcts = [t["pnl_pct"] for t in data["profitable_trades"]]
        self.assertEqual(pcts, sorted(pcts, reverse=True))

    def test_profitable_capped_at_max(self):
        for i in range(lm.MAX_PROFITABLE + 5):
            lm.record_trade(
                f"SYM{i}", 100.0, 110.0, float(i + 1), float(i + 1),
                "buy", "sell", "TestAgent"
            )
        with open(lm.LEARNING_FILE) as f:
            data = json.load(f)
        self.assertLessEqual(len(data["profitable_trades"]), lm.MAX_PROFITABLE)

    def test_losses_capped_at_max(self):
        for i in range(lm.MAX_LOSSES + 5):
            lm.record_trade(
                f"SYM{i}", 100.0, 90.0, float(-(i + 1)), float(-(i + 1)),
                "buy", "sell", "TestAgent"
            )
        with open(lm.LEARNING_FILE) as f:
            data = json.load(f)
        self.assertLessEqual(len(data["loss_trades"]), lm.MAX_LOSSES)

    def test_reasoning_truncated_at_300_chars(self):
        long_reason = "x" * 500
        self._record(buy_reason=long_reason)
        with open(lm.LEARNING_FILE) as f:
            data = json.load(f)
        self.assertLessEqual(len(data["profitable_trades"][0]["buy_reasoning"]), 300)


# ── get_learning_summary tests ────────────────────────────────────────────────

class TestGetLearningSummary(LearningManagerBase):

    def test_empty_file_returns_empty_string(self):
        result = lm.get_learning_summary()
        self.assertEqual(result, "")

    def test_profitable_trade_appears_in_summary(self):
        lm.record_trade("AAPL", 100.0, 120.0, 2000.0, 20.0, "Strong buy", "Exit", "Agent")
        result = lm.get_learning_summary()
        self.assertIn("AAPL", result)
        self.assertIn("20.0", result)

    def test_loss_trade_appears_in_summary(self):
        lm.record_trade("TSLA", 200.0, 180.0, -2000.0, -10.0, "FOMO buy", "Stop loss", "Agent")
        result = lm.get_learning_summary()
        self.assertIn("TSLA", result)

    def test_summary_has_section_headers(self):
        lm.record_trade("AAPL", 100.0, 110.0, 1000.0, 10.0, "buy", "sell", "Agent")
        result = lm.get_learning_summary()
        self.assertIn("What Worked", result)

    def test_summary_shows_loss_section_when_present(self):
        lm.record_trade("AAPL", 100.0, 80.0, -2000.0, -20.0, "wrong call", "cut loss", "Agent")
        result = lm.get_learning_summary()
        self.assertIn("Avoid", result)


# ── record_catalyst_outcome tests ────────────────────────────────────────────

class TestRecordCatalystOutcome(LearningManagerBase):

    def _record(self, symbol="AAPL", category="macro", score=3,
                headline="Fed cuts rates", change_open=1.2, change_1h=0.8,
                during_session=False, confirmed=True):
        lm.record_catalyst_outcome(
            symbol=symbol, category=category, score=score,
            headline=headline, change_open=change_open, change_1h=change_1h,
            during_session=during_session, confirmed=confirmed,
        )

    def test_outcome_saved_to_file(self):
        self._record()
        with open(lm.LEARNING_FILE) as f:
            data = json.load(f)
        self.assertEqual(len(data["catalyst_outcomes"]), 1)

    def test_entry_has_expected_fields(self):
        self._record()
        with open(lm.LEARNING_FILE) as f:
            entry = json.load(f)["catalyst_outcomes"][0]
        for field in ("symbol", "category", "score", "headline",
                      "change_open", "change_1h", "during_session",
                      "confirmed", "date"):
            self.assertIn(field, entry)

    def test_outcomes_capped_at_max(self):
        for i in range(lm.MAX_CATALYST_OUTCOMES + 5):
            self._record(symbol=f"SYM{i}")
        with open(lm.LEARNING_FILE) as f:
            data = json.load(f)
        self.assertLessEqual(len(data["catalyst_outcomes"]), lm.MAX_CATALYST_OUTCOMES)

    def test_most_recent_kept_when_capped(self):
        """When capped, the most recent entries are retained."""
        for i in range(lm.MAX_CATALYST_OUTCOMES + 3):
            self._record(symbol=f"SYM{i:03d}")
        with open(lm.LEARNING_FILE) as f:
            outcomes = json.load(f)["catalyst_outcomes"]
        symbols = [o["symbol"] for o in outcomes]
        # The last entry recorded should still be present
        self.assertIn(f"SYM{lm.MAX_CATALYST_OUTCOMES + 2:03d}", symbols)

    def test_flat_outcome_stored_as_not_confirmed(self):
        self._record(change_1h=0.01, confirmed=False)
        with open(lm.LEARNING_FILE) as f:
            entry = json.load(f)["catalyst_outcomes"][0]
        self.assertFalse(entry["confirmed"])

    def test_does_not_overwrite_trade_data(self):
        """record_catalyst_outcome must not disturb existing trade entries."""
        lm.record_trade("AAPL", 100.0, 110.0, 1000.0, 10.0, "buy", "sell", "Agent")
        self._record()
        with open(lm.LEARNING_FILE) as f:
            data = json.load(f)
        self.assertEqual(len(data["profitable_trades"]), 1)
        self.assertEqual(len(data["catalyst_outcomes"]), 1)


# ── get_catalyst_summary tests ────────────────────────────────────────────────

class TestGetCatalystSummary(LearningManagerBase):

    def test_empty_returns_empty_string(self):
        result = lm.get_catalyst_summary()
        self.assertEqual(result, "")

    def test_summary_contains_category(self):
        lm.record_catalyst_outcome("AAPL", "macro", 3, "Fed cuts rates",
                                   1.2, 0.8, False, True)
        result = lm.get_catalyst_summary()
        self.assertIn("MACRO", result)

    def test_summary_shows_confirmation_rate(self):
        # 2 confirmed, 1 not
        lm.record_catalyst_outcome("AAPL", "macro", 3, "H1", 1.0, 0.8, False, True)
        lm.record_catalyst_outcome("MSFT", "macro", 3, "H2", 0.5, 0.4, False, True)
        lm.record_catalyst_outcome("GOOGL", "macro", 2, "H3", 0.0, 0.0, False, False)
        result = lm.get_catalyst_summary()
        self.assertIn("67%", result)   # 2/3 confirmed = 66.7% → formatted as 67%

    def test_summary_included_in_get_learning_summary(self):
        lm.record_catalyst_outcome("AAPL", "catalyst", 3, "Earnings beat",
                                   2.0, 1.5, True, True)
        result = lm.get_learning_summary()
        self.assertIn("CATALYST", result)


if __name__ == "__main__":
    unittest.main()
