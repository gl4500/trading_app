"""
Unit tests for data/tax_estimator.py and the get_filled_orders()
method on AlpacaClient. No live Alpaca API calls — all SDK calls mocked.
"""
import sys
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock
import asyncio

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
# Absolute fallback: project site-packages used when running from a git worktree
_SITE_ABS = r"C:\Users\gl450\trading_app\site-packages"
for _p in (_BACKEND, _SITE, _SITE_ABS):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

# Pre-seed sys.modules to prevent the module-level singleton from calling
# TradingClient() (which requires API credentials) during import.
# We replace the TradingClient name in the alpaca module namespace so that
# AlpacaClient.__init__'s call to TradingClient(...) uses our mock instead.
import unittest.mock as _mock

# Patch TradingClient and StockHistoricalDataClient at their source before
# trading.alpaca_client is first imported so the module-level singleton
# AlpacaClient() doesn't attempt a real API connection.
with _mock.patch.dict("sys.modules", {}):
    _tc_patcher  = _mock.patch("alpaca.trading.client.TradingClient")
    _hdc_patcher = _mock.patch("alpaca.data.historical.StockHistoricalDataClient")
    _tc_mock  = _tc_patcher.start()
    _hdc_mock = _hdc_patcher.start()
    _tc_mock.return_value  = MagicMock()
    _hdc_mock.return_value = MagicMock()
    try:
        import trading.alpaca_client as _alpaca_mod
        from trading.alpaca_client import AlpacaClient
    finally:
        _tc_patcher.stop()
        _hdc_patcher.stop()


# ── helpers ──────────────────────────────────────────────────────────────────

def _dt(year, month, day, hour=12):
    return datetime(year, month, day, hour, 0, 0, tzinfo=timezone.utc)


def _order(symbol, side, shares, price, filled_at):
    """Build a plain order dict as returned by get_filled_orders()."""
    return {
        "symbol": symbol,
        "side": side,      # "buy" or "sell"
        "shares": float(shares),
        "price": float(price),
        "filled_at": filled_at,
    }


# ── AlpacaClient.get_filled_orders() ─────────────────────────────────────────

class TestGetFilledOrders(unittest.IsolatedAsyncioTestCase):

    async def test_returns_filled_orders_for_year(self):
        """get_filled_orders(2025) returns one dict per filled buy/sell order."""
        mock_order = MagicMock()
        mock_order.symbol = "AAPL"
        mock_order.side.value = "buy"
        mock_order.filled_qty = "10"
        mock_order.filled_avg_price = "150.00"
        mock_order.filled_at = _dt(2025, 3, 1)

        client = AlpacaClient.__new__(AlpacaClient)
        client._trading = MagicMock()
        client._trading.get_orders = MagicMock(return_value=[mock_order])

        result = await client.get_filled_orders(2025)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["symbol"], "AAPL")
        self.assertEqual(result[0]["side"], "buy")
        self.assertAlmostEqual(result[0]["shares"], 10.0)
        self.assertAlmostEqual(result[0]["price"], 150.0)

    async def test_empty_year_returns_empty_list(self):
        """get_filled_orders returns [] when no orders exist."""
        client = AlpacaClient.__new__(AlpacaClient)
        client._trading = MagicMock()
        client._trading.get_orders = MagicMock(return_value=[])

        result = await client.get_filled_orders(2025)

        self.assertEqual(result, [])

    async def test_alpaca_error_raises(self):
        """get_filled_orders propagates exceptions so the endpoint can return 503."""
        client = AlpacaClient.__new__(AlpacaClient)
        client._trading = MagicMock()
        client._trading.get_orders = MagicMock(side_effect=Exception("API down"))

        with self.assertRaises(Exception):
            await client.get_filled_orders(2025)
