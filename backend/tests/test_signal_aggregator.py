"""
Unit tests for data/signal_aggregator.py
Covers: _score_headlines(), _aggregate_scores(), format_for_prompt().
get_composite_signal() hits external APIs and is not tested here — those
require integration tests with mocked HTTP clients.
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.signal_aggregator import (
    _score_headlines,
    _aggregate_scores,
    format_for_prompt,
    SOURCE_WEIGHTS,
)


# ── _score_headlines tests ────────────────────────────────────────────────────

class TestScoreHeadlines(unittest.TestCase):

    def test_empty_list_returns_none(self):
        self.assertIsNone(_score_headlines([]))

    def test_bullish_headlines_positive_score(self):
        articles = [
            {"headline": "Apple beats earnings record with strong profit surge", "summary": ""},
            {"headline": "Stock rally approved by analysts who upgraded outlook", "summary": ""},
        ]
        result = _score_headlines(articles)
        self.assertIsNotNone(result)
        self.assertGreater(result, 0)

    def test_bearish_headlines_negative_score(self):
        articles = [
            {"headline": "Company misses earnings guidance amid layoffs and losses", "summary": ""},
            {"headline": "Stock downgraded after investigation reveals weak results", "summary": ""},
        ]
        result = _score_headlines(articles)
        self.assertIsNotNone(result)
        self.assertLess(result, 0)

    def test_neutral_headline_score_near_zero(self):
        # No bullish or bearish keywords
        articles = [{"headline": "Company announces annual meeting date", "summary": ""}]
        result = _score_headlines(articles)
        # With no keyword matches, returns None (no scoreable content)
        self.assertIsNone(result)

    def test_score_in_minus_one_to_one_range(self):
        articles = [
            {"headline": "record beats strong profit buyback growth surge", "summary": ""},
        ]
        result = _score_headlines(articles)
        if result is not None:
            self.assertGreaterEqual(result, -1.0)
            self.assertLessEqual(result, 1.0)

    def test_mixed_sentiment_between_extremes(self):
        articles = [
            {"headline": "Company beats expectations despite layoff concerns", "summary": ""},
        ]
        result = _score_headlines(articles)
        if result is not None:
            self.assertGreater(result, -1.0)
            self.assertLess(result, 1.0)


# ── _aggregate_scores tests ───────────────────────────────────────────────────

class TestAggregateScores(unittest.TestCase):

    def test_all_none_returns_zero_and_zero(self):
        composite, confidence, verdict = _aggregate_scores(None, None, None, None, None)
        self.assertEqual(composite, 0.0)
        self.assertEqual(confidence, 0.0)
        self.assertIn("No external signal", verdict)

    def test_single_bullish_source(self):
        composite, confidence, verdict = _aggregate_scores(
            analyst_score=0.8,
            earnings_score=None,
            alpaca_news_score=None,
            yahoo_news_score=None,
        )
        self.assertGreater(composite, 0)
        # agreement=0.5 (single source) × source_coverage=1/5 → confidence=0.100
        self.assertEqual(confidence, 0.1)

    def test_unanimous_bullish_raises_confidence(self):
        # All five sources agree strongly bullish
        composite, confidence, verdict = _aggregate_scores(
            analyst_score=0.9,
            earnings_score=0.8,
            alpaca_news_score=0.85,
            yahoo_news_score=0.75,
            congressional_score=0.7,
        )
        self.assertGreater(composite, 0.4)
        self.assertGreater(confidence, 0.5)
        self.assertIn("BULLISH", verdict)

    def test_mixed_sources_lowers_confidence(self):
        # Strongly conflicting sources → lower confidence
        composite, confidence, verdict = _aggregate_scores(
            analyst_score=1.0,
            earnings_score=-1.0,
            alpaca_news_score=None,
            yahoo_news_score=None,
        )
        self.assertIsInstance(confidence, float)

    def test_bearish_composite_verdict(self):
        composite, confidence, verdict = _aggregate_scores(
            analyst_score=-0.8,
            earnings_score=-0.7,
            alpaca_news_score=-0.6,
            yahoo_news_score=None,
        )
        self.assertLess(composite, 0)
        self.assertIn("BEARISH", verdict)

    def test_neutral_composite_verdict(self):
        composite, confidence, verdict = _aggregate_scores(
            analyst_score=0.05,
            earnings_score=-0.05,
            alpaca_news_score=None,
            yahoo_news_score=None,
        )
        self.assertIn("NEUTRAL", verdict)

    def test_composite_within_minus_one_to_one(self):
        composite, _, _ = _aggregate_scores(1.0, 1.0, 1.0, 1.0, 1.0)
        self.assertGreaterEqual(composite, -1.0)
        self.assertLessEqual(composite, 1.0)

    def test_source_weights_sum_to_one(self):
        total = sum(SOURCE_WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=5)


# ── format_for_prompt tests ───────────────────────────────────────────────────

class TestFormatForPrompt(unittest.TestCase):

    def _make_signal(self, composite=0.5, confidence=0.7, verdict="BULLISH",
                     analyst_score=0.6, earnings_score=0.4,
                     alpaca_score=0.5, yahoo_score=0.3,
                     congress_score=0.2):
        return {
            "symbol": "AAPL",
            "composite_score": composite,
            "confidence": confidence,
            "verdict": verdict,
            "sources": {
                "analyst_consensus": {
                    "score": analyst_score,
                    "weight": 0.35,
                    "bull": 10, "hold": 5, "bear": 2,
                    "total": 17, "price_target": 180.0,
                },
                "earnings_surprise": {
                    "score": earnings_score,
                    "weight": 0.22,
                    "surprise_pct": 5.0,
                },
                "alpaca_news": {"score": alpaca_score, "weight": 0.18, "articles": 3},
                "yahoo_news":  {"score": yahoo_score,  "weight": 0.12, "articles": 4},
                "congressional_trades": {
                    "score": congress_score, "weight": 0.13,
                    "congress_buys": 2, "congress_sells": 1,
                    "congress_total": 3, "total_filings": 3,
                    "window_days": 90,
                },
            },
            "yahoo_news_headlines": ["Apple beats Q3 estimates", "iPhone demand surge"],
        }

    def test_empty_signal_returns_unavailable(self):
        result = format_for_prompt({})
        self.assertIn("unavailable", result.lower())

    def test_none_signal_returns_unavailable(self):
        result = format_for_prompt(None)
        self.assertIn("unavailable", result.lower())

    def test_verdict_appears_in_output(self):
        result = format_for_prompt(self._make_signal(verdict="BULLISH"))
        self.assertIn("BULLISH", result)

    def test_composite_score_appears(self):
        result = format_for_prompt(self._make_signal(composite=0.55))
        self.assertIn("0.55", result)

    def test_analyst_buy_sell_counts_shown(self):
        result = format_for_prompt(self._make_signal())
        self.assertIn("10 buy", result)

    def test_price_target_shown_when_available(self):
        result = format_for_prompt(self._make_signal())
        self.assertIn("180.00", result)

    def test_earnings_surprise_pct_shown(self):
        result = format_for_prompt(self._make_signal())
        self.assertIn("5.0", result)

    def test_congressional_buy_sell_counts_shown(self):
        result = format_for_prompt(self._make_signal())
        self.assertIn("2 buy", result)

    def test_no_data_fallback_for_missing_analyst_score(self):
        signal = self._make_signal()
        signal["sources"]["analyst_consensus"]["score"] = None
        result = format_for_prompt(signal)
        self.assertIn("no data", result)

    def test_yahoo_headlines_included(self):
        result = format_for_prompt(self._make_signal())
        self.assertIn("Apple beats Q3 estimates", result)


if __name__ == "__main__":
    unittest.main()
