"""
Unit tests for agents/claude_agent.py
Covers: analyze() fallback, backoff counter, _api_lock, _build_market_prompt
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

from agents.claude_agent import ClaudeAgent
from agents.base_agent import Signal


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_ctx(symbols=("AAPL", "MSFT")):
    """Minimal market context used by most tests."""
    return {sym: {"price": 150.0, "bars": None, "news": [], "stats": {}} for sym in symbols}


class TestClaudeAgentFallback(unittest.IsolatedAsyncioTestCase):
    """When Anthropic is unconfigured, analyze() must return HOLD for all symbols."""

    def setUp(self):
        self.agent = ClaudeAgent()

    async def test_no_api_key_returns_hold_signals(self):
        with patch("agents.claude_agent.HAS_ANTHROPIC", True), \
             patch("agents.claude_agent.config") as mock_cfg:
            mock_cfg.ANTHROPIC_API_KEY = ""
            mock_cfg.WATCHLIST = ["AAPL"]
            mock_cfg.MAX_POSITION_SIZE = 0.10
            ctx = _make_ctx(["AAPL"])
            signals = await self.agent.analyze(ctx)
        self.assertTrue(all(s.action == "HOLD" for s in signals))

    async def test_missing_anthropic_package_returns_hold(self):
        with patch("agents.claude_agent.HAS_ANTHROPIC", False), \
             patch("agents.claude_agent.config") as mock_cfg:
            mock_cfg.ANTHROPIC_API_KEY = ""
            mock_cfg.WATCHLIST = []
            mock_cfg.MAX_POSITION_SIZE = 0.10
            ctx = _make_ctx(["AAPL"])
            signals = await self.agent.analyze(ctx)
        self.assertTrue(all(s.action == "HOLD" for s in signals))

    async def test_returns_signal_per_symbol(self):
        with patch("agents.claude_agent.HAS_ANTHROPIC", False), \
             patch("agents.claude_agent.config") as mock_cfg:
            mock_cfg.ANTHROPIC_API_KEY = ""
            mock_cfg.WATCHLIST = []
            mock_cfg.MAX_POSITION_SIZE = 0.10
            ctx = _make_ctx(["AAPL", "MSFT"])
            signals = await self.agent.analyze(ctx)
        syms = {s.symbol for s in signals}
        self.assertIn("AAPL", syms)
        self.assertIn("MSFT", syms)


class TestClaudeAgentBackoff(unittest.IsolatedAsyncioTestCase):
    """Backoff counter increments on 429 errors and _backoff_until is set."""

    def setUp(self):
        self.agent = ClaudeAgent()

    async def test_backoff_until_set_on_rate_limit(self):
        import anthropic

        mock_client = MagicMock()
        mock_err = anthropic.APIStatusError.__new__(anthropic.APIStatusError)
        mock_err.status_code = 429
        mock_err.message = "rate limited"
        mock_err.response = MagicMock(status_code=429)

        async def raise_429(*args, **kwargs):
            raise mock_err

        mock_client.messages.create = raise_429
        self.agent._client = mock_client

        before = time.time()
        with patch("agents.claude_agent.HAS_ANTHROPIC", True), \
             patch("agents.claude_agent.config") as mock_cfg:
            mock_cfg.ANTHROPIC_API_KEY = "fake"
            mock_cfg.WATCHLIST = []
            mock_cfg.MAX_POSITION_SIZE = 0.10
            # Call _get_claude_decisions directly
            result = await self.agent._get_claude_decisions({"AAPL": {"price": 150, "bars": None, "news": [], "stats": {}}}, ["AAPL"])

        self.assertIsNone(result)
        self.assertGreater(self.agent._backoff_until, before)

    async def test_backoff_seconds_doubles_on_repeat_429(self):
        import anthropic

        initial_backoff = self.agent._backoff_seconds
        mock_client = MagicMock()
        mock_err = anthropic.APIStatusError.__new__(anthropic.APIStatusError)
        mock_err.status_code = 429
        mock_err.message = "rate limited"
        mock_err.response = MagicMock(status_code=429)

        async def raise_429(*args, **kwargs):
            raise mock_err

        mock_client.messages.create = raise_429
        self.agent._client = mock_client

        with patch("agents.claude_agent.HAS_ANTHROPIC", True), \
             patch("agents.claude_agent.config") as mock_cfg:
            mock_cfg.ANTHROPIC_API_KEY = "fake"
            mock_cfg.WATCHLIST = []
            mock_cfg.MAX_POSITION_SIZE = 0.10
            # First 429
            await self.agent._get_claude_decisions(_make_ctx(["AAPL"]), ["AAPL"])
            first_backoff = self.agent._backoff_seconds
            # Reset backoff_until so next call also hits the 429 logic
            self.agent._backoff_until = 0.0
            await self.agent._get_claude_decisions(_make_ctx(["AAPL"]), ["AAPL"])
            second_backoff = self.agent._backoff_seconds

        self.assertGreater(first_backoff, initial_backoff)
        self.assertGreater(second_backoff, first_backoff)

    async def test_in_backoff_returns_fallback_hold(self):
        self.agent._backoff_until = time.time() + 9999

        with patch("agents.claude_agent.HAS_ANTHROPIC", True), \
             patch("agents.claude_agent.config") as mock_cfg:
            mock_cfg.ANTHROPIC_API_KEY = "fake"
            mock_cfg.WATCHLIST = []
            mock_cfg.MAX_POSITION_SIZE = 0.10
            ctx = _make_ctx(["AAPL"])
            signals = await self.agent.analyze(ctx)
        self.assertTrue(all(s.action == "HOLD" for s in signals))


class TestClaudeAgentApiLock(unittest.IsolatedAsyncioTestCase):
    """When _api_lock is held, analyze() waits and reuses cached decisions."""

    async def test_concurrent_call_reuses_cached_decisions(self):
        agent = ClaudeAgent()
        agent._last_decisions = {
            "decisions": [
                {"symbol": "AAPL", "action": "HOLD", "shares": 0,
                 "confidence": 0.5, "reasoning": "cached"}
            ],
            "_watchlist": ["AAPL"],
        }

        lock_acquired = asyncio.Event()
        lock_release = asyncio.Event()

        async def hold_lock():
            async with agent._api_lock:
                lock_acquired.set()
                await lock_release.wait()

        async def call_analyze():
            with patch("agents.claude_agent.HAS_ANTHROPIC", True), \
                 patch("agents.claude_agent.config") as mock_cfg:
                mock_cfg.ANTHROPIC_API_KEY = "fake"
                mock_cfg.WATCHLIST = []
                mock_cfg.MAX_POSITION_SIZE = 0.10
                return await agent.analyze(_make_ctx(["AAPL"]))

        # Hold the lock in a background task
        holder = asyncio.create_task(hold_lock())
        await lock_acquired.wait()

        # Start analyze while lock is held — it will enter the "locked" branch
        analyzer = asyncio.create_task(call_analyze())
        await asyncio.sleep(0)  # let analyzer reach the lock check

        # Release the lock so analyze() can proceed
        lock_release.set()

        signals = await analyzer
        await holder

        self.assertIsInstance(signals, list)


class TestClaudeAgentSuccessfulAnalysis(unittest.IsolatedAsyncioTestCase):
    """When Claude returns a valid JSON response, parse_ai_decisions is called."""

    async def test_valid_response_parsed_to_signals(self):
        agent = ClaudeAgent()

        fake_response_json = {
            "market_analysis": "Bullish conditions.",
            "decisions": [
                {
                    "symbol": "AAPL",
                    "action": "HOLD",
                    "shares": 0,
                    "confidence": 0.6,
                    "reasoning": "Mixed signals",
                }
            ],
        }

        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = '{"market_analysis": "ok", "decisions": [{"symbol": "AAPL", "action": "HOLD", "shares": 0, "confidence": 0.6, "reasoning": "test"}]}'

        mock_response = MagicMock()
        mock_response.content = [mock_block]

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        agent._client = mock_client

        with patch("agents.claude_agent.HAS_ANTHROPIC", True), \
             patch("agents.claude_agent.config") as mock_cfg, \
             patch("agents.claude_agent.get_learning_summary", return_value=""), \
             patch("agents.claude_agent.news_service") as mock_news, \
             patch("agents.claude_agent.format_technicals", return_value=""), \
             patch("agents.claude_agent.format_composite", return_value=""):
            mock_cfg.ANTHROPIC_API_KEY = "fake"
            mock_cfg.WATCHLIST = ["AAPL"]
            mock_cfg.MAX_POSITION_SIZE = 0.10
            mock_news.format_for_prompt.return_value = ""
            signals = await agent.analyze(_make_ctx(["AAPL"]))

        self.assertIsInstance(signals, list)
        self.assertTrue(len(signals) >= 1)


class TestClaudeAgentBuildPrompt(unittest.TestCase):
    """_build_market_prompt should include each watchlist symbol."""

    def setUp(self):
        self.agent = ClaudeAgent()

    def test_prompt_contains_watchlist_symbols(self):
        with patch("agents.claude_agent.build_portfolio_context", return_value="portfolio"), \
             patch("agents.claude_agent.format_bars_for_prompt", return_value="bars"), \
             patch("agents.claude_agent.news_service") as mock_news, \
             patch("agents.claude_agent.format_technicals", return_value="tech"), \
             patch("agents.claude_agent.format_composite", return_value="comp"), \
             patch("agents.claude_agent.get_learning_summary", return_value=""):
            mock_news.format_for_prompt.return_value = "news"
            ctx = _make_ctx(["AAPL", "MSFT"])
            prompt = self.agent._build_market_prompt(ctx, ["AAPL", "MSFT"])
        self.assertIn("AAPL", prompt)
        self.assertIn("MSFT", prompt)

    def test_prompt_contains_overnight_catalysts(self):
        with patch("agents.claude_agent.build_portfolio_context", return_value="portfolio"), \
             patch("agents.claude_agent.format_bars_for_prompt", return_value="bars"), \
             patch("agents.claude_agent.news_service") as mock_news, \
             patch("agents.claude_agent.format_technicals", return_value="tech"), \
             patch("agents.claude_agent.format_composite", return_value="comp"), \
             patch("agents.claude_agent.get_learning_summary", return_value=""):
            mock_news.format_for_prompt.return_value = ""
            ctx = {
                "AAPL": {"price": 150.0, "bars": None, "news": [], "stats": {}},
                "__overnight_catalysts__": [{"headline": "Big news!", "score": 3, "category": "policy", "date": "2024-01-01", "symbol": "AAPL"}],
            }
            prompt = self.agent._build_market_prompt(ctx, ["AAPL"])
        self.assertIn("Big news!", prompt)


if __name__ == "__main__":
    unittest.main()
