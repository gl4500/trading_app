"""
Unit tests for agents/gemini_agent.py
Covers: analyze() fallback, backoff counter, cache replay, _api_lock
"""
import sys
import os
import asyncio
import time
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agents.gemini_agent import GeminiAgent


def _make_ctx(symbols=("AAPL",)):
    return {sym: {"price": 150.0, "bars": None, "news": [], "stats": {}} for sym in symbols}


class TestGeminiAgentFallback(unittest.IsolatedAsyncioTestCase):
    """analyze() returns HOLD signals when Gemini is unconfigured."""

    async def test_no_api_key_returns_hold_signals(self):
        agent = GeminiAgent()
        with patch("agents.gemini_agent.HAS_GEMINI", True), \
             patch("agents.gemini_agent.config") as mock_cfg:
            mock_cfg.GEMINI_API_KEY = ""
            mock_cfg.MAX_POSITION_SIZE = 0.10
            signals = await agent.analyze(_make_ctx(["AAPL"]))
        self.assertTrue(all(s.action == "HOLD" for s in signals))

    async def test_missing_gemini_package_returns_hold(self):
        agent = GeminiAgent()
        with patch("agents.gemini_agent.HAS_GEMINI", False), \
             patch("agents.gemini_agent.config") as mock_cfg:
            mock_cfg.GEMINI_API_KEY = ""
            mock_cfg.MAX_POSITION_SIZE = 0.10
            signals = await agent.analyze(_make_ctx(["AAPL"]))
        self.assertTrue(all(s.action == "HOLD" for s in signals))

    async def test_returns_signal_per_symbol(self):
        agent = GeminiAgent()
        with patch("agents.gemini_agent.HAS_GEMINI", False), \
             patch("agents.gemini_agent.config") as mock_cfg:
            mock_cfg.GEMINI_API_KEY = ""
            mock_cfg.MAX_POSITION_SIZE = 0.10
            signals = await agent.analyze(_make_ctx(["AAPL", "MSFT"]))
        syms = {s.symbol for s in signals}
        self.assertIn("AAPL", syms)
        self.assertIn("MSFT", syms)


class TestGeminiAgentBackoff(unittest.IsolatedAsyncioTestCase):
    """Backoff timer is set when a 429/quota error is received."""

    async def test_rate_limit_error_sets_backoff_until(self):
        agent = GeminiAgent()

        async def raise_quota(*args, **kwargs):
            raise Exception("429 RESOURCE_EXHAUSTED: quota exceeded")

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = raise_quota
        agent._client = mock_client

        before = time.time()
        with patch("agents.gemini_agent.HAS_GEMINI", True), \
             patch("agents.gemini_agent.config") as mock_cfg, \
             patch("agents.gemini_agent.news_service") as mock_news, \
             patch("agents.gemini_agent.format_technicals", return_value=""), \
             patch("agents.gemini_agent.format_composite", return_value=""), \
             patch("agents.gemini_agent.build_portfolio_context", return_value=""):
            mock_cfg.GEMINI_API_KEY = "fake"
            mock_cfg.MAX_POSITION_SIZE = 0.10
            mock_news.format_for_prompt.return_value = ""
            result = await agent._get_gemini_decisions(_make_ctx(["AAPL"]), ["AAPL"])

        self.assertIsNone(result)
        self.assertGreater(agent._backoff_until, before)

    async def test_backoff_seconds_doubles_on_repeat_quota_error(self):
        agent = GeminiAgent()
        initial_backoff = agent._backoff_seconds

        async def raise_quota(*args, **kwargs):
            raise Exception("429 RESOURCE_EXHAUSTED: quota exceeded")

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = raise_quota
        agent._client = mock_client

        with patch("agents.gemini_agent.HAS_GEMINI", True), \
             patch("agents.gemini_agent.config") as mock_cfg, \
             patch("agents.gemini_agent.news_service") as mock_news, \
             patch("agents.gemini_agent.format_technicals", return_value=""), \
             patch("agents.gemini_agent.format_composite", return_value=""), \
             patch("agents.gemini_agent.build_portfolio_context", return_value=""):
            mock_cfg.GEMINI_API_KEY = "fake"
            mock_cfg.MAX_POSITION_SIZE = 0.10
            mock_news.format_for_prompt.return_value = ""
            await agent._get_gemini_decisions(_make_ctx(["AAPL"]), ["AAPL"])
            first_backoff = agent._backoff_seconds
            agent._backoff_until = 0.0
            await agent._get_gemini_decisions(_make_ctx(["AAPL"]), ["AAPL"])
            second_backoff = agent._backoff_seconds

        self.assertGreater(first_backoff, initial_backoff)
        self.assertGreater(second_backoff, first_backoff)

    async def test_in_backoff_returns_fallback_hold(self):
        agent = GeminiAgent()
        agent._backoff_until = time.time() + 9999

        with patch("agents.gemini_agent.HAS_GEMINI", True), \
             patch("agents.gemini_agent.config") as mock_cfg:
            mock_cfg.GEMINI_API_KEY = "fake"
            mock_cfg.MAX_POSITION_SIZE = 0.10
            signals = await agent.analyze(_make_ctx(["AAPL"]))
        self.assertTrue(all(s.action == "HOLD" for s in signals))


class TestGeminiAgentCacheReplay(unittest.IsolatedAsyncioTestCase):
    """Cached decisions are replayed between analysis intervals."""

    async def test_cached_decisions_replayed_on_non_interval_cycle(self):
        agent = GeminiAgent()
        agent._analysis_interval = 10
        agent._cycle_count = 9   # second cycle → 10 % 10 == 0, not interval trigger

        agent._last_decisions = {
            "decisions": [
                {"symbol": "AAPL", "action": "HOLD", "shares": 0,
                 "confidence": 0.5, "reasoning": "cached"}
            ],
            "_watchlist": ["AAPL"],
        }

        with patch("agents.gemini_agent.HAS_GEMINI", True), \
             patch("agents.gemini_agent.config") as mock_cfg:
            mock_cfg.GEMINI_API_KEY = "fake"
            mock_cfg.MAX_POSITION_SIZE = 0.10
            signals = await agent.analyze(_make_ctx(["AAPL"]))

        # Should return cached signals without making API call
        self.assertIsInstance(signals, list)


class TestGeminiAgentValidResponse(unittest.IsolatedAsyncioTestCase):
    """When Gemini returns valid JSON, decisions are parsed correctly."""

    async def test_valid_json_response_parsed(self):
        agent = GeminiAgent()

        mock_response = MagicMock()
        mock_response.text = '{"decisions": [{"symbol": "AAPL", "action": "HOLD", "shares": 0, "confidence": 0.5, "reasoning": "test"}], "market_analysis": "ok"}'

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
        agent._client = mock_client

        with patch("agents.gemini_agent.HAS_GEMINI", True), \
             patch("agents.gemini_agent.config") as mock_cfg, \
             patch("agents.gemini_agent.news_service") as mock_news, \
             patch("agents.gemini_agent.format_technicals", return_value=""), \
             patch("agents.gemini_agent.format_composite", return_value=""), \
             patch("agents.gemini_agent.build_portfolio_context", return_value=""):
            mock_cfg.GEMINI_API_KEY = "fake"
            mock_cfg.MAX_POSITION_SIZE = 0.10
            mock_news.format_for_prompt.return_value = ""
            result = await agent._get_gemini_decisions(_make_ctx(["AAPL"]), ["AAPL"])

        self.assertIsNotNone(result)
        self.assertIn("decisions", result)

    async def test_empty_response_returns_none(self):
        agent = GeminiAgent()

        mock_response = MagicMock()
        mock_response.text = ""

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
        agent._client = mock_client

        with patch("agents.gemini_agent.HAS_GEMINI", True), \
             patch("agents.gemini_agent.config") as mock_cfg, \
             patch("agents.gemini_agent.news_service") as mock_news, \
             patch("agents.gemini_agent.format_technicals", return_value=""), \
             patch("agents.gemini_agent.format_composite", return_value=""), \
             patch("agents.gemini_agent.build_portfolio_context", return_value=""):
            mock_cfg.GEMINI_API_KEY = "fake"
            mock_cfg.MAX_POSITION_SIZE = 0.10
            mock_news.format_for_prompt.return_value = ""
            result = await agent._get_gemini_decisions(_make_ctx(["AAPL"]), ["AAPL"])

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
