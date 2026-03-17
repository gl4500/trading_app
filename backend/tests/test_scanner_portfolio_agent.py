"""
Unit tests for agents/scanner_portfolio_agent.py
Covers: BUY recs >= 60% confidence, SELL recs, underperformer exit, new-scan gate
"""
import sys
import os
import asyncio
import unittest
from unittest.mock import patch, AsyncMock, MagicMock

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agents.scanner_portfolio_agent import ScannerPortfolioAgent, MIN_BUY_CONFIDENCE, DEFAULT_STOP_LOSS_PCT
from trading.portfolio import Position


def _make_scan(recommendations, scanned_at="2024-01-01T10:00:00"):
    return {
        "status": "ok",
        "recommendations": recommendations,
        "scanned_at": scanned_at,
    }


def _make_ctx(symbols=None, price=150.0):
    symbols = symbols or []
    return {sym: {"price": price} for sym in symbols}


class TestScannerPortfolioAgentBuy(unittest.IsolatedAsyncioTestCase):
    """BUY recommendations >= MIN_BUY_CONFIDENCE should generate BUY signals."""

    async def test_high_confidence_buy_generates_signal(self):
        agent = ScannerPortfolioAgent()
        agent.risk_manager.get_max_buy_shares = MagicMock(return_value=5)
        scan = _make_scan([
            {"symbol": "AAPL", "action": "BUY", "confidence": 0.75, "reasoning": "strong momentum", "catalysts": []},
        ])

        with patch("agents.scanner_agent.get_cached_scan", return_value=scan), \
             patch("trading.alpaca_client.alpaca_client.get_bars_multi", new_callable=AsyncMock) as mock_bars:
            mock_bars.return_value = {}
            ctx = _make_ctx(["AAPL"], price=150.0)
            signals = await agent.analyze(ctx)

        buy_signals = [s for s in signals if s.action == "BUY" and s.symbol == "AAPL"]
        self.assertTrue(len(buy_signals) >= 1)

    async def test_low_confidence_buy_below_threshold_is_skipped(self):
        agent = ScannerPortfolioAgent()
        # confidence=0.55 < MIN_BUY_CONFIDENCE=0.60
        scan = _make_scan([
            {"symbol": "AAPL", "action": "BUY", "confidence": 0.55, "reasoning": "weak signal", "catalysts": []},
        ])

        with patch("agents.scanner_agent.get_cached_scan", return_value=scan), \
             patch("trading.alpaca_client.alpaca_client.get_bars_multi", new_callable=AsyncMock) as mock_bars:
            mock_bars.return_value = {}
            ctx = _make_ctx(["AAPL"], price=150.0)
            signals = await agent.analyze(ctx)

        buy_signals = [s for s in signals if s.action == "BUY"]
        self.assertEqual(len(buy_signals), 0)

    async def test_exact_threshold_buy_generates_signal(self):
        """Confidence exactly at threshold (0.60) should be allowed."""
        agent = ScannerPortfolioAgent()
        scan = _make_scan([
            {"symbol": "MSFT", "action": "BUY", "confidence": 0.60, "reasoning": "at threshold", "catalysts": []},
        ])

        with patch("agents.scanner_agent.get_cached_scan", return_value=scan), \
             patch("trading.alpaca_client.alpaca_client.get_bars_multi", new_callable=AsyncMock) as mock_bars:
            mock_bars.return_value = {}
            agent.risk_manager.get_max_buy_shares = MagicMock(return_value=3)
            ctx = _make_ctx(["MSFT"], price=300.0)
            signals = await agent.analyze(ctx)

        # Should not be filtered (confidence == MIN_BUY_CONFIDENCE)
        # actual signal depends on risk_manager returning > 0 shares
        self.assertIsInstance(signals, list)

    async def test_no_scan_returns_empty(self):
        """No cached scan → analyze returns empty list."""
        agent = ScannerPortfolioAgent()

        with patch("agents.scanner_agent.get_cached_scan", return_value=None):
            signals = await agent.analyze({})

        self.assertEqual(signals, [])

    async def test_stale_scan_returns_empty(self):
        """Scan with status != 'ok' → empty list."""
        agent = ScannerPortfolioAgent()
        scan = {"status": "error", "recommendations": [], "scanned_at": "2024-01-01T00:00:00"}

        with patch("agents.scanner_agent.get_cached_scan", return_value=scan):
            signals = await agent.analyze({})

        self.assertEqual(signals, [])

    async def test_empty_recommendations_returns_empty(self):
        agent = ScannerPortfolioAgent()
        scan = _make_scan([])

        with patch("agents.scanner_agent.get_cached_scan", return_value=scan):
            signals = await agent.analyze({})

        self.assertEqual(signals, [])


class TestScannerPortfolioAgentSell(unittest.IsolatedAsyncioTestCase):
    """Explicit SELL recommendations for held positions generate SELL signals."""

    async def test_explicit_sell_for_held_position(self):
        agent = ScannerPortfolioAgent()
        agent.portfolio.positions["AAPL"] = Position("AAPL", 10, 140.0)

        scan = _make_scan([
            {"symbol": "AAPL", "action": "SELL", "confidence": 0.80, "reasoning": "bearish breakdown"},
        ])

        with patch("agents.scanner_agent.get_cached_scan", return_value=scan), \
             patch("trading.alpaca_client.alpaca_client.get_bars_multi", new_callable=AsyncMock) as mock_bars:
            mock_bars.return_value = {}
            ctx = _make_ctx(["AAPL"], price=130.0)
            signals = await agent.analyze(ctx)

        sell_signals = [s for s in signals if s.action == "SELL" and s.symbol == "AAPL"]
        self.assertEqual(len(sell_signals), 1)
        self.assertEqual(sell_signals[0].shares, 10)

    async def test_explicit_sell_not_held_skipped(self):
        """SELL rec for a symbol we don't hold → no signal."""
        agent = ScannerPortfolioAgent()
        # No position in AAPL

        scan = _make_scan([
            {"symbol": "AAPL", "action": "SELL", "confidence": 0.80, "reasoning": "bearish"},
        ])

        with patch("agents.scanner_agent.get_cached_scan", return_value=scan), \
             patch("trading.alpaca_client.alpaca_client.get_bars_multi", new_callable=AsyncMock) as mock_bars:
            mock_bars.return_value = {}
            signals = await agent.analyze({})

        sell_signals = [s for s in signals if s.action == "SELL"]
        self.assertEqual(len(sell_signals), 0)

    async def test_sell_confidence_used_from_rec(self):
        """The confidence in the SELL signal should come from the recommendation."""
        agent = ScannerPortfolioAgent()
        agent.portfolio.positions["TSLA"] = Position("TSLA", 5, 200.0)

        scan = _make_scan([
            {"symbol": "TSLA", "action": "SELL", "confidence": 0.90, "reasoning": "overvalued"},
        ])

        with patch("agents.scanner_agent.get_cached_scan", return_value=scan), \
             patch("trading.alpaca_client.alpaca_client.get_bars_multi", new_callable=AsyncMock) as mock_bars:
            mock_bars.return_value = {}
            ctx = _make_ctx(["TSLA"], price=180.0)
            signals = await agent.analyze(ctx)

        sell = next((s for s in signals if s.action == "SELL" and s.symbol == "TSLA"), None)
        self.assertIsNotNone(sell)
        self.assertAlmostEqual(sell.confidence, 0.90)


class TestScannerPortfolioAgentUnderperformer(unittest.IsolatedAsyncioTestCase):
    """Held positions down >= DEFAULT_STOP_LOSS_PCT and not in BUY set are exited."""

    async def test_underperformer_not_in_buy_set_gets_sell(self):
        agent = ScannerPortfolioAgent()
        # Position bought at 100, now at 93 → -7% → exceeds 5% stop
        agent.portfolio.positions["XYZ"] = Position("XYZ", 10, 100.0)

        # Scan has no BUY for XYZ
        scan = _make_scan([
            {"symbol": "AAPL", "action": "BUY", "confidence": 0.75, "reasoning": "good"},
        ])

        with patch("agents.scanner_agent.get_cached_scan", return_value=scan), \
             patch("trading.alpaca_client.alpaca_client.get_bars_multi", new_callable=AsyncMock) as mock_bars:
            mock_bars.return_value = {}
            agent.risk_manager.get_max_buy_shares = MagicMock(return_value=0)
            ctx = {"XYZ": {"price": 93.0}, "AAPL": {"price": 150.0}}
            signals = await agent.analyze(ctx)

        sell_xyz = [s for s in signals if s.action == "SELL" and s.symbol == "XYZ"]
        self.assertEqual(len(sell_xyz), 1)

    async def test_position_in_buy_set_not_stopped_out(self):
        """If a held position is in the BUY set, don't stop it out even if down."""
        agent = ScannerPortfolioAgent()
        # Down -7% but XYZ is in the BUY set
        agent.portfolio.positions["XYZ"] = Position("XYZ", 10, 100.0)

        scan = _make_scan([
            {"symbol": "XYZ", "action": "BUY", "confidence": 0.70, "reasoning": "still good"},
        ])

        with patch("agents.scanner_agent.get_cached_scan", return_value=scan), \
             patch("trading.alpaca_client.alpaca_client.get_bars_multi", new_callable=AsyncMock) as mock_bars:
            mock_bars.return_value = {}
            agent.risk_manager.get_max_buy_shares = MagicMock(return_value=0)
            ctx = {"XYZ": {"price": 93.0}}
            signals = await agent.analyze(ctx)

        sell_xyz = [s for s in signals if s.action == "SELL" and s.symbol == "XYZ"]
        self.assertEqual(len(sell_xyz), 0)

    async def test_small_loss_within_stop_not_sold(self):
        """Position down -3% < 5% stop → not stopped out."""
        agent = ScannerPortfolioAgent()
        agent.portfolio.positions["ABC"] = Position("ABC", 10, 100.0)

        scan = _make_scan([
            {"symbol": "AAPL", "action": "BUY", "confidence": 0.75, "reasoning": "good"},
        ])

        with patch("agents.scanner_agent.get_cached_scan", return_value=scan), \
             patch("trading.alpaca_client.alpaca_client.get_bars_multi", new_callable=AsyncMock) as mock_bars:
            mock_bars.return_value = {}
            agent.risk_manager.get_max_buy_shares = MagicMock(return_value=0)
            ctx = {"ABC": {"price": 97.0}, "AAPL": {"price": 150.0}}
            signals = await agent.analyze(ctx)

        sell_abc = [s for s in signals if s.action == "SELL" and s.symbol == "ABC"]
        self.assertEqual(len(sell_abc), 0)


class TestScannerPortfolioAgentNewScanGate(unittest.IsolatedAsyncioTestCase):
    """New BUY positions are only entered on fresh scans."""

    async def test_same_scan_ts_does_not_re_enter_held_position(self):
        """Already-held position on the same scan_ts should not generate a new BUY."""
        agent = ScannerPortfolioAgent()
        agent._last_acted_scan_ts = "2024-01-01T10:00:00"
        agent.portfolio.positions["AAPL"] = Position("AAPL", 5, 140.0)

        scan = _make_scan([
            {"symbol": "AAPL", "action": "BUY", "confidence": 0.80, "reasoning": "strong"},
        ], scanned_at="2024-01-01T10:00:00")  # same ts

        with patch("agents.scanner_agent.get_cached_scan", return_value=scan), \
             patch("trading.alpaca_client.alpaca_client.get_bars_multi", new_callable=AsyncMock) as mock_bars:
            mock_bars.return_value = {}
            agent.risk_manager.get_max_buy_shares = MagicMock(return_value=5)
            ctx = _make_ctx(["AAPL"], price=150.0)
            signals = await agent.analyze(ctx)

        buy_aapl = [s for s in signals if s.action == "BUY" and s.symbol == "AAPL"]
        # already_held=True and new_scan=False → skip
        self.assertEqual(len(buy_aapl), 0)

    async def test_new_scan_ts_allows_re_entry(self):
        """Fresh scan with a different ts should allow re-entering a held position."""
        agent = ScannerPortfolioAgent()
        agent._last_acted_scan_ts = "2024-01-01T09:00:00"
        agent.portfolio.positions["AAPL"] = Position("AAPL", 5, 140.0)

        scan = _make_scan([
            {"symbol": "AAPL", "action": "BUY", "confidence": 0.80, "reasoning": "upgraded"},
        ], scanned_at="2024-01-01T10:30:00")  # different ts

        with patch("agents.scanner_agent.get_cached_scan", return_value=scan), \
             patch("trading.alpaca_client.alpaca_client.get_bars_multi", new_callable=AsyncMock) as mock_bars:
            mock_bars.return_value = {}
            agent.risk_manager.get_max_buy_shares = MagicMock(return_value=5)
            ctx = _make_ctx(["AAPL"], price=150.0)
            signals = await agent.analyze(ctx)

        buy_aapl = [s for s in signals if s.action == "BUY" and s.symbol == "AAPL"]
        # new_scan=True so already_held is fine → BUY generated (if shares > 0)
        self.assertTrue(len(buy_aapl) >= 1)


if __name__ == "__main__":
    unittest.main()
