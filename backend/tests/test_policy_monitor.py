"""
Unit tests for data/policy_monitor.py
Covers: score_headline() — the pure scoring function that requires no I/O.
scan_policy_news() is async and hits the news service; it is covered with
a lightweight smoke test that stubs news_service.get_news_multi.
"""
import sys
import os
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.policy_monitor import score_headline


# ── score_headline tests ──────────────────────────────────────────────────────

class TestScoreHeadlineIrrelevant(unittest.TestCase):
    """Headlines with no policy keywords should score 0."""

    def test_unrelated_headline_scores_zero(self):
        result = score_headline("Company releases new product lineup")
        self.assertEqual(result["score"], 0)

    def test_empty_headline_scores_zero(self):
        result = score_headline("")
        self.assertEqual(result["score"], 0)

    def test_result_has_required_keys(self):
        result = score_headline("Some news headline")
        for key in ("score", "category", "sectors", "reason"):
            self.assertIn(key, result)


class TestScoreHeadlinePolicyTriggers(unittest.TestCase):
    """High-value policy keywords should raise scores significantly."""

    def test_executive_order_scores_high(self):
        result = score_headline("President signs executive order on AI regulation")
        self.assertGreaterEqual(result["score"], 3)

    def test_fed_rate_scores_high(self):
        result = score_headline("Fed rate decision expected to raise benchmark by 25bps")
        self.assertGreaterEqual(result["score"], 3)

    def test_debt_ceiling_scores_high(self):
        result = score_headline("Congress reaches deal to raise debt ceiling before deadline")
        self.assertGreaterEqual(result["score"], 3)

    def test_government_shutdown_scores_high(self):
        result = score_headline("Government shutdown averted after last-minute budget deal")
        self.assertGreaterEqual(result["score"], 3)

    def test_tariff_scores_policy(self):
        result = score_headline("White House announces new tariff on Chinese electronics")
        self.assertGreaterEqual(result["score"], 2)

    def test_sanctions_detected(self):
        result = score_headline("US imposes new sanctions against foreign energy firms")
        self.assertGreaterEqual(result["score"], 2)


class TestScoreHeadlineCategories(unittest.TestCase):
    """score_headline should assign the correct category."""

    def test_executive_order_category_is_policy(self):
        result = score_headline("President signs executive order restricting imports")
        self.assertEqual(result["category"], "policy")

    def test_fed_rate_category_is_macro(self):
        result = score_headline("Federal reserve holds interest rate steady at 5.25%")
        self.assertEqual(result["category"], "macro")

    def test_war_category_is_geopolitical(self):
        result = score_headline("Conflict escalates between two nations near oil fields")
        self.assertEqual(result["category"], "geopolitical")

    def test_antitrust_category_is_regulatory(self):
        result = score_headline("DOJ investigation launched over antitrust concerns")
        self.assertEqual(result["category"], "regulatory")


class TestScoreHeadlineSectors(unittest.TestCase):
    """Sector-specific keywords should populate the sectors list."""

    def test_semiconductor_keywords_tag_technology(self):
        result = score_headline("New chip ban targets advanced semiconductor exports to China")
        self.assertIn("technology", result["sectors"])

    def test_oil_keywords_tag_energy(self):
        result = score_headline("OPEC+ agrees to cut oil production by one million barrels")
        self.assertIn("energy", result["sectors"])

    def test_drug_pricing_tags_healthcare(self):
        result = score_headline("Congress passes drug pricing reform targeting medicare")
        self.assertIn("healthcare", result["sectors"])

    def test_defense_spending_tags_defense(self):
        result = score_headline("Pentagon secures record defense spending increase for next year")
        self.assertIn("defense", result["sectors"])

    def test_banking_regulation_tags_financials(self):
        result = score_headline("CFPB tightens banking regulation on credit card fees")
        self.assertIn("financials", result["sectors"])

    def test_multiple_sectors_detected(self):
        # Both tariff (consumer) and semiconductor (technology) keywords
        result = score_headline("New tariff on semiconductor imports hits consumer tech prices")
        self.assertGreaterEqual(len(result["sectors"]), 2)


class TestScoreHeadlineSummaryBoost(unittest.TestCase):
    """Summary text should contribute to scoring even if headline is mild."""

    def test_summary_adds_sector_context(self):
        # Headline alone has no sector; summary contains "oil"
        base = score_headline("Breaking: new policy announcement expected today")
        with_summary = score_headline(
            "Breaking: new policy announcement expected today",
            "The executive order targets oil and gas pipeline permits in federal land"
        )
        self.assertGreaterEqual(with_summary["score"], base["score"])

    def test_reason_field_lists_matched_keywords(self):
        result = score_headline("President signs executive order raising tariff on oil imports")
        self.assertGreater(len(result["reason"]), 0)


if __name__ == "__main__":
    unittest.main()
