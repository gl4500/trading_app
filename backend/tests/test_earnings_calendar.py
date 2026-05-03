"""Tests for data/earnings_calendar.py — yfinance-cached earnings dates."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestEarningsCalendar(unittest.TestCase):

    def setUp(self):
        # Each test gets its own cache file so they don't share state.
        self._tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w")
        self._tmp.write("{}")
        self._tmp.close()
        self._cache_patch = patch(
            "data.earnings_calendar.EARNINGS_CACHE_PATH", self._tmp.name,
        )
        self._cache_patch.start()

    def tearDown(self):
        self._cache_patch.stop()
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def _mock_yfinance(self, next_dt=None, last_dt=None):
        """Return a context manager that patches yfinance.Ticker."""
        mock_ticker = MagicMock()
        mock_ticker.calendar = {"Earnings Date": [next_dt] if next_dt else None}
        if last_dt is not None:
            # earnings_history is a DataFrame indexed by datetime — emulate
            # with a small object whose .index is a list of datetime values
            # and len works.
            mock_hist = MagicMock()
            mock_hist.__len__ = lambda self_: 1
            mock_hist.index = [last_dt]
            mock_ticker.earnings_history = mock_hist
        else:
            mock_ticker.earnings_history = None
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        return patch.dict("sys.modules", {"yfinance": mock_yf})

    def test_fetches_and_caches_on_miss(self):
        from data import earnings_calendar
        future = datetime.now(timezone.utc) + timedelta(days=14)
        past   = datetime.now(timezone.utc) - timedelta(days=60)
        with self._mock_yfinance(next_dt=future, last_dt=past):
            ed = earnings_calendar.get_earnings_dates("AAPL")
        self.assertEqual(ed.next_earnings, future.isoformat()[:10])
        self.assertEqual(ed.last_earnings, past.isoformat()[:10])
        # Should now be in the cache file
        with open(self._tmp.name, "r", encoding="utf-8") as f:
            cache = json.load(f)
        self.assertIn("AAPL", cache)
        self.assertEqual(cache["AAPL"]["next_earnings"], future.isoformat()[:10])

    def test_cache_hit_skips_yfinance(self):
        """If a recent cache entry exists, get_earnings_dates returns it
        without calling yfinance."""
        from data import earnings_calendar
        with open(self._tmp.name, "w", encoding="utf-8") as f:
            json.dump({
                "AAPL": {
                    "next_earnings": "2026-07-30",
                    "last_earnings": "2026-04-30",
                    "fetched_ts":    time.time(),
                },
            }, f)
        # If yfinance is called we'd see it raise (no patch installed)
        ed = earnings_calendar.get_earnings_dates("AAPL")
        self.assertEqual(ed.next_earnings, "2026-07-30")
        self.assertEqual(ed.last_earnings, "2026-04-30")

    def test_stale_cache_triggers_refresh(self):
        """Cache entries older than the TTL are re-fetched."""
        from data import earnings_calendar
        # 25h ago — past the 24h TTL
        with open(self._tmp.name, "w", encoding="utf-8") as f:
            json.dump({
                "AAPL": {
                    "next_earnings": "OLD",
                    "last_earnings": "OLD",
                    "fetched_ts":    time.time() - 25 * 3600,
                },
            }, f)
        future = datetime.now(timezone.utc) + timedelta(days=14)
        past   = datetime.now(timezone.utc) - timedelta(days=60)
        with self._mock_yfinance(next_dt=future, last_dt=past):
            ed = earnings_calendar.get_earnings_dates("AAPL")
        self.assertNotEqual(ed.next_earnings, "OLD")

    def test_force_refresh_bypasses_cache(self):
        from data import earnings_calendar
        with open(self._tmp.name, "w", encoding="utf-8") as f:
            json.dump({
                "AAPL": {
                    "next_earnings": "FRESH-IN-CACHE",
                    "last_earnings": None,
                    "fetched_ts":    time.time(),   # fresh
                },
            }, f)
        future = datetime.now(timezone.utc) + timedelta(days=10)
        with self._mock_yfinance(next_dt=future):
            ed = earnings_calendar.get_earnings_dates("AAPL", force_refresh=True)
        self.assertEqual(ed.next_earnings, future.isoformat()[:10])

    def test_yfinance_failure_returns_none_dates(self):
        from data import earnings_calendar
        mock_yf = MagicMock()
        mock_yf.Ticker.side_effect = RuntimeError("network down")
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            ed = earnings_calendar.get_earnings_dates("XYZ")
        self.assertIsNone(ed.next_earnings)
        self.assertIsNone(ed.last_earnings)

    def test_days_to_next_earnings_positive_when_future(self):
        from data import earnings_calendar
        # Pre-populate cache with a date 7 days out
        seven_days_iso = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()[:10]
        with open(self._tmp.name, "w", encoding="utf-8") as f:
            json.dump({
                "AAPL": {
                    "next_earnings": seven_days_iso,
                    "last_earnings": None,
                    "fetched_ts":    time.time(),
                },
            }, f)
        days = earnings_calendar.days_to_next_earnings("AAPL", time.time())
        self.assertIsNotNone(days)
        self.assertAlmostEqual(days, 7.0, delta=1.0)

    def test_days_since_last_earnings_positive_when_past(self):
        from data import earnings_calendar
        thirty_days_ago_iso = (
            datetime.now(timezone.utc) - timedelta(days=30)
        ).isoformat()[:10]
        with open(self._tmp.name, "w", encoding="utf-8") as f:
            json.dump({
                "MSFT": {
                    "next_earnings": None,
                    "last_earnings": thirty_days_ago_iso,
                    "fetched_ts":    time.time(),
                },
            }, f)
        days = earnings_calendar.days_since_last_earnings("MSFT", time.time())
        self.assertIsNotNone(days)
        self.assertAlmostEqual(days, 30.0, delta=1.0)

    def test_days_to_next_returns_none_when_unknown(self):
        from data import earnings_calendar
        # No cache entry, yfinance fails
        mock_yf = MagicMock()
        mock_yf.Ticker.side_effect = RuntimeError("nope")
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            days = earnings_calendar.days_to_next_earnings("UNKNOWN", time.time())
        self.assertIsNone(days)

    def test_bulk_lookup_returns_one_per_symbol(self):
        from data import earnings_calendar
        future = datetime.now(timezone.utc) + timedelta(days=10)
        past   = datetime.now(timezone.utc) - timedelta(days=20)
        with self._mock_yfinance(next_dt=future, last_dt=past):
            result = earnings_calendar.get_earnings_dates_bulk(["AAPL", "MSFT", "NVDA"])
        self.assertEqual(set(result.keys()), {"AAPL", "MSFT", "NVDA"})
        for sym, ed in result.items():
            self.assertEqual(ed.next_earnings, future.isoformat()[:10])


if __name__ == "__main__":
    unittest.main()
