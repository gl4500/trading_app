"""
Unit tests for data/tax_estimator.py and AlpacaClient.get_filled_orders().
No live Alpaca API calls — all SDK calls mocked.
data/tax_estimator.py tests are added in subsequent tasks.
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
        self.assertEqual(result[0]["filled_at"], _dt(2025, 3, 1))

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

    async def test_orders_with_none_filled_qty_are_skipped(self):
        """Orders with filled_qty=None (e.g. cancelled-but-closed) are skipped."""
        mock_none_order = MagicMock()
        mock_none_order.filled_qty = None
        mock_none_order.filled_avg_price = "150.00"

        client = AlpacaClient.__new__(AlpacaClient)
        client._trading = MagicMock()
        client._trading.get_orders = MagicMock(return_value=[mock_none_order])

        result = await client.get_filled_orders(2025)
        self.assertEqual(result, [])


# ── TaxEstimator — FIFO pairing and holding period ───────────────────────────

from data.tax_estimator import TaxEstimator


class TestFifoPairing(unittest.TestCase):

    def test_short_term_gain(self):
        """Sell within 365 days → classified short-term, gain correct."""
        orders = [
            _order("AAPL", "buy",  10, 100.0, _dt(2025, 1, 10)),
            _order("AAPL", "sell", 10, 120.0, _dt(2025, 6, 10)),  # 150 days
        ]
        est = TaxEstimator(orders)
        result = est.summarize(2025)
        self.assertAlmostEqual(result["short_term"]["gains"], 200.0)
        self.assertAlmostEqual(result["short_term"]["net"],   200.0)
        self.assertAlmostEqual(result["long_term"]["gains"],    0.0)
        self.assertAlmostEqual(result["total_net"],           200.0)

    def test_long_term_gain(self):
        """Sell after 365 days → classified long-term."""
        orders = [
            _order("AAPL", "buy",  10, 100.0, _dt(2023, 1, 1)),
            _order("AAPL", "sell", 10, 150.0, _dt(2025, 3, 1)),  # ~2 years
        ]
        est = TaxEstimator(orders)
        result = est.summarize(2025)
        self.assertAlmostEqual(result["long_term"]["gains"],  500.0)
        self.assertAlmostEqual(result["short_term"]["gains"],   0.0)

    def test_loss_offset(self):
        """Net is gains minus losses."""
        orders = [
            _order("AAPL", "buy",  10, 100.0, _dt(2025, 1, 1)),
            _order("AAPL", "sell", 10,  80.0, _dt(2025, 3, 1)),   # -$200 loss
        ]
        est = TaxEstimator(orders)
        result = est.summarize(2025)
        self.assertAlmostEqual(result["short_term"]["losses"], 200.0)
        self.assertAlmostEqual(result["short_term"]["net"],   -200.0)
        self.assertAlmostEqual(result["total_net"],           -200.0)

    def test_fifo_partial_lot(self):
        """Sell spans two buy lots — each classified independently."""
        orders = [
            _order("AAPL", "buy",  5, 100.0, _dt(2023, 1, 1)),   # lot 1: long-term by 2025-06-01
            _order("AAPL", "buy",  5, 110.0, _dt(2025, 1, 15)),  # lot 2: short-term in 2025
            _order("AAPL", "sell", 10, 130.0, _dt(2025, 6, 1)),
        ]
        est = TaxEstimator(orders)
        result = est.summarize(2025)
        # lot 1: (130-100)*5 = 150 long-term
        # lot 2: (130-110)*5 = 100 short-term
        self.assertAlmostEqual(result["long_term"]["gains"],  150.0)
        self.assertAlmostEqual(result["short_term"]["gains"], 100.0)
        self.assertAlmostEqual(result["total_net"],           250.0)

    def test_mixed_symbols(self):
        """AAPL and TSLA lots are tracked independently."""
        orders = [
            _order("AAPL", "buy",  10, 100.0, _dt(2025, 1, 1)),
            _order("TSLA", "buy",  10, 200.0, _dt(2025, 1, 1)),
            _order("AAPL", "sell", 10, 120.0, _dt(2025, 4, 1)),  # +200
            _order("TSLA", "sell", 10, 180.0, _dt(2025, 4, 1)),  # -200
        ]
        est = TaxEstimator(orders)
        result = est.summarize(2025)
        self.assertAlmostEqual(result["short_term"]["gains"],  200.0)
        self.assertAlmostEqual(result["short_term"]["losses"], 200.0)
        self.assertAlmostEqual(result["short_term"]["net"],      0.0)

    def test_empty_year_returns_zeros(self):
        """No trades for the requested year → all zeros, no crash."""
        orders = [
            _order("AAPL", "buy",  10, 100.0, _dt(2024, 1, 1)),
            _order("AAPL", "sell", 10, 120.0, _dt(2024, 6, 1)),
        ]
        est = TaxEstimator(orders)
        result = est.summarize(2025)
        self.assertEqual(result["total_net"], 0.0)
        self.assertEqual(result["trades_analyzed"], 0)

    def test_year_filter(self):
        """Trades from other years are excluded from the summary."""
        orders = [
            _order("AAPL", "buy",  10, 100.0, _dt(2024, 1, 1)),
            _order("AAPL", "sell", 10, 150.0, _dt(2024, 6, 1)),  # 2024 — excluded
            _order("AAPL", "buy",  10, 110.0, _dt(2024, 12, 1)),
            _order("AAPL", "sell", 10, 130.0, _dt(2025, 3, 1)),  # 2025 — included
        ]
        est = TaxEstimator(orders)
        result = est.summarize(2025)
        self.assertEqual(result["trades_analyzed"], 1)
        self.assertAlmostEqual(result["short_term"]["gains"], 200.0)  # (130-110)*10
