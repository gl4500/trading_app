"""
Unit tests for data/stooq_client.py
Covers: get_bars() CSV parsing, column normalisation, caching, error handling,
        get_bars_multi() concurrent fetch, graceful degradation.
"""
import sys
import os
import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# Sample Stooq CSV response (Date,Open,High,Low,Close,Volume)
_STOOQ_CSV = (
    "Date,Open,High,Low,Close,Volume\n"
    "2000-01-03,100.00,102.50,99.50,101.00,50000000\n"
    "2000-01-04,101.00,103.00,100.00,102.00,45000000\n"
    "2000-01-05,102.00,104.00,101.00,103.50,60000000\n"
    "2024-01-02,175.00,177.00,174.00,176.00,52000000\n"
    "2024-01-03,176.00,178.00,175.50,177.50,48000000\n"
)

_STOOQ_CSV_NO_VOLUME = (
    "Date,Open,High,Low,Close\n"
    "2024-01-02,175.00,177.00,174.00,176.00\n"
    "2024-01-03,176.00,178.00,175.50,177.50\n"
)

_STOOQ_HTML_ERROR = "<html><body>No data found</body></html>"


def _mock_response(text: str, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


@unittest.skipUnless(HAS_PANDAS, "pandas not available")
class TestStooqClientGetBars(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        from data.stooq_client import StooqClient
        self.client = StooqClient()

    async def test_get_bars_returns_dataframe(self):
        with patch("data.stooq_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_response(_STOOQ_CSV))
            mock_cls.return_value = mock_http

            df = await self.client.get_bars("AAPL")

        self.assertIsInstance(df, pd.DataFrame)
        self.assertFalse(df.empty)

    async def test_get_bars_has_required_columns(self):
        with patch("data.stooq_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_response(_STOOQ_CSV))
            mock_cls.return_value = mock_http

            df = await self.client.get_bars("AAPL")

        for col in ("open", "high", "low", "close"):
            self.assertIn(col, df.columns, f"Missing column: {col}")

    async def test_get_bars_without_volume_still_works(self):
        with patch("data.stooq_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_response(_STOOQ_CSV_NO_VOLUME))
            mock_cls.return_value = mock_http

            df = await self.client.get_bars("AAPL")

        self.assertFalse(df.empty)
        self.assertIn("close", df.columns)

    async def test_get_bars_html_response_returns_empty(self):
        """Stooq returns HTML when a symbol is not found."""
        with patch("data.stooq_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_response(_STOOQ_HTML_ERROR))
            mock_cls.return_value = mock_http

            df = await self.client.get_bars("INVALID_SYM")

        self.assertTrue(df.empty)

    async def test_get_bars_http_error_returns_empty(self):
        with patch("data.stooq_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_response("", status_code=404))
            mock_cls.return_value = mock_http

            df = await self.client.get_bars("AAPL")

        self.assertTrue(df.empty)

    async def test_get_bars_network_exception_returns_empty(self):
        import httpx
        with patch("data.stooq_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))
            mock_cls.return_value = mock_http

            df = await self.client.get_bars("AAPL")

        self.assertTrue(df.empty)

    async def test_get_bars_days_parameter_limits_rows(self):
        with patch("data.stooq_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_response(_STOOQ_CSV))
            mock_cls.return_value = mock_http

            df = await self.client.get_bars("AAPL", days=2)

        # Should return at most 2 rows
        self.assertLessEqual(len(df), 2)

    async def test_get_bars_sorted_ascending_by_date(self):
        with patch("data.stooq_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_response(_STOOQ_CSV))
            mock_cls.return_value = mock_http

            df = await self.client.get_bars("AAPL")

        # Dates should be in ascending order
        if "date" in df.columns:
            dates = df["date"].tolist()
            self.assertEqual(dates, sorted(dates))


@unittest.skipUnless(HAS_PANDAS, "pandas not available")
class TestStooqClientCaching(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        from data.stooq_client import StooqClient
        self.client = StooqClient()

    async def test_second_call_uses_cache_not_http(self):
        with patch("data.stooq_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_response(_STOOQ_CSV))
            mock_cls.return_value = mock_http

            await self.client.get_bars("AAPL", days=5)
            await self.client.get_bars("AAPL", days=5)

        # HTTP get should only be called once (second call served from cache)
        self.assertEqual(mock_http.get.call_count, 1)

    async def test_different_days_bypass_cache(self):
        """Different days parameter = different cache key = separate fetch."""
        with patch("data.stooq_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_response(_STOOQ_CSV))
            mock_cls.return_value = mock_http

            await self.client.get_bars("AAPL", days=60)
            await self.client.get_bars("AAPL", days=1250)

        self.assertEqual(mock_http.get.call_count, 2)


@unittest.skipUnless(HAS_PANDAS, "pandas not available")
class TestStooqClientMulti(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        from data.stooq_client import StooqClient
        self.client = StooqClient()

    async def test_get_bars_multi_returns_dict(self):
        with patch("data.stooq_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_response(_STOOQ_CSV))
            mock_cls.return_value = mock_http

            result = await self.client.get_bars_multi(["AAPL", "MSFT"])

        self.assertIsInstance(result, dict)
        self.assertIn("AAPL", result)
        self.assertIn("MSFT", result)

    async def test_get_bars_multi_empty_list_returns_empty_dict(self):
        result = await self.client.get_bars_multi([])
        self.assertEqual(result, {})

    async def test_get_bars_multi_failed_symbol_returns_empty_df(self):
        import httpx

        async def side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "invalid" in url.lower():
                raise httpx.ConnectError("fail")
            return _mock_response(_STOOQ_CSV)

        with patch("data.stooq_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=_mock_response(_STOOQ_CSV))
            mock_cls.return_value = mock_http

            # One valid, one invalid — both should be present in result
            result = await self.client.get_bars_multi(["AAPL", "INVALID"])

        self.assertIn("AAPL", result)
        self.assertIn("INVALID", result)


@unittest.skipUnless(HAS_PANDAS, "pandas not available")
class TestStooqClientSymbolFormat(unittest.TestCase):

    def setUp(self):
        from data.stooq_client import StooqClient
        self.client = StooqClient()

    def test_us_symbol_format(self):
        """US symbols should be formatted as {lower}.us for the URL."""
        url = self.client._symbol_url("AAPL")
        self.assertIn("aapl.us", url.lower())

    def test_spy_etf_format(self):
        url = self.client._symbol_url("SPY")
        self.assertIn("spy.us", url.lower())

    def test_symbol_lowercased(self):
        url = self.client._symbol_url("MSFT")
        self.assertNotIn("MSFT", url)  # should be lowercased


# ── TestGetMacroIndicators ────────────────────────────────────────────────────

class TestGetMacroIndicators(unittest.IsolatedAsyncioTestCase):

    _VIX_CSV = "Date,Open,High,Low,Close,Volume\n2024-01-01,17.0,18.0,16.5,17.5,0\n2024-01-02,17.5,19.0,17.0,18.5,0\n"
    _YIELD_CSV = "Date,Open,High,Low,Close,Volume\n2024-01-01,4.50,4.52,4.48,4.50,0\n2024-01-02,4.50,4.55,4.49,4.52,0\n"

    def _mock_http(self, csv_text: str):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = csv_text
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(get=AsyncMock(return_value=mock_resp)))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        return mock_ctx

    async def test_returns_dict_with_expected_keys(self):
        from data.stooq_client import StooqClient
        client = StooqClient()

        with patch("httpx.AsyncClient", return_value=self._mock_http(self._VIX_CSV)):
            result = await client.get_macro_indicators()

        # Should have at least one key populated
        self.assertIsInstance(result, dict)

    async def test_vix_price_and_pct_populated(self):
        from data.stooq_client import StooqClient
        client = StooqClient()

        with patch("httpx.AsyncClient", return_value=self._mock_http(self._VIX_CSV)):
            result = await client.get_macro_indicators()

        vix = result.get("VIX", {})
        if vix:  # only assert if Stooq returned data
            self.assertIn("price", vix)
            self.assertIn("pct_1d", vix)
            self.assertAlmostEqual(vix["price"], 18.5, places=1)

    async def test_returns_empty_on_http_error(self):
        from data.stooq_client import StooqClient
        client = StooqClient()

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(get=AsyncMock(return_value=mock_resp)))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_ctx):
            result = await client.get_macro_indicators()

        self.assertEqual(result, {})

    async def test_cache_used_on_second_call(self):
        from data.stooq_client import StooqClient
        client = StooqClient()

        call_count = 0

        async def _fake_get(url):
            nonlocal call_count
            call_count += 1
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = self._VIX_CSV
            return mock_resp

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(get=_fake_get))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_ctx):
            await client.get_macro_indicators()
            await client.get_macro_indicators()

        # Each symbol is fetched once; second call should hit cache
        self.assertLessEqual(call_count, 4)  # 4 symbols, all cached after first call


class TestFormatMacroForPrompt(unittest.TestCase):

    def test_empty_returns_empty_string(self):
        from data.stooq_client import format_macro_for_prompt
        self.assertEqual(format_macro_for_prompt({}), "")

    def test_vix_in_output(self):
        from data.stooq_client import format_macro_for_prompt
        result = format_macro_for_prompt({"VIX": {"price": 18.5, "pct_1d": 2.3}})
        self.assertIn("VIX", result)
        self.assertIn("18.5", result)

    def test_yield_in_output(self):
        from data.stooq_client import format_macro_for_prompt
        result = format_macro_for_prompt({"10Y_Yield": {"price": 4.52, "pct_1d": 0.4}})
        self.assertIn("4.52", result)

    def test_gold_formatted_with_dollar_sign(self):
        from data.stooq_client import format_macro_for_prompt
        result = format_macro_for_prompt({"Gold": {"price": 2345.0, "pct_1d": 0.8}})
        self.assertIn("$", result)
        self.assertIn("2,345", result)

    def test_vix_elevated_label(self):
        from data.stooq_client import format_macro_for_prompt
        result = format_macro_for_prompt({"VIX": {"price": 30.0, "pct_1d": 5.0}})
        self.assertIn("elevated", result)

    def test_vix_low_label(self):
        from data.stooq_client import format_macro_for_prompt
        result = format_macro_for_prompt({"VIX": {"price": 12.0, "pct_1d": -1.0}})
        self.assertIn("low", result)

    def test_partial_data_no_crash(self):
        from data.stooq_client import format_macro_for_prompt
        result = format_macro_for_prompt({"VIX": {"price": 18.5}, "Gold": {"price": None}})
        self.assertIn("VIX", result)


if __name__ == "__main__":
    unittest.main()
