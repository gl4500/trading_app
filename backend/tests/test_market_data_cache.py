"""
Unit tests for data/market_data.py — MarketDataCache and MarketDataService.
MarketDataService tests verify Alpaca-primary data flow (Massive is last resort).
"""
import sys
import os
import asyncio
import unittest
from unittest.mock import AsyncMock, patch, MagicMock
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.market_data import MarketDataCache


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestMarketDataCache(unittest.TestCase):

    def setUp(self):
        # Use a short TTL for expiry tests
        self.cache = MarketDataCache(ttl_seconds=2)

    def test_get_missing_key_returns_none(self):
        result = run(self.cache.get("nonexistent_key"))
        self.assertIsNone(result)

    def test_set_then_get_returns_same_value(self):
        run(self.cache.set("AAPL|price", 150.0))
        result = run(self.cache.get("AAPL|price"))
        self.assertEqual(result, 150.0)

    def test_set_overwrites_existing_value(self):
        run(self.cache.set("AAPL|price", 150.0))
        run(self.cache.set("AAPL|price", 155.0))
        result = run(self.cache.get("AAPL|price"))
        self.assertEqual(result, 155.0)

    def test_cache_stores_dict_value(self):
        payload = {"open": 100.0, "close": 105.0, "volume": 1_000_000}
        run(self.cache.set("AAPL|bars", payload))
        result = run(self.cache.get("AAPL|bars"))
        self.assertEqual(result, payload)

    def test_clear_empties_cache(self):
        run(self.cache.set("AAPL|price", 150.0))
        run(self.cache.set("MSFT|price", 300.0))
        run(self.cache.clear())
        self.assertIsNone(run(self.cache.get("AAPL|price")))
        self.assertIsNone(run(self.cache.get("MSFT|price")))

    def test_expired_entry_returns_none(self):
        import time
        short_cache = MarketDataCache(ttl_seconds=0)  # 0-second TTL
        run(short_cache.set("AAPL|price", 150.0))
        time.sleep(0.01)
        result = run(short_cache.get("AAPL|price"))
        self.assertIsNone(result)

    def test_multiple_keys_independent(self):
        run(self.cache.set("AAPL|price", 150.0))
        run(self.cache.set("MSFT|price", 300.0))
        self.assertEqual(run(self.cache.get("AAPL|price")), 150.0)
        self.assertEqual(run(self.cache.get("MSFT|price")), 300.0)

    def test_make_key_separates_args(self):
        key = self.cache._make_key("AAPL", "bars", 60)
        self.assertEqual(key, "AAPL|bars|60")


def _make_bars(n=5) -> pd.DataFrame:
    """Return a minimal OHLCV DataFrame with n rows."""
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n),
        "open":  [100.0] * n,
        "high":  [105.0] * n,
        "low":   [95.0]  * n,
        "close": [102.0] * n,
        "volume": [1_000_000] * n,
    })


class TestMarketDataServiceAlpacaPrimary(unittest.IsolatedAsyncioTestCase):
    """Verify that Alpaca is the primary data source; Massive is last resort."""

    # ── get_latest_prices ──────────────────────────────────────────────────────

    async def test_get_latest_prices_uses_alpaca_as_primary(self):
        """When Alpaca returns prices, Massive should not be called."""
        from data.market_data import MarketDataService
        svc = MarketDataService()
        svc._last_price_fetch = 0  # force cache miss

        with patch("data.market_data.alpaca_client") as mock_alpaca, \
             patch("data.market_data.massive_client") as mock_massive:
            mock_alpaca.get_latest_prices = AsyncMock(return_value={"AAPL": 175.0, "MSFT": 420.0})
            mock_massive.get_snapshots = AsyncMock(return_value={})

            prices = await svc.get_latest_prices(["AAPL", "MSFT"])

        self.assertEqual(prices["AAPL"], 175.0)
        self.assertEqual(prices["MSFT"], 420.0)
        mock_alpaca.get_latest_prices.assert_called_once()
        mock_massive.get_snapshots.assert_not_called()

    async def test_get_latest_prices_falls_back_to_massive(self):
        """When Alpaca returns empty, Massive should be tried."""
        from data.market_data import MarketDataService
        svc = MarketDataService()
        svc._last_price_fetch = 0

        with patch("data.market_data.alpaca_client") as mock_alpaca, \
             patch("data.market_data.massive_client") as mock_massive:
            mock_alpaca.get_latest_prices = AsyncMock(return_value={})
            mock_massive.get_snapshots = AsyncMock(return_value={"AAPL": 170.0})

            prices = await svc.get_latest_prices(["AAPL"])

        self.assertEqual(prices["AAPL"], 170.0)
        mock_massive.get_snapshots.assert_called_once()

    async def test_get_latest_prices_falls_back_when_alpaca_raises(self):
        """When Alpaca raises, Massive should be tried."""
        from data.market_data import MarketDataService
        svc = MarketDataService()
        svc._last_price_fetch = 0

        with patch("data.market_data.alpaca_client") as mock_alpaca, \
             patch("data.market_data.massive_client") as mock_massive:
            mock_alpaca.get_latest_prices = AsyncMock(side_effect=Exception("network error"))
            mock_massive.get_snapshots = AsyncMock(return_value={"AAPL": 168.0})

            prices = await svc.get_latest_prices(["AAPL"])

        self.assertEqual(prices["AAPL"], 168.0)
        mock_massive.get_snapshots.assert_called_once()

    # ── get_historical_bars ────────────────────────────────────────────────────

    async def test_get_historical_bars_uses_alpaca_as_primary(self):
        """When Alpaca returns bars, Massive should not be called."""
        from data.market_data import MarketDataService
        svc = MarketDataService()
        bars = _make_bars(30)

        with patch("data.market_data.alpaca_client") as mock_alpaca, \
             patch("data.market_data.massive_client") as mock_massive, \
             patch("data.market_data.stooq_client") as mock_stooq:
            mock_alpaca.get_bars = AsyncMock(return_value=bars)
            mock_massive.get_bars = AsyncMock(return_value=pd.DataFrame())
            mock_stooq.get_bars = AsyncMock(return_value=pd.DataFrame())

            result = await svc.get_historical_bars("AAPL", days=30)

        self.assertFalse(result.empty)
        self.assertEqual(len(result), 30)
        mock_alpaca.get_bars.assert_called_once()
        mock_massive.get_bars.assert_not_called()

    async def test_get_historical_bars_falls_back_to_stooq(self):
        """When Alpaca returns empty, Stooq should be tried before Massive."""
        from data.market_data import MarketDataService
        svc = MarketDataService()
        bars = _make_bars(10)

        with patch("data.market_data.alpaca_client") as mock_alpaca, \
             patch("data.market_data.stooq_client") as mock_stooq, \
             patch("data.market_data.massive_client") as mock_massive:
            mock_alpaca.get_bars = AsyncMock(return_value=pd.DataFrame())
            mock_stooq.get_bars = AsyncMock(return_value=bars)
            mock_massive.get_bars = AsyncMock(return_value=pd.DataFrame())

            result = await svc.get_historical_bars("AAPL", days=10)

        self.assertFalse(result.empty)
        mock_stooq.get_bars.assert_called_once()
        mock_massive.get_bars.assert_not_called()

    async def test_get_historical_bars_falls_back_to_massive_last(self):
        """When both Alpaca and Stooq fail, Massive should be tried last."""
        from data.market_data import MarketDataService
        svc = MarketDataService()
        bars = _make_bars(10)

        with patch("data.market_data.alpaca_client") as mock_alpaca, \
             patch("data.market_data.stooq_client") as mock_stooq, \
             patch("data.market_data.massive_client") as mock_massive:
            mock_alpaca.get_bars = AsyncMock(return_value=pd.DataFrame())
            mock_stooq.get_bars = AsyncMock(return_value=pd.DataFrame())
            mock_massive.get_bars = AsyncMock(return_value=bars)

            result = await svc.get_historical_bars("AAPL", days=10)

        self.assertFalse(result.empty)
        mock_massive.get_bars.assert_called_once()

    # ── get_all_bars ───────────────────────────────────────────────────────────

    async def test_get_all_bars_uses_alpaca_batch_as_primary(self):
        """When Alpaca batch returns bars, Massive should not be called."""
        from data.market_data import MarketDataService
        svc = MarketDataService()
        bars = _make_bars(30)

        with patch("data.market_data.alpaca_client") as mock_alpaca, \
             patch("data.market_data.massive_client") as mock_massive:
            mock_alpaca.get_bars_multi = AsyncMock(return_value={"AAPL": bars, "MSFT": bars})
            mock_massive.get_bars_multi = AsyncMock(return_value={})

            result = await svc.get_all_bars(["AAPL", "MSFT"], days=30)

        self.assertIn("AAPL", result)
        self.assertFalse(result["AAPL"].empty)
        mock_alpaca.get_bars_multi.assert_called_once()
        mock_massive.get_bars_multi.assert_not_called()

    async def test_get_all_bars_falls_back_when_alpaca_returns_empty(self):
        """When Alpaca batch returns empty, stooq or massive should be tried."""
        from data.market_data import MarketDataService
        svc = MarketDataService()
        bars = _make_bars(10)

        with patch("data.market_data.alpaca_client") as mock_alpaca, \
             patch("data.market_data.stooq_client") as mock_stooq, \
             patch("data.market_data.massive_client") as mock_massive:
            mock_alpaca.get_bars_multi = AsyncMock(return_value={})
            mock_stooq.get_bars_multi = AsyncMock(return_value={"AAPL": bars})
            mock_massive.get_bars_multi = AsyncMock(return_value={})

            result = await svc.get_all_bars(["AAPL"], days=10)

        self.assertIn("AAPL", result)
        mock_stooq.get_bars_multi.assert_called_once()
        mock_massive.get_bars_multi.assert_not_called()


class TestSnapshotForbiddenFlag(unittest.IsolatedAsyncioTestCase):
    """Verify _snapshot_forbidden flag stops cascading 403 calls."""

    async def test_snapshot_forbidden_set_on_403(self):
        """A 403 response on batch snapshot sets _snapshot_forbidden."""
        from data.massive_client import MassiveClient
        import httpx
        client = MassiveClient()
        client._is_available = lambda: True

        mock_resp = MagicMock()
        mock_resp.status_code = 403

        with patch("httpx.AsyncClient") as mock_http:
            mock_http.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                get=AsyncMock(return_value=mock_resp)
            ))
            mock_http.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await client.get_snapshots(["AAPL"])

        self.assertTrue(client._snapshot_forbidden)
        self.assertEqual(result, {})

    async def test_snapshot_forbidden_skips_all_calls(self):
        """Once _snapshot_forbidden is True, get_snapshots returns {} immediately."""
        from data.massive_client import MassiveClient
        client = MassiveClient()
        client._snapshot_forbidden = True

        with patch("httpx.AsyncClient") as mock_http:
            result = await client.get_snapshots(["AAPL", "MSFT"])
            mock_http.assert_not_called()

        self.assertEqual(result, {})

    async def test_per_symbol_snapshot_skipped_when_forbidden(self):
        """get_snapshot (per-symbol) also short-circuits when forbidden."""
        from data.massive_client import MassiveClient
        client = MassiveClient()
        client._snapshot_forbidden = True

        with patch("httpx.AsyncClient") as mock_http:
            result = await client.get_snapshot("AAPL")
            mock_http.assert_not_called()

        self.assertEqual(result, {})

    async def test_forbidden_flag_not_set_on_non_403(self):
        """A 429 or 500 should NOT set _snapshot_forbidden."""
        from data.massive_client import MassiveClient
        client = MassiveClient()
        client._is_available = lambda: True

        mock_resp = MagicMock()
        mock_resp.status_code = 429

        with patch("httpx.AsyncClient") as mock_http:
            mock_http.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                get=AsyncMock(return_value=mock_resp)
            ))
            mock_http.return_value.__aexit__ = AsyncMock(return_value=False)
            await client.get_snapshots(["AAPL"])

        self.assertFalse(client._snapshot_forbidden)


if __name__ == "__main__":
    unittest.main()
