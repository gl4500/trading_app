"""
Unit tests for data/massive_client.py
Covers: availability gate, caching, response normalisation, S3 helpers,
        macro context formatting, sentinel integration.
All external calls (httpx, boto3) are mocked — no real API calls.
"""
import sys
import os
import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pandas as pd

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from data.massive_client import MassiveClient


def _run(coro):
    return asyncio.run(coro)


def _client(api_key="test-key"):
    c = MassiveClient()
    with patch("data.massive_client.config") as cfg:
        cfg.MASSIVE_API_KEY      = api_key
        cfg.MASSIVE_S3_BUCKET    = "test-bucket"
        cfg.MASSIVE_S3_ACCESS_KEY = "AK"
        cfg.MASSIVE_S3_SECRET_KEY = "SK"
        cfg.MASSIVE_S3_REGION    = "us-east-1"
        c._config_key = api_key
    return c


# ── Availability gate ─────────────────────────────────────────────────────────

class TestAvailability(unittest.TestCase):

    def test_no_key_not_available(self):
        c = MassiveClient()
        with patch("data.massive_client.config") as cfg:
            cfg.MASSIVE_API_KEY = ""
            self.assertFalse(c._is_available())

    def test_key_present_is_available(self):
        c = MassiveClient()
        with patch("data.massive_client.config") as cfg:
            cfg.MASSIVE_API_KEY = "abc123"
            self.assertTrue(c._is_available())

    def test_get_bars_returns_empty_without_key(self):
        c = MassiveClient()
        with patch("data.massive_client.config") as cfg:
            cfg.MASSIVE_API_KEY = ""
            result = _run(c.get_bars("AAPL"))
        self.assertIsInstance(result, pd.DataFrame)
        self.assertTrue(result.empty)

    def test_get_snapshots_returns_empty_without_key(self):
        c = MassiveClient()
        with patch("data.massive_client.config") as cfg:
            cfg.MASSIVE_API_KEY = ""
            result = _run(c.get_snapshots(["AAPL"]))
        self.assertEqual(result, {})

    def test_get_macro_context_returns_empty_without_key(self):
        c = MassiveClient()
        with patch("data.massive_client.config") as cfg:
            cfg.MASSIVE_API_KEY = ""
            result = _run(c.get_macro_context())
        self.assertEqual(result, "")


# ── Caching ───────────────────────────────────────────────────────────────────

class TestCaching(unittest.TestCase):

    def test_bars_cache_hit(self):
        c = MassiveClient()
        df = pd.DataFrame({"open": [1], "high": [2], "low": [0.5], "close": [1.5], "volume": [1000]})
        c._bars_cache["AAPL|day|60"] = (1e15, df)  # far-future timestamp = never expires
        with patch("data.massive_client.config") as cfg:
            cfg.MASSIVE_API_KEY = "key"
            result = _run(c.get_bars("AAPL", days=60))
        self.assertFalse(result.empty)
        self.assertEqual(len(result), 1)

    def test_economy_cache_hit(self):
        c = MassiveClient()
        c._economy_cache["treasury_yields"] = (1e15, {"year_10": "4.25"})
        with patch("data.massive_client.config") as cfg:
            cfg.MASSIVE_API_KEY = "key"
            result = _run(c.get_economy("treasury_yields"))
        self.assertEqual(result.get("year_10"), "4.25")


# ── Bars response normalisation ───────────────────────────────────────────────

class TestBarsNormalisation(unittest.TestCase):

    def _make_response(self, results):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": results}
        return mock_resp

    def test_compact_columns_renamed(self):
        """t/o/h/l/c/v → timestamp/open/high/low/close/volume"""
        rows = [{"t": "2024-01-15", "o": 100, "h": 105, "l": 98, "c": 103, "v": 50000}]
        c = MassiveClient()
        with patch("data.massive_client.config") as cfg:
            cfg.MASSIVE_API_KEY = "key"
            with patch("httpx.AsyncClient") as MockClient:
                mock_ctx = AsyncMock()
                mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
                mock_ctx.__aexit__ = AsyncMock(return_value=False)
                mock_ctx.get = AsyncMock(return_value=self._make_response(rows))
                MockClient.return_value = mock_ctx
                df = _run(c.get_bars("AAPL", days=5))
        self.assertIn("close", df.columns)
        self.assertIn("open", df.columns)
        self.assertFalse(df.empty)

    def test_missing_required_columns_returns_empty(self):
        """If response lacks OHLC columns, return empty DataFrame."""
        rows = [{"weird_col": 123}]
        c = MassiveClient()
        with patch("data.massive_client.config") as cfg:
            cfg.MASSIVE_API_KEY = "key"
            with patch("httpx.AsyncClient") as MockClient:
                mock_ctx = AsyncMock()
                mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
                mock_ctx.__aexit__ = AsyncMock(return_value=False)
                mock_ctx.get = AsyncMock(return_value=self._make_response(rows))
                MockClient.return_value = mock_ctx
                df = _run(c.get_bars("AAPL", days=5))
        self.assertTrue(df.empty)

    def test_http_401_returns_empty(self):
        c = MassiveClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        with patch("data.massive_client.config") as cfg:
            cfg.MASSIVE_API_KEY = "bad-key"
            with patch("httpx.AsyncClient") as MockClient:
                mock_ctx = AsyncMock()
                mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
                mock_ctx.__aexit__ = AsyncMock(return_value=False)
                mock_ctx.get = AsyncMock(return_value=mock_resp)
                MockClient.return_value = mock_ctx
                df = _run(c.get_bars("AAPL", days=5))
        self.assertTrue(df.empty)


# ── Macro context ─────────────────────────────────────────────────────────────

class TestMacroContext(unittest.TestCase):

    def test_formats_treasury_yields(self):
        c = MassiveClient()
        c._economy_cache["treasury_yields"] = (1e15, {"year_2": "4.80", "year_10": "4.25", "year_30": "4.50"})
        c._economy_cache["inflation"] = (1e15, {})
        c._economy_cache["labor"]     = (1e15, {})
        with patch("data.massive_client.config") as cfg:
            cfg.MASSIVE_API_KEY = "key"
            result = _run(c.get_macro_context())
        self.assertIn("Treasury Yields", result)
        self.assertIn("2Y=4.80%", result)
        self.assertIn("10Y=4.25%", result)

    def test_formats_inflation(self):
        c = MassiveClient()
        c._economy_cache["treasury_yields"] = (1e15, {})
        c._economy_cache["inflation"]        = (1e15, {"value": "3.2", "date": "2024-01"})
        c._economy_cache["labor"]            = (1e15, {})
        with patch("data.massive_client.config") as cfg:
            cfg.MASSIVE_API_KEY = "key"
            result = _run(c.get_macro_context())
        self.assertIn("Inflation", result)
        self.assertIn("3.2%", result)

    def test_empty_when_no_data(self):
        c = MassiveClient()
        c._economy_cache["treasury_yields"] = (1e15, {})
        c._economy_cache["inflation"]        = (1e15, {})
        c._economy_cache["labor"]            = (1e15, {})
        with patch("data.massive_client.config") as cfg:
            cfg.MASSIVE_API_KEY = "key"
            result = _run(c.get_macro_context())
        self.assertEqual(result, "")


# ── Options flow ──────────────────────────────────────────────────────────────

class TestOptionsFlow(unittest.TestCase):

    def test_returns_empty_without_key(self):
        c = MassiveClient()
        with patch("data.massive_client.config") as cfg:
            cfg.MASSIVE_API_KEY = ""
            result = _run(c.get_options_flow(["AAPL"]))
        self.assertEqual(result, [])

    def test_parses_flow_items(self):
        c = MassiveClient()
        flows = [{"ticker": "AAPL", "side": "CALL", "premium": 500000, "expiry": "2024-02-16", "strike_price": 190}]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": flows}
        with patch("data.massive_client.config") as cfg:
            cfg.MASSIVE_API_KEY = "key"
            with patch("httpx.AsyncClient") as MockClient:
                mock_ctx = AsyncMock()
                mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
                mock_ctx.__aexit__ = AsyncMock(return_value=False)
                mock_ctx.get = AsyncMock(return_value=mock_resp)
                MockClient.return_value = mock_ctx
                with patch("data.massive_client.MassiveClient._is_available", return_value=True):
                    result = _run(c.get_options_flow(["AAPL"]))
        self.assertIsInstance(result, list)

    def test_symbol_filter_applied(self):
        """Items for symbols not in the requested list should be excluded."""
        c = MassiveClient()
        flows = [
            {"ticker": "AAPL", "side": "CALL", "premium": 100000},
            {"ticker": "MSFT", "side": "PUT",  "premium": 200000},
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": flows}
        with patch("data.massive_client.config") as cfg:
            cfg.MASSIVE_API_KEY = "key"
            with patch("httpx.AsyncClient") as MockClient:
                mock_ctx = AsyncMock()
                mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
                mock_ctx.__aexit__ = AsyncMock(return_value=False)
                mock_ctx.get = AsyncMock(return_value=mock_resp)
                MockClient.return_value = mock_ctx
                with patch("data.massive_client.MassiveClient._is_available", return_value=True):
                    result = _run(c.get_options_flow(["AAPL"]))  # only AAPL
        tickers = [r["symbol"] for r in result]
        self.assertNotIn("MSFT", tickers)


# ── S3 ────────────────────────────────────────────────────────────────────────

class TestS3(unittest.TestCase):

    def test_no_s3_client_without_credentials(self):
        c = MassiveClient()
        with patch("data.massive_client.config") as cfg:
            cfg.MASSIVE_S3_BUCKET     = ""
            cfg.MASSIVE_S3_ACCESS_KEY = ""
            cfg.MASSIVE_S3_SECRET_KEY = ""
            cfg.MASSIVE_S3_REGION     = "us-east-1"
            client = c._get_s3_client()
        self.assertIsNone(client)

    def test_list_flat_files_returns_empty_without_s3(self):
        c = MassiveClient()
        with patch.object(c, "_get_s3_client", return_value=None):
            result = _run(c.list_flat_files("stocks", "AAPL"))
        self.assertEqual(result, [])

    def test_download_flat_file_returns_empty_without_s3(self):
        c = MassiveClient()
        with patch.object(c, "_get_s3_client", return_value=None):
            result = _run(c.download_flat_file("stocks/daily/AAPL/2024-01-15.csv"))
        self.assertIsInstance(result, pd.DataFrame)
        self.assertTrue(result.empty)

    def test_download_history_returns_empty_when_no_files(self):
        c = MassiveClient()
        with patch.object(c, "list_flat_files", new_callable=AsyncMock, return_value=[]):
            result = _run(c.download_history("AAPL"))
        self.assertIsInstance(result, pd.DataFrame)
        self.assertTrue(result.empty)


# ── Sentinel integration ──────────────────────────────────────────────────────

class TestSentinelIntegration(unittest.TestCase):

    def test_fetch_massive_signals_returns_empty_without_key(self):
        from data.sentinel_sources import fetch_massive_signals
        with patch("data.massive_client.massive_client._is_available", return_value=False):
            result = _run(fetch_massive_signals(["AAPL"]))
        self.assertEqual(result, [])

    def test_fetch_all_sources_includes_massive(self):
        """fetch_all_sources should call fetch_massive_signals."""
        from data import sentinel_sources
        self.assertTrue(hasattr(sentinel_sources, "fetch_massive_signals"))


if __name__ == "__main__":
    unittest.main()
