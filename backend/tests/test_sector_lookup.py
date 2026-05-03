"""
Unit tests for data/sector_lookup.py

Covers:
  * Cache hit (no yfinance call when symbol already in sectors.json)
  * Cache miss (lazy fetch from yfinance, persists to cache)
  * Failure modes (yfinance raises, missing "sector" key)
  * Bulk lookup (get_sectors)
  * Stable SECTOR_TO_ID mapping (Unknown=0, alphabetical thereafter)
  * force_refresh=True bypasses cache
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class SectorLookupTestBase(unittest.TestCase):
    """Provides a temp cache dir + patches the module-level cache path."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.cache_path = os.path.join(self._tmpdir.name, "sectors.json")

        # Import module fresh and patch its cache path constant
        import data.sector_lookup as sector_lookup
        self.sector_lookup = sector_lookup
        self._orig_path = sector_lookup.SECTORS_CACHE_PATH
        sector_lookup.SECTORS_CACHE_PATH = self.cache_path

    def tearDown(self):
        self.sector_lookup.SECTORS_CACHE_PATH = self._orig_path

    def _write_cache(self, payload: dict):
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)


class TestGetSectorCache(SectorLookupTestBase):

    def test_get_sector_uses_cache_when_present(self):
        """Cache hit must NOT call yfinance."""
        self._write_cache({"AAPL": "Technology"})

        with patch.object(self.sector_lookup, "yfinance") as mock_yf:
            result = self.sector_lookup.get_sector("AAPL")

        self.assertEqual(result, "Technology")
        mock_yf.Ticker.assert_not_called()

    def test_get_sector_fetches_and_caches_on_miss(self):
        """Cache miss must call yfinance and persist the value."""
        self.assertFalse(os.path.exists(self.cache_path))

        with patch.object(self.sector_lookup, "yfinance") as mock_yf:
            mock_ticker = MagicMock()
            mock_ticker.info = {"sector": "Technology"}
            mock_yf.Ticker.return_value = mock_ticker

            result = self.sector_lookup.get_sector("AAPL")

        self.assertEqual(result, "Technology")
        mock_yf.Ticker.assert_called_once_with("AAPL")

        # Persisted to disk
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            cached = json.load(fh)
        self.assertEqual(cached.get("AAPL"), "Technology")

    def test_get_sector_returns_unknown_on_yfinance_failure(self):
        """If yfinance raises (network, etc.) return 'Unknown'."""
        with patch.object(self.sector_lookup, "yfinance") as mock_yf:
            mock_yf.Ticker.side_effect = RuntimeError("network down")
            result = self.sector_lookup.get_sector("AAPL")

        self.assertEqual(result, "Unknown")

    def test_get_sector_returns_unknown_on_missing_sector_key(self):
        """If the .info dict has no 'sector' key, return 'Unknown'."""
        with patch.object(self.sector_lookup, "yfinance") as mock_yf:
            mock_ticker = MagicMock()
            mock_ticker.info = {"longName": "Some Co.", "marketCap": 1_000_000}
            mock_yf.Ticker.return_value = mock_ticker

            result = self.sector_lookup.get_sector("ZZZZ")

        self.assertEqual(result, "Unknown")


class TestGetSectorsBulk(SectorLookupTestBase):

    def test_get_sectors_bulk_caches_all(self):
        """get_sectors() with three new symbols should call yfinance 3x and cache all."""
        with patch.object(self.sector_lookup, "yfinance") as mock_yf:
            def _ticker(sym):
                m = MagicMock()
                m.info = {
                    "AAPL": {"sector": "Technology"},
                    "JPM": {"sector": "Financial Services"},
                    "XOM": {"sector": "Energy"},
                }[sym]
                return m
            mock_yf.Ticker.side_effect = _ticker

            result = self.sector_lookup.get_sectors(["AAPL", "JPM", "XOM"])

        self.assertEqual(result, {
            "AAPL": "Technology",
            "JPM": "Financial Services",
            "XOM": "Energy",
        })
        self.assertEqual(mock_yf.Ticker.call_count, 3)

        # All persisted
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            cached = json.load(fh)
        self.assertEqual(cached["AAPL"], "Technology")
        self.assertEqual(cached["JPM"], "Financial Services")
        self.assertEqual(cached["XOM"], "Energy")


class TestForceRefresh(SectorLookupTestBase):

    def test_force_refresh_bypasses_cache(self):
        """force_refresh=True must hit yfinance even if cache is populated."""
        self._write_cache({"AAPL": "StaleSector"})

        with patch.object(self.sector_lookup, "yfinance") as mock_yf:
            mock_ticker = MagicMock()
            mock_ticker.info = {"sector": "Technology"}
            mock_yf.Ticker.return_value = mock_ticker

            result = self.sector_lookup.get_sectors(
                ["AAPL"], force_refresh=True
            )

        self.assertEqual(result, {"AAPL": "Technology"})
        mock_yf.Ticker.assert_called_once_with("AAPL")

        # Cache overwritten with fresh value
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            cached = json.load(fh)
        self.assertEqual(cached["AAPL"], "Technology")


class TestSectorToIdMapping(unittest.TestCase):

    def test_sector_to_id_mapping_stable(self):
        """SECTOR_TO_ID has 'Unknown' at index 0 and rest alphabetical."""
        # Fresh import — no cache patching needed; this exercises module constants
        import data.sector_lookup as sector_lookup

        mapping = sector_lookup.SECTOR_TO_ID
        self.assertIsInstance(mapping, dict)
        self.assertEqual(mapping["Unknown"], 0)

        # All 11 GICS sectors yfinance returns + Unknown = 12 total
        expected_sectors = [
            "Basic Materials",
            "Communication Services",
            "Consumer Cyclical",
            "Consumer Defensive",
            "Energy",
            "Financial Services",
            "Healthcare",
            "Industrials",
            "Real Estate",
            "Technology",
            "Utilities",
        ]
        for idx, sector in enumerate(expected_sectors, start=1):
            self.assertEqual(
                mapping[sector], idx,
                f"{sector} should map to {idx} (alphabetical), got {mapping.get(sector)}",
            )

        # Length: 11 GICS + 1 Unknown = 12
        self.assertEqual(len(mapping), 12)


if __name__ == "__main__":
    unittest.main()
