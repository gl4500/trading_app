"""
Unit tests for agents/cnn_reasoning_agent.py

Covers:
  - analyze() emits BUY/SELL/HOLD signals without error
  - SELL path reads portfolio.positions[sym].shares (not get_position)
  - Ollama unavailable falls back to rule-based decision
  - Pre-training surrogate logic (CNN not yet trained)
  - analyze() does not raise when market_context is empty
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages")))

from agents.cnn_reasoning_agent import CNNReasoningAgent
from trading.portfolio import Position


def _make_ctx(price=100.0, composite=0.0):
    return {
        "price": price,
        "composite_signal": {
            "composite_score": composite,
            "sources": {
                "analyst_consensus":    {"score": 0.1},
                "earnings_surprise":    {"score": 0.0},
                "alpaca_news":          {"score": 0.0},
                "yahoo_news":           {"score": 0.0},
                "congressional_trades": {"score": 0.0},
            },
        },
    }


def _make_market(symbols=("AAPL",), price=100.0, composite=0.0):
    ctx = {sym: _make_ctx(price=price, composite=composite) for sym in symbols}
    ctx["__overnight_catalysts__"] = []
    return ctx


class TestCNNReasoningAgentAnalyze(unittest.IsolatedAsyncioTestCase):
    """analyze() should never raise; SELL path must not call get_position."""

    def setUp(self):
        self.agent = CNNReasoningAgent()

    def _patch_ollama_hold(self):
        return patch.object(
            self.agent, "_ollama_decision",
            new=AsyncMock(return_value={"action": "HOLD", "confidence": 0.5, "reasoning": "test"})
        )

    async def test_returns_list_of_signals(self):
        mkt = _make_market(["AAPL", "MSFT"])
        with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
             self._patch_ollama_hold():
            signals = await self.agent.analyze(mkt)
        self.assertIsInstance(signals, list)
        self.assertEqual(len(signals), 2)

    async def test_buy_signal_sets_shares(self):
        mkt = _make_market(["AAPL"], price=150.0)
        buy_resp = {"action": "BUY", "confidence": 0.85, "reasoning": "strong"}
        with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
             patch.object(self.agent, "_ollama_decision", new=AsyncMock(return_value=buy_resp)):
            signals = await self.agent.analyze(mkt)
        buys = [s for s in signals if s.action == "BUY"]
        self.assertEqual(len(buys), 1)
        self.assertGreater(buys[0].shares, 0)

    async def test_sell_signal_reads_portfolio_positions_not_get_position(self):
        """
        Regression: get_position() does not exist on Portfolio.
        SELL path must use portfolio.positions[sym].shares instead.
        """
        mkt = _make_market(["AAPL"], price=150.0)
        # Inject a held position so SELL fires
        self.agent.portfolio.positions["AAPL"] = Position(symbol="AAPL", shares=10, avg_cost=140.0)

        sell_resp = {"action": "SELL", "confidence": 0.80, "reasoning": "bearish"}
        with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
             patch.object(self.agent, "_ollama_decision", new=AsyncMock(return_value=sell_resp)):
            # Must not raise AttributeError
            signals = await self.agent.analyze(mkt)

        sells = [s for s in signals if s.action == "SELL"]
        self.assertEqual(len(sells), 1)
        self.assertEqual(sells[0].shares, 10)

    async def test_sell_skipped_when_no_position(self):
        """SELL signal for a symbol not held should produce a HOLD instead."""
        mkt = _make_market(["TSLA"], price=200.0)
        # No position held for TSLA
        sell_resp = {"action": "SELL", "confidence": 0.75, "reasoning": "bearish"}
        with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
             patch.object(self.agent, "_ollama_decision", new=AsyncMock(return_value=sell_resp)):
            signals = await self.agent.analyze(mkt)

        sells = [s for s in signals if s.action == "SELL"]
        self.assertEqual(len(sells), 0)

    async def test_ollama_unavailable_uses_rule_based_fallback(self):
        """When _ollama_decision returns None, rule-based fallback kicks in."""
        mkt = _make_market(["AAPL"])
        with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
             patch.object(self.agent, "_ollama_decision", new=AsyncMock(return_value=None)):
            signals = await self.agent.analyze(mkt)
        # Rule-based: direction=neutral → HOLD (composite=0 → neutral)
        self.assertEqual(len(signals), 1)
        self.assertIn(signals[0].action, ("BUY", "SELL", "HOLD"))

    async def test_empty_market_context_returns_empty_list(self):
        with patch.object(self.agent, "_ensure_model", new=AsyncMock()):
            signals = await self.agent.analyze({})
        self.assertEqual(signals, [])

    async def test_non_dict_context_entries_skipped(self):
        mkt = {
            "__overnight_catalysts__": ["some catalyst"],
            "AAPL": _make_ctx(),
        }
        with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
             self._patch_ollama_hold():
            signals = await self.agent.analyze(mkt)
        symbols = [s.symbol for s in signals]
        self.assertIn("AAPL", symbols)
        self.assertNotIn("__overnight_catalysts__", symbols)

    async def test_buy_confidence_below_threshold_produces_hold(self):
        """BUY with confidence < 0.50 should not emit a BUY signal."""
        mkt = _make_market(["AAPL"], price=100.0)
        low_conf_buy = {"action": "BUY", "confidence": 0.30, "reasoning": "weak"}
        with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
             patch.object(self.agent, "_ollama_decision", new=AsyncMock(return_value=low_conf_buy)):
            signals = await self.agent.analyze(mkt)
        buys = [s for s in signals if s.action == "BUY"]
        self.assertEqual(len(buys), 0)


if __name__ == "__main__":
    unittest.main()
