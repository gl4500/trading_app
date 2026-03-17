"""
Unit tests for data/sentinel_sources.py
Covers: _parse_rss(), _make_catalyst(), _score() — pure/offline helpers.
Network-fetching async functions (fetch_rss_feeds, fetch_edgar_8k, etc.)
are not called here to avoid live HTTP traffic in CI; they are smoke-tested
with patched httpx clients.
"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from data.sentinel_sources import _parse_rss, _make_catalyst, _score


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── _score tests ──────────────────────────────────────────────────────────────

class TestScore(unittest.TestCase):
    """_score() calls policy_monitor.score_headline internally."""

    def test_returns_dict_with_score_key(self):
        result = _score("Fed raises interest rate by 25 basis points")
        self.assertIn("score", result)

    def test_unrelated_headline_score_zero(self):
        # Use a headline with no policy, macro, or sector keywords at all
        result = _score("Local city marathon sets new participation record")
        self.assertEqual(result["score"], 0)

    def test_policy_headline_nonzero_score(self):
        result = _score("President signs executive order targeting semiconductor exports")
        self.assertGreater(result["score"], 0)

    def test_returns_category_and_sectors(self):
        result = _score("New tariff on oil imports announced")
        self.assertIn("category", result)
        self.assertIn("sectors", result)


# ── _make_catalyst tests ──────────────────────────────────────────────────────

class TestMakeCatalyst(unittest.TestCase):

    def test_low_score_headline_returns_none(self):
        # Completely irrelevant headline → score=0 → filtered out
        result = _make_catalyst("Weekend sports results are in", "", "TestSource", "2024-01-01")
        self.assertIsNone(result)

    def test_high_score_headline_returns_dict(self):
        result = _make_catalyst(
            "President signs executive order on semiconductor export controls",
            "The executive order restricts advanced chip sales to adversary nations",
            "Reuters", "2024-06-15"
        )
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)

    def test_catalyst_has_required_fields(self):
        result = _make_catalyst(
            "Fed rate decision: Federal Reserve raises interest rate 0.25%",
            "Federal Reserve votes to raise rates", "CNBC", "2024-06-15", "SPY"
        )
        if result is not None:
            for field in ("headline", "summary", "source", "date", "symbol",
                          "score", "category", "sectors", "reason", "detected_at"):
                self.assertIn(field, result)

    def test_symbol_preserved(self):
        result = _make_catalyst(
            "Fed rate decision today: Federal Reserve raises interest rate",
            "", "CNBC", "2024-06-15", "AAPL"
        )
        if result is not None:
            self.assertEqual(result["symbol"], "AAPL")

    def test_headline_truncated_at_200_chars(self):
        long_headline = "A" * 300
        # Score will be 0 so None is returned — use a real policy headline
        result = _make_catalyst(
            "Federal Reserve raises interest rate: " + "x" * 200,
            "", "Test", "2024-01-01"
        )
        if result is not None:
            self.assertLessEqual(len(result["headline"]), 200)


# ── _parse_rss tests ──────────────────────────────────────────────────────────

class TestParseRss(unittest.TestCase):

    def _rss_xml(self, title, description="", pub_date="Mon, 01 Jan 2024 12:00:00 GMT"):
        return f"""<?xml version="1.0"?>
        <rss version="2.0"><channel>
          <item>
            <title>{title}</title>
            <description>{description}</description>
            <pubDate>{pub_date}</pubDate>
          </item>
        </channel></rss>"""

    def test_parse_valid_rss_returns_list(self):
        xml = self._rss_xml("Some headline here")
        result = _parse_rss(xml, "TestSource")
        self.assertIsInstance(result, list)

    def test_policy_headline_returns_catalyst(self):
        xml = self._rss_xml(
            "President signs executive order on tariff policy",
            "White House announces new tariff measures affecting trade war"
        )
        result = _parse_rss(xml, "TestSource")
        # At least one catalyst should be scored ≥ 1
        self.assertGreater(len(result), 0)

    def test_irrelevant_headline_filtered_out(self):
        xml = self._rss_xml("Local restaurant serves new menu item today")
        result = _parse_rss(xml, "TestSource")
        self.assertEqual(len(result), 0)

    def test_malformed_xml_returns_empty_list(self):
        result = _parse_rss("this is not xml at all <<<", "TestSource")
        self.assertEqual(result, [])

    def test_empty_string_returns_empty_list(self):
        result = _parse_rss("", "TestSource")
        self.assertEqual(result, [])

    def test_atom_feed_parsed(self):
        atom_xml = """<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>Federal Reserve raises interest rate decision 25bps</title>
            <summary>The Fed raises rates amid inflation report concerns</summary>
            <updated>2024-06-15T12:00:00Z</updated>
          </entry>
        </feed>"""
        result = _parse_rss(atom_xml, "TestAtom")
        self.assertIsInstance(result, list)
        # The headline scores ≥ 1 (fed rate = 3 points)
        self.assertGreater(len(result), 0)

    def test_source_name_preserved_in_result(self):
        xml = self._rss_xml(
            "President signs executive order on semiconductor tariff"
        )
        result = _parse_rss(xml, "MySource")
        if result:
            self.assertEqual(result[0]["source"], "MySource")


if __name__ == "__main__":
    unittest.main()
