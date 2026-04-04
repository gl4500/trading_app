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
        # API returns yield_2_year / yield_10_year / yield_30_year field names
        c._economy_cache["treasury_yields"] = (1e15, {"yield_2_year": "4.80", "yield_10_year": "4.25", "yield_30_year": "4.50"})
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

    def test_flow_items_include_greeks(self):
        """Each flow result dict must expose delta, gamma, theta, vega, iv, open_interest."""
        c = MassiveClient()
        # Realistic Polygon.io options snapshot response with greeks
        api_result = {
            "details": {
                "contract_type": "call",
                "expiration_date": "2024-06-21",
                "strike_price": 190,
                "underlying_ticker": "AAPL",
            },
            "day": {"volume": 500, "vwap": 3.50},
            "greeks": {"delta": 0.55, "gamma": 0.012, "theta": -0.08, "vega": 0.18},
            "implied_volatility": 0.32,
            "open_interest": 8750,
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": [api_result]}
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
        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertAlmostEqual(item["delta"], 0.55)
        self.assertAlmostEqual(item["gamma"], 0.012)
        self.assertAlmostEqual(item["theta"], -0.08)
        self.assertAlmostEqual(item["vega"], 0.18)
        self.assertAlmostEqual(item["iv"], 0.32)
        self.assertEqual(item["open_interest"], 8750)


# ── Greeks summary ─────────────────────────────────────────────────────────────

class TestGreeksSummary(unittest.TestCase):

    def _make_flow_items(self):
        """Two CALL and one PUT for AAPL with greeks."""
        return [
            {
                "symbol": "AAPL", "side": "CALL",
                "delta": 0.60, "gamma": 0.01, "theta": -0.05, "vega": 0.20,
                "iv": 0.30, "open_interest": 5000, "premium": 150000,
                "details": {"strike_price": 185}, "day": {"volume": 200},
            },
            {
                "symbol": "AAPL", "side": "CALL",
                "delta": 0.45, "gamma": 0.015, "theta": -0.04, "vega": 0.15,
                "iv": 0.28, "open_interest": 3000, "premium": 90000,
                "details": {"strike_price": 190}, "day": {"volume": 150},
            },
            {
                "symbol": "AAPL", "side": "PUT",
                "delta": -0.35, "gamma": 0.01, "theta": -0.03, "vega": 0.12,
                "iv": 0.34, "open_interest": 2000, "premium": 50000,
                "details": {"strike_price": 180}, "day": {"volume": 100},
            },
        ]

    def test_get_greeks_summary_returns_per_symbol(self):
        c = MassiveClient()
        with patch.object(c, "get_options_flow", return_value=self._make_flow_items()):
            with patch("data.massive_client.MassiveClient._is_available", return_value=True):
                result = _run(c.get_greeks_summary(["AAPL"]))
        self.assertIn("AAPL", result)

    def test_greeks_summary_empty_without_key(self):
        c = MassiveClient()
        with patch("data.massive_client.config") as cfg:
            cfg.MASSIVE_API_KEY = ""
            result = _run(c.get_greeks_summary(["AAPL"]))
        self.assertEqual(result, {})

    def test_greeks_summary_avg_iv(self):
        """avg_iv should be volume-weighted average of iv across all contracts."""
        c = MassiveClient()
        items = self._make_flow_items()  # volumes: 200, 150, 100; ivs: 0.30, 0.28, 0.34
        expected_iv = (0.30 * 200 + 0.28 * 150 + 0.34 * 100) / (200 + 150 + 100)
        with patch.object(c, "get_options_flow", return_value=items):
            with patch("data.massive_client.MassiveClient._is_available", return_value=True):
                result = _run(c.get_greeks_summary(["AAPL"]))
        self.assertAlmostEqual(result["AAPL"]["avg_iv"], expected_iv, places=4)

    def test_greeks_summary_put_call_ratio(self):
        """put_call_ratio = total PUT volume / total CALL volume."""
        c = MassiveClient()
        items = self._make_flow_items()  # PUT vol=100, CALL vol=200+150=350
        with patch.object(c, "get_options_flow", return_value=items):
            with patch("data.massive_client.MassiveClient._is_available", return_value=True):
                result = _run(c.get_greeks_summary(["AAPL"]))
        self.assertAlmostEqual(result["AAPL"]["put_call_ratio"], 100 / 350, places=4)

    def test_greeks_summary_delta_bias_bullish(self):
        """delta_bias > 0 when CALL volume dominates with positive delta."""
        c = MassiveClient()
        items = self._make_flow_items()
        with patch.object(c, "get_options_flow", return_value=items):
            with patch("data.massive_client.MassiveClient._is_available", return_value=True):
                result = _run(c.get_greeks_summary(["AAPL"]))
        self.assertGreater(result["AAPL"]["delta_bias"], 0)

    def test_greeks_summary_high_oi_strike(self):
        """high_oi_strike should be the strike with the highest open_interest."""
        c = MassiveClient()
        items = self._make_flow_items()  # OIs: 5000@185, 3000@190, 2000@180 → max at 185
        with patch.object(c, "get_options_flow", return_value=items):
            with patch("data.massive_client.MassiveClient._is_available", return_value=True):
                result = _run(c.get_greeks_summary(["AAPL"]))
        self.assertEqual(result["AAPL"]["high_oi_strike"], 185)

    def test_format_greeks_for_prompt(self):
        """format_greeks_for_prompt returns a non-empty string with IV and P/C ratio."""
        from data.massive_client import format_greeks_for_prompt
        summary = {
            "avg_iv": 0.305,
            "delta_bias": 0.18,
            "put_call_ratio": 0.29,
            "high_oi_strike": 185,
            "call_volume": 350,
            "put_volume": 100,
        }
        text = format_greeks_for_prompt("AAPL", summary)
        self.assertIn("IV", text)
        self.assertIn("30.5%", text)
        self.assertIn("P/C", text)
        self.assertIn("bullish", text.lower())


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


class TestOptions403LogLevel(unittest.TestCase):
    """403 Forbidden on options endpoint must log at INFO, not WARNING."""

    def test_403_logs_info_not_warning(self):
        """First 403 response must use logger.info, not logger.warning."""
        import logging
        c = MassiveClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 403

        with patch("data.massive_client.config") as cfg, \
             patch("httpx.AsyncClient") as MockClient, \
             patch("data.massive_client.MassiveClient._is_available", return_value=True):
            cfg.MASSIVE_API_KEY = "key"
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.get = AsyncMock(return_value=mock_resp)
            MockClient.return_value = mock_ctx

            with self.assertLogs("data.massive_client", level="INFO") as log_ctx:
                _run(c._fetch_options_for_symbol("AAPL", 10))

        # Must have logged something
        self.assertTrue(len(log_ctx.records) > 0)
        # None of those records should be WARNING or above
        for record in log_ctx.records:
            self.assertLess(
                record.levelno, logging.WARNING,
                f"Expected INFO/DEBUG but got {record.levelname}: {record.message}"
            )

    def test_403_sets_options_forbidden_flag(self):
        """After a 403, _options_forbidden must be True so no further calls are made."""
        c = MassiveClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 403

        with patch("data.massive_client.config") as cfg, \
             patch("httpx.AsyncClient") as MockClient, \
             patch("data.massive_client.MassiveClient._is_available", return_value=True):
            cfg.MASSIVE_API_KEY = "key"
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.get = AsyncMock(return_value=mock_resp)
            MockClient.return_value = mock_ctx
            _run(c._fetch_options_for_symbol("AAPL", 10))

        self.assertTrue(c._options_forbidden)


if __name__ == "__main__":
    unittest.main()
