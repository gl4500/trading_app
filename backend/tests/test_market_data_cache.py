"""
Unit tests for data/market_data.py — MarketDataCache only.
MarketDataService is not unit-tested here because it depends on
alpaca_client, news_service, and signal_aggregator; those require
integration-style tests with mocked I/O.
"""
import sys
import os
import asyncio
import unittest

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


if __name__ == "__main__":
    unittest.main()
