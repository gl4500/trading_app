"""
Unit tests for data/news_service.py — retry, circuit breaker, and timeout.

Mocks the synchronous Alpaca client call (`_fetch_news_sync`) so no real
network I/O happens.
"""
import sys
import os
import time
import logging
import unittest
from unittest.mock import patch

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from data import news_service as ns_mod
from data.news_service import NewsService, _is_retryable


class TestRetryClassifier(unittest.TestCase):
    def test_502_is_retryable(self):
        self.assertTrue(_is_retryable(Exception("HTTP 502 Bad Gateway")))

    def test_503_is_retryable(self):
        self.assertTrue(_is_retryable(Exception("503 Service Unavailable")))

    def test_504_is_retryable(self):
        self.assertTrue(_is_retryable(Exception("504 Gateway Timeout")))

    def test_connect_timeout_is_retryable(self):
        self.assertTrue(_is_retryable(Exception(
            "Caused by ConnectTimeoutError(<...>, 'Connection to data.alpaca.markets timed out.')"
        )))

    def test_read_timeout_is_retryable(self):
        self.assertTrue(_is_retryable(Exception("HTTPSConnectionPool: ReadTimeoutError")))

    def test_4xx_not_retryable(self):
        self.assertFalse(_is_retryable(Exception("HTTP 401 Unauthorized")))

    def test_random_error_not_retryable(self):
        self.assertFalse(_is_retryable(Exception("KeyError: 'symbol'")))


class TestNewsServiceRetry(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.svc = NewsService()

    async def test_caches_successful_fetch(self):
        with patch.object(self.svc, "_fetch_news_sync", return_value=[{"headline": "A"}]) as m:
            r1 = await self.svc.get_news("AAA")
            r2 = await self.svc.get_news("AAA")
        self.assertEqual(r1, r2)
        self.assertEqual(len(r1), 1)
        # second call hit the cache
        self.assertEqual(m.call_count, 1)

    async def test_retries_once_on_transient_502(self):
        attempts = []

        def fake(sym):
            attempts.append(sym)
            if len(attempts) == 1:
                raise Exception("502 Bad Gateway")
            return [{"headline": "OK"}]

        with patch.object(self.svc, "_fetch_news_sync", side_effect=fake):
            r = await self.svc.get_news("AAA")

        self.assertEqual(len(attempts), 2)
        self.assertEqual(len(r), 1)

    async def test_does_not_retry_on_non_retryable_error(self):
        attempts = []

        def fake(sym):
            attempts.append(sym)
            raise Exception("HTTP 401 Unauthorized")

        with patch.object(self.svc, "_fetch_news_sync", side_effect=fake):
            r = await self.svc.get_news("AAA")

        self.assertEqual(len(attempts), 1)   # no retry
        self.assertEqual(r, [])

    async def test_returns_empty_list_after_persistent_failure(self):
        with patch.object(self.svc, "_fetch_news_sync", side_effect=Exception("502")):
            r = await self.svc.get_news("AAA")
        self.assertEqual(r, [])

    async def test_returns_stale_cache_when_fetch_fails(self):
        with patch.object(self.svc, "_fetch_news_sync", return_value=[{"headline": "old"}]):
            await self.svc.get_news("AAA")
        # Force cache expiry
        ts, articles = self.svc._cache["AAA"]
        self.svc._cache["AAA"] = (ts - ns_mod.NEWS_CACHE_TTL - 10, articles)

        with patch.object(self.svc, "_fetch_news_sync", side_effect=Exception("502")):
            r = await self.svc.get_news("AAA")
        self.assertEqual(r, [{"headline": "old"}])

    async def test_logs_at_warning_not_error(self):
        with patch.object(self.svc, "_fetch_news_sync", side_effect=Exception("502")):
            with self.assertLogs("data.news_service", level="WARNING") as cm:
                await self.svc.get_news("AAA")

        levels = [rec.levelno for rec in cm.records]
        self.assertIn(logging.WARNING, levels)
        self.assertNotIn(logging.ERROR, levels)


class TestCircuitBreaker(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.svc = NewsService()

    async def test_opens_after_threshold_consecutive_failures(self):
        attempts = []

        def fake(sym):
            attempts.append(sym)
            raise Exception("502")

        with patch.object(self.svc, "_fetch_news_sync", side_effect=fake):
            for sym in [f"S{i}" for i in range(ns_mod.BREAKER_THRESHOLD + 3)]:
                await self.svc.get_news(sym)

        # Once breaker opens, subsequent fetches short-circuit (no upstream call).
        # Each attempted call retries once -> 2 attempts; capped at BREAKER_THRESHOLD calls.
        self.assertLessEqual(len(attempts), ns_mod.BREAKER_THRESHOLD * 2)
        self.assertTrue(self.svc._breaker_is_open())

    async def test_breaker_serves_stale_cache_when_open(self):
        # Seed cache for AAA via a successful call
        with patch.object(self.svc, "_fetch_news_sync", return_value=[{"headline": "cached"}]):
            await self.svc.get_news("AAA")

        # Manually open the breaker
        self.svc._breaker_open_until = time.time() + 60.0
        # Expire the cache so we'd normally hit upstream
        ts, articles = self.svc._cache["AAA"]
        self.svc._cache["AAA"] = (ts - ns_mod.NEWS_CACHE_TTL - 10, articles)

        # Fetch should short-circuit and return stale cache, not call upstream
        with patch.object(self.svc, "_fetch_news_sync") as m:
            r = await self.svc.get_news("AAA")
        m.assert_not_called()
        self.assertEqual(r, [{"headline": "cached"}])

    async def test_success_resets_breaker(self):
        # Trip the failure counter halfway
        with patch.object(self.svc, "_fetch_news_sync", side_effect=Exception("502")):
            await self.svc.get_news("AAA")
        self.assertEqual(self.svc._consecutive_failures, 1)

        # A success then resets it
        with patch.object(self.svc, "_fetch_news_sync", return_value=[{"headline": "ok"}]):
            await self.svc.get_news("BBB")
        self.assertEqual(self.svc._consecutive_failures, 0)
        self.assertEqual(self.svc._breaker_open_until, 0.0)


if __name__ == "__main__":
    unittest.main()
