"""
Unit tests for data/sector_analysis.py
Covers: get_sector_performance(), get_stock_vs_sector(),
        format_sector_summary(), format_stock_sector_context()
"""
import sys
import os
import unittest
from unittest.mock import AsyncMock, patch
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import data.sector_analysis as sa


def _make_bars(closes):
    """Build a minimal OHLCV DataFrame from a list of close prices."""
    return pd.DataFrame({
        "close":  closes,
        "volume": [1_000_000] * len(closes),
    })


def _make_bars_dict(overrides=None):
    """
    Return a bars dict for ALL_ETFS with sensible defaults.
    SPY: +0.4%  QQQ: +0.9%  IWM: -0.2%
    XLK: +1.2%  XLF: +0.6%  XLE: -0.8%  XLV: +0.3%
    XLY: +0.5%  XLP: -0.1%  XLI: +0.2%  XLC: +0.7%
    XLB: -0.3%
    """
    base_prices = {
        "SPY": [400.0, 401.6],      # +0.4%
        "QQQ": [350.0, 353.15],     # +0.9%
        "IWM": [200.0, 199.6],      # -0.2%
        "XLK": [180.0, 182.16],     # +1.2%
        "XLF": [40.0,  40.24],      # +0.6%
        "XLE": [80.0,  79.36],      # -0.8%
        "XLV": [140.0, 140.42],     # +0.3%
        "XLY": [170.0, 170.85],     # +0.5%
        "XLP": [75.0,  74.925],     # -0.1%
        "XLI": [110.0, 110.22],     # +0.2%
        "XLC": [65.0,  65.455],     # +0.7%
        "XLB": [85.0,  84.745],     # -0.3%
    }
    d = {sym: _make_bars(closes) for sym, closes in base_prices.items()}
    if overrides:
        d.update(overrides)
    return d


# ── TestGetSectorPerformance ──────────────────────────────────────────────────

class TestGetSectorPerformance(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Reset module-level cache before every test
        sa._cache = None
        sa._cache_ts = 0.0

    async def _call(self, bars_override=None):
        bars = _make_bars_dict(bars_override)
        with patch("data.sector_analysis._fetch_bars", new_callable=AsyncMock) as m:
            m.return_value = bars
            result = await sa.get_sector_performance()
        return result

    async def test_returns_benchmark_1d(self):
        result = await self._call()
        self.assertAlmostEqual(result["benchmark_1d"], 0.4, places=1)

    async def test_broad_market_keys_present(self):
        result = await self._call()
        for etf in ("SPY", "QQQ", "IWM"):
            self.assertIn(etf, result["broad"])

    async def test_sectors_dict_populated(self):
        result = await self._call()
        self.assertGreater(len(result["sectors"]), 0)

    async def test_sector_entry_has_expected_keys(self):
        result = await self._call()
        entry = result["sectors"].get("Technology", {})
        for key in ("etf", "pct_1d", "pct_5d", "vs_spy_1d", "trend"):
            self.assertIn(key, entry)

    async def test_leading_sector_trend(self):
        # XLK +1.2% vs SPY +0.4% = +0.8% → leading (threshold 0.5)
        result = await self._call()
        self.assertEqual(result["sectors"]["Technology"]["trend"], "leading")

    async def test_lagging_sector_trend(self):
        # XLE -0.8% vs SPY +0.4% = -1.2% → lagging (threshold -0.5)
        result = await self._call()
        self.assertEqual(result["sectors"]["Energy"]["trend"], "lagging")

    async def test_neutral_sector_trend(self):
        # XLV +0.3% vs SPY +0.4% = -0.1% → neutral
        result = await self._call()
        self.assertEqual(result["sectors"]["Healthcare"]["trend"], "neutral")

    async def test_missing_etf_excluded_from_sectors(self):
        # Return empty dict for XLK → Technology should be absent
        bars = _make_bars_dict({"XLK": pd.DataFrame()})
        with patch("data.sector_analysis._fetch_bars", new_callable=AsyncMock) as m:
            m.return_value = bars
            sa._cache = None
            result = await sa.get_sector_performance()
        self.assertNotIn("Technology", result["sectors"])

    async def test_result_is_cached_second_call_does_not_refetch(self):
        bars = _make_bars_dict()
        with patch("data.sector_analysis._fetch_bars", new_callable=AsyncMock) as m:
            m.return_value = bars
            await sa.get_sector_performance()
            await sa.get_sector_performance()   # should use cache
            self.assertEqual(m.call_count, 1)

    async def test_vs_spy_1d_computed_correctly(self):
        result = await self._call()
        tech = result["sectors"]["Technology"]
        expected_vs_spy = round(tech["pct_1d"] - result["benchmark_1d"], 2)
        self.assertAlmostEqual(tech["vs_spy_1d"], expected_vs_spy, places=2)


# ── TestGetStockVsSector ──────────────────────────────────────────────────────

class TestGetStockVsSector(unittest.TestCase):

    def _make_perf(self, spy_1d=0.4, xlk_1d=1.2, xlk_trend="leading"):
        return {
            "benchmark_1d": spy_1d,
            "sectors": {
                "Technology": {
                    "etf": "XLK",
                    "pct_1d": xlk_1d,
                    "vs_spy_1d": round(xlk_1d - spy_1d, 2),
                    "trend": xlk_trend,
                }
            },
            "broad": {"SPY": {"pct_1d": spy_1d}},
        }

    def test_outperforming_stock(self):
        # NVDA +3.0% when XLK +1.2% → diff +1.8 >= 1.0 → outperforming
        perf = self._make_perf(xlk_1d=1.2)
        result = sa.get_stock_vs_sector("NVDA", 3.0, perf)
        self.assertEqual(result["stock_label"], "outperforming sector")

    def test_underperforming_stock(self):
        # NVDA -1.5% when XLK +1.2% → diff -2.7 <= -1.0 → underperforming
        perf = self._make_perf(xlk_1d=1.2)
        result = sa.get_stock_vs_sector("NVDA", -1.5, perf)
        self.assertEqual(result["stock_label"], "underperforming sector")

    def test_in_line_stock(self):
        # NVDA +1.5% when XLK +1.2% → diff +0.3, within threshold → in line
        perf = self._make_perf(xlk_1d=1.2)
        result = sa.get_stock_vs_sector("NVDA", 1.5, perf)
        self.assertEqual(result["stock_label"], "in line with sector")

    def test_returns_sector_name(self):
        perf = self._make_perf()
        result = sa.get_stock_vs_sector("NVDA", 1.0, perf)
        self.assertEqual(result["sector_name"], "Technology")

    def test_returns_sector_trend(self):
        perf = self._make_perf(xlk_trend="leading")
        result = sa.get_stock_vs_sector("NVDA", 1.0, perf)
        self.assertEqual(result["sector_trend"], "leading")

    def test_unknown_symbol_handled(self):
        # Symbol not in universe → sector_name "Unknown", no crash
        perf = self._make_perf()
        result = sa.get_stock_vs_sector("ZZZZ", 1.0, perf)
        self.assertEqual(result["sector_name"], "Unknown")
        # stock_vs_sector should be None (no sector data for Unknown)
        self.assertIsNone(result["stock_vs_sector"])

    def test_none_stock_pct_handled(self):
        perf = self._make_perf()
        result = sa.get_stock_vs_sector("NVDA", None, perf)
        self.assertIsNone(result["stock_vs_sector"])

    def test_benchmark_1d_passed_through(self):
        perf = self._make_perf(spy_1d=0.4)
        result = sa.get_stock_vs_sector("NVDA", 1.0, perf)
        self.assertAlmostEqual(result["benchmark_1d"], 0.4)


# ── TestFormatSectorSummary ───────────────────────────────────────────────────

class TestFormatSectorSummary(unittest.TestCase):

    def _make_perf(self):
        return {
            "benchmark_1d": 0.4,
            "broad": {
                "SPY": {"pct_1d": 0.4},
                "QQQ": {"pct_1d": 0.9},
                "IWM": {"pct_1d": -0.2},
            },
            "sectors": {
                "Technology": {"etf": "XLK", "pct_1d": 1.2, "vs_spy_1d": 0.8,  "trend": "leading"},
                "Energy":     {"etf": "XLE", "pct_1d": -0.8, "vs_spy_1d": -1.2, "trend": "lagging"},
                "Healthcare": {"etf": "XLV", "pct_1d": 0.3,  "vs_spy_1d": -0.1, "trend": "neutral"},
            },
        }

    def test_empty_returns_empty_string(self):
        self.assertEqual(sa.format_sector_summary({}), "")

    def test_contains_spy_return(self):
        result = sa.format_sector_summary(self._make_perf())
        self.assertIn("SPY", result)

    def test_contains_qqq(self):
        result = sa.format_sector_summary(self._make_perf())
        self.assertIn("QQQ", result)

    def test_leading_sector_in_summary(self):
        result = sa.format_sector_summary(self._make_perf())
        self.assertIn("Technology", result)
        self.assertIn("leading", result.lower())

    def test_lagging_sector_in_summary(self):
        result = sa.format_sector_summary(self._make_perf())
        self.assertIn("Energy", result)
        self.assertIn("lagging", result.lower())

    def test_no_broad_data_still_returns_sectors(self):
        perf = self._make_perf()
        perf["broad"] = {}
        result = sa.format_sector_summary(perf)
        self.assertIn("Technology", result)


# ── TestFormatStockSectorContext ──────────────────────────────────────────────

class TestFormatStockSectorContext(unittest.TestCase):

    def _stock_data(self, label="outperforming sector", trend="leading"):
        return {
            "sector_name":   "Technology",
            "sector_etf":    "XLK",
            "sector_pct_1d": 1.2,
            "sector_trend":  trend,
            "stock_vs_sector": 1.8,
            "stock_label":   label,
            "benchmark_1d":  0.4,
        }

    def test_shows_sector_name(self):
        result = sa.format_stock_sector_context("NVDA", self._stock_data())
        self.assertIn("Technology", result)

    def test_shows_sector_etf(self):
        result = sa.format_stock_sector_context("NVDA", self._stock_data())
        self.assertIn("XLK", result)

    def test_shows_outperforming_label(self):
        result = sa.format_stock_sector_context("NVDA", self._stock_data("outperforming sector"))
        self.assertIn("outperforming", result)

    def test_shows_underperforming_label(self):
        result = sa.format_stock_sector_context("NVDA", self._stock_data("underperforming sector"))
        self.assertIn("underperforming", result)

    def test_shows_trend(self):
        result = sa.format_stock_sector_context("NVDA", self._stock_data(trend="leading"))
        self.assertIn("leading", result)

    def test_empty_data_returns_empty_string(self):
        self.assertEqual(sa.format_stock_sector_context("NVDA", {}), "")


if __name__ == "__main__":
    unittest.main()
