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


# ── Token logging & hourly rate limit tests ──────────────────────────────────

def _make_claude_mock_response(input_tokens=8000, output_tokens=500):
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = '{"market_analysis": "ok", "decisions": [{"symbol": "AAPL", "action": "HOLD", "shares": 0, "confidence": 0.5, "reasoning": "test"}]}'
    mock_usage = MagicMock()
    mock_usage.input_tokens = input_tokens
    mock_usage.output_tokens = output_tokens
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    mock_response.usage = mock_usage
    return mock_response


class TestClaudeTokenLogging(unittest.IsolatedAsyncioTestCase):

    def _make_agent_with_client(self, input_tokens=8000, output_tokens=500):
        agent = ClaudeAgent()
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_make_claude_mock_response(input_tokens, output_tokens)
        )
        agent._client = mock_client
        return agent, mock_client

    async def test_token_usage_logged_after_api_call(self):
        agent, _ = self._make_agent_with_client(input_tokens=8100, output_tokens=490)
        with patch("agents.claude_agent.HAS_ANTHROPIC", True), \
             patch("agents.claude_agent.config") as cfg, \
             patch("agents.claude_agent.get_learning_summary", return_value=""), \
             patch("agents.claude_agent.news_service") as mock_news, \
             patch("agents.claude_agent.format_technicals", return_value=""), \
             patch("agents.claude_agent.format_composite", return_value=""), \
             patch("agents.claude_agent.save_token_log", new_callable=AsyncMock):
            cfg.ANTHROPIC_API_KEY = "key"
            cfg.WATCHLIST = ["AAPL"]
            cfg.MAX_POSITION_SIZE = 0.10
            mock_news.format_for_prompt.return_value = ""
            with self.assertLogs("agents.claude_agent", level="INFO") as cm:
                await agent._get_claude_decisions(_make_ctx(["AAPL"]), ["AAPL"])
        log_text = " ".join(cm.output)
        self.assertIn("8100", log_text)
        self.assertIn("490", log_text)

    async def test_daily_token_counter_incremented(self):
        agent, _ = self._make_agent_with_client(input_tokens=8000, output_tokens=500)
        with patch("agents.claude_agent.HAS_ANTHROPIC", True), \
             patch("agents.claude_agent.config") as cfg, \
             patch("agents.claude_agent.get_learning_summary", return_value=""), \
             patch("agents.claude_agent.news_service") as mock_news, \
             patch("agents.claude_agent.format_technicals", return_value=""), \
             patch("agents.claude_agent.format_composite", return_value=""), \
             patch("agents.claude_agent.save_token_log", new_callable=AsyncMock):
            cfg.ANTHROPIC_API_KEY = "key"
            cfg.WATCHLIST = ["AAPL"]
            cfg.MAX_POSITION_SIZE = 0.10
            mock_news.format_for_prompt.return_value = ""
            await agent._get_claude_decisions(_make_ctx(["AAPL"]), ["AAPL"])
        self.assertEqual(agent._daily_tokens, 8500)


class TestClaudeHourlyRateLimit(unittest.IsolatedAsyncioTestCase):

    def _make_agent_with_client(self):
        agent = ClaudeAgent()
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_make_claude_mock_response()
        )
        agent._client = mock_client
        return agent, mock_client

    async def test_api_blocked_when_hourly_limit_reached(self):
        agent, mock_client = self._make_agent_with_client()
        # Seed 2 calls made within the last hour
        agent._call_timestamps = [time.time() - 100, time.time() - 50]
        with patch("agents.claude_agent.HAS_ANTHROPIC", True), \
             patch("agents.claude_agent.config") as cfg, \
             patch("agents.claude_agent.get_learning_summary", return_value=""), \
             patch("agents.claude_agent.news_service") as mock_news, \
             patch("agents.claude_agent.format_technicals", return_value=""), \
             patch("agents.claude_agent.format_composite", return_value=""):
            cfg.ANTHROPIC_API_KEY = "key"
            cfg.WATCHLIST = ["AAPL"]
            cfg.MAX_POSITION_SIZE = 0.10
            mock_news.format_for_prompt.return_value = ""
            result = await agent._get_claude_decisions(_make_ctx(["AAPL"]), ["AAPL"])
        mock_client.messages.create.assert_not_called()
        self.assertIsNone(result)

    async def test_api_allowed_when_under_hourly_limit(self):
        agent, mock_client = self._make_agent_with_client()
        # Only 1 call in the last hour
        agent._call_timestamps = [time.time() - 100]
        with patch("agents.claude_agent.HAS_ANTHROPIC", True), \
             patch("agents.claude_agent.config") as cfg, \
             patch("agents.claude_agent.get_learning_summary", return_value=""), \
             patch("agents.claude_agent.news_service") as mock_news, \
             patch("agents.claude_agent.format_technicals", return_value=""), \
             patch("agents.claude_agent.format_composite", return_value=""), \
             patch("agents.claude_agent.save_token_log", new_callable=AsyncMock):
            cfg.ANTHROPIC_API_KEY = "key"
            cfg.WATCHLIST = ["AAPL"]
            cfg.MAX_POSITION_SIZE = 0.10
            mock_news.format_for_prompt.return_value = ""
            result = await agent._get_claude_decisions(_make_ctx(["AAPL"]), ["AAPL"])
        mock_client.messages.create.assert_called_once()
        self.assertIsNotNone(result)

    async def test_old_timestamps_expire_from_window(self):
        """Timestamps older than 1 hour must not count toward the limit."""
        agent, mock_client = self._make_agent_with_client()
        # 2 calls, but both > 1 hour ago → should not count
        agent._call_timestamps = [time.time() - 3700, time.time() - 3601]
        with patch("agents.claude_agent.HAS_ANTHROPIC", True), \
             patch("agents.claude_agent.config") as cfg, \
             patch("agents.claude_agent.get_learning_summary", return_value=""), \
             patch("agents.claude_agent.news_service") as mock_news, \
             patch("agents.claude_agent.format_technicals", return_value=""), \
             patch("agents.claude_agent.format_composite", return_value=""), \
             patch("agents.claude_agent.save_token_log", new_callable=AsyncMock):
            cfg.ANTHROPIC_API_KEY = "key"
            cfg.WATCHLIST = ["AAPL"]
            cfg.MAX_POSITION_SIZE = 0.10
            mock_news.format_for_prompt.return_value = ""
            result = await agent._get_claude_decisions(_make_ctx(["AAPL"]), ["AAPL"])
        mock_client.messages.create.assert_called_once()

    async def test_timestamp_recorded_after_successful_call(self):
        agent, _ = self._make_agent_with_client()
        before = time.time()
        with patch("agents.claude_agent.HAS_ANTHROPIC", True), \
             patch("agents.claude_agent.config") as cfg, \
             patch("agents.claude_agent.get_learning_summary", return_value=""), \
             patch("agents.claude_agent.news_service") as mock_news, \
             patch("agents.claude_agent.format_technicals", return_value=""), \
             patch("agents.claude_agent.format_composite", return_value=""), \
             patch("agents.claude_agent.save_token_log", new_callable=AsyncMock):
            cfg.ANTHROPIC_API_KEY = "key"
            cfg.WATCHLIST = ["AAPL"]
            cfg.MAX_POSITION_SIZE = 0.10
            mock_news.format_for_prompt.return_value = ""
            await agent._get_claude_decisions(_make_ctx(["AAPL"]), ["AAPL"])
        self.assertEqual(len(agent._call_timestamps), 1)
        self.assertGreaterEqual(agent._call_timestamps[0], before)

    async def test_rate_limit_warning_logged(self):
        agent, _ = self._make_agent_with_client()
        agent._call_timestamps = [time.time() - 10, time.time() - 5]
        with patch("agents.claude_agent.HAS_ANTHROPIC", True), \
             patch("agents.claude_agent.config") as cfg, \
             patch("agents.claude_agent.get_learning_summary", return_value=""), \
             patch("agents.claude_agent.news_service") as mock_news, \
             patch("agents.claude_agent.format_technicals", return_value=""), \
             patch("agents.claude_agent.format_composite", return_value=""):
            cfg.ANTHROPIC_API_KEY = "key"
            cfg.WATCHLIST = ["AAPL"]
            cfg.MAX_POSITION_SIZE = 0.10
            mock_news.format_for_prompt.return_value = ""
            with self.assertLogs("agents.claude_agent", level="WARNING") as cm:
                await agent._get_claude_decisions(_make_ctx(["AAPL"]), ["AAPL"])
        self.assertTrue(any("rate limit" in line.lower() or "hourly" in line.lower() for line in cm.output))


class TestClaudePromptGeminiView(unittest.TestCase):
    """_build_market_prompt includes Gemini market view when present in context."""

    def setUp(self):
        self.agent = ClaudeAgent()

    def _build(self, extra_ctx=None):
        ctx = _make_ctx(["AAPL"])
        if extra_ctx:
            ctx.update(extra_ctx)
        with patch("agents.claude_agent.build_portfolio_context", return_value="portfolio"), \
             patch("agents.claude_agent.format_bars_for_prompt", return_value="bars"), \
             patch("agents.claude_agent.news_service") as mock_news, \
             patch("agents.claude_agent.format_technicals", return_value=""), \
             patch("agents.claude_agent.format_composite", return_value=""), \
             patch("agents.claude_agent.get_learning_summary", return_value=""):
            mock_news.format_for_prompt.return_value = ""
            return self.agent._build_market_prompt(ctx, ["AAPL"])

    def test_gemini_view_included_when_present(self):
        prompt = self._build({"__gemini_market_view__": "Gemini says: broad rally incoming."})
        self.assertIn("Gemini", prompt)
        self.assertIn("broad rally incoming", prompt)

    def test_prompt_unaffected_when_no_gemini_view(self):
        prompt = self._build()
        self.assertNotIn("__gemini_market_view__", prompt)


class TestClaudeRateLimitCacheReplay(unittest.IsolatedAsyncioTestCase):
    """When rate-limited on an API cycle, last decisions must be replayed not HOLDs."""

    def _make_agent_rate_limited(self):
        agent = ClaudeAgent()
        # Seed 2 recent timestamps so rate limit fires immediately
        agent._call_timestamps = [time.time() - 100, time.time() - 50]
        # Seed last good decisions
        agent._last_decisions = {
            "market_analysis": "bullish",
            "decisions": [
                {"symbol": "AAPL", "action": "HOLD", "shares": 0,
                 "confidence": 0.7, "reasoning": "cached decision"}
            ],
            "_watchlist": ["AAPL"],
        }
        return agent

    async def test_rate_limited_api_cycle_replays_cache_not_hold(self):
        agent = self._make_agent_rate_limited()
        # Force an API cycle by setting cycle_count so % interval == 0 (triggers fresh call)
        agent._cycle_count = 0

        with patch("agents.claude_agent.HAS_ANTHROPIC", True), \
             patch("agents.claude_agent.config") as cfg, \
             patch("agents.claude_agent.get_learning_summary", return_value=""), \
             patch("agents.claude_agent.news_service") as mock_news, \
             patch("agents.claude_agent.format_technicals", return_value=""), \
             patch("agents.claude_agent.format_composite", return_value=""):
            cfg.ANTHROPIC_API_KEY = "key"
            cfg.WATCHLIST = ["AAPL"]
            cfg.MAX_POSITION_SIZE = 0.10
            mock_news.format_for_prompt.return_value = ""
            signals = await agent.analyze(_make_ctx(["AAPL"]))

        # Should have replayed the cached decision, not a blank fallback
        self.assertTrue(len(signals) > 0)
        aapl = next((s for s in signals if s.symbol == "AAPL"), None)
        self.assertIsNotNone(aapl)
        # Cached reasoning should appear, not the generic "API unavailable" fallback
        self.assertNotIn("API unavailable", aapl.reasoning)

    async def test_rate_limited_no_cache_still_returns_hold(self):
        agent = ClaudeAgent()
        agent._call_timestamps = [time.time() - 100, time.time() - 50]
        # No last_decisions cached
        agent._last_decisions = {}
        agent._cycle_count = 0

        with patch("agents.claude_agent.HAS_ANTHROPIC", True), \
             patch("agents.claude_agent.config") as cfg, \
             patch("agents.claude_agent.get_learning_summary", return_value=""), \
             patch("agents.claude_agent.news_service") as mock_news, \
             patch("agents.claude_agent.format_technicals", return_value=""), \
             patch("agents.claude_agent.format_composite", return_value=""):
            cfg.ANTHROPIC_API_KEY = "key"
            cfg.WATCHLIST = ["AAPL"]
            cfg.MAX_POSITION_SIZE = 0.10
            mock_news.format_for_prompt.return_value = ""
            signals = await agent.analyze(_make_ctx(["AAPL"]))

        self.assertTrue(all(s.action == "HOLD" for s in signals))


class TestClaudeSaveTokenLog(unittest.IsolatedAsyncioTestCase):
    """save_token_log is called after each successful Claude API call."""

    def _make_agent_with_client(self, input_tokens=8000, output_tokens=500):
        agent = ClaudeAgent()
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_make_claude_mock_response(input_tokens, output_tokens)
        )
        agent._client = mock_client
        return agent, mock_client

    async def test_save_token_log_called_after_success(self):
        agent, _ = self._make_agent_with_client(input_tokens=8000, output_tokens=500)
        with patch("agents.claude_agent.HAS_ANTHROPIC", True), \
             patch("agents.claude_agent.config") as cfg, \
             patch("agents.claude_agent.get_learning_summary", return_value=""), \
             patch("agents.claude_agent.news_service") as mock_news, \
             patch("agents.claude_agent.format_technicals", return_value=""), \
             patch("agents.claude_agent.format_composite", return_value=""), \
             patch("agents.claude_agent.save_token_log", new_callable=AsyncMock) as mock_save:
            cfg.ANTHROPIC_API_KEY = "key"
            cfg.WATCHLIST = ["AAPL"]
            cfg.MAX_POSITION_SIZE = 0.10
            mock_news.format_for_prompt.return_value = ""
            await agent._get_claude_decisions(_make_ctx(["AAPL"]), ["AAPL"])
        mock_save.assert_awaited_once()
        all_args = list(mock_save.call_args[0]) + list((mock_save.call_args[1] or {}).values())
        self.assertIn("ClaudeAgent", all_args)
        self.assertIn("claude-opus-4-6", all_args)

    async def test_save_token_log_limit_hit_false_on_success(self):
        agent, _ = self._make_agent_with_client()
        with patch("agents.claude_agent.HAS_ANTHROPIC", True), \
             patch("agents.claude_agent.config") as cfg, \
             patch("agents.claude_agent.get_learning_summary", return_value=""), \
             patch("agents.claude_agent.news_service") as mock_news, \
             patch("agents.claude_agent.format_technicals", return_value=""), \
             patch("agents.claude_agent.format_composite", return_value=""), \
             patch("agents.claude_agent.save_token_log", new_callable=AsyncMock) as mock_save:
            cfg.ANTHROPIC_API_KEY = "key"
            cfg.WATCHLIST = ["AAPL"]
            cfg.MAX_POSITION_SIZE = 0.10
            mock_news.format_for_prompt.return_value = ""
            await agent._get_claude_decisions(_make_ctx(["AAPL"]), ["AAPL"])
        call_kwargs = mock_save.call_args
        limit_hit = call_kwargs[1].get("limit_hit") if call_kwargs[1] else call_kwargs[0][-1]
        self.assertFalse(limit_hit)


# ── Prompt caching structure tests ───────────────────────────────────────────

def _make_cache_mock_response(input_tokens=8000, output_tokens=500,
                               cache_creation=800, cache_read=0):
    """Mock response that includes cache token fields."""
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = (
        '{"market_analysis": "ok", "decisions": '
        '[{"symbol": "AAPL", "action": "HOLD", "shares": 0, '
        '"confidence": 0.5, "reasoning": "test"}]}'
    )
    mock_usage = MagicMock()
    mock_usage.input_tokens = input_tokens
    mock_usage.output_tokens = output_tokens
    mock_usage.cache_creation_input_tokens = cache_creation
    mock_usage.cache_read_input_tokens = cache_read
    mock_resp = MagicMock()
    mock_resp.content = [mock_block]
    mock_resp.usage = mock_usage
    return mock_resp


class TestClaudeAgentPromptCaching(unittest.IsolatedAsyncioTestCase):
    """API call must use prompt caching: system list + split user content blocks."""

    def _make_agent(self, input_tokens=8000, output_tokens=500):
        agent = ClaudeAgent()
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_make_cache_mock_response(input_tokens, output_tokens)
        )
        agent._client = mock_client
        return agent, mock_client

    async def _call_and_capture(self, agent, mock_client, ctx=None):
        ctx = ctx or _make_ctx(["AAPL"])
        with patch("agents.claude_agent.HAS_ANTHROPIC", True), \
             patch("agents.claude_agent.config") as cfg, \
             patch("agents.claude_agent.get_learning_summary", return_value=""), \
             patch("agents.claude_agent.news_service") as mock_news, \
             patch("agents.claude_agent.format_technicals", return_value=""), \
             patch("agents.claude_agent.format_composite", return_value=""), \
             patch("agents.claude_agent.save_token_log", new_callable=AsyncMock):
            cfg.ANTHROPIC_API_KEY = "key"
            cfg.WATCHLIST = ["AAPL"]
            cfg.MAX_POSITION_SIZE = 0.10
            mock_news.format_for_prompt.return_value = ""
            await agent._get_claude_decisions(ctx, ["AAPL"])
        return mock_client.messages.create.call_args[1]

    async def test_system_parameter_is_a_list(self):
        agent, mock_client = self._make_agent()
        kwargs = await self._call_and_capture(agent, mock_client)
        self.assertIsInstance(kwargs["system"], list)

    async def test_system_last_block_has_cache_control_ephemeral(self):
        agent, mock_client = self._make_agent()
        kwargs = await self._call_and_capture(agent, mock_client)
        last_block = kwargs["system"][-1]
        self.assertIn("cache_control", last_block)
        self.assertEqual(last_block["cache_control"]["type"], "ephemeral")

    async def test_user_message_content_is_a_list(self):
        agent, mock_client = self._make_agent()
        kwargs = await self._call_and_capture(agent, mock_client)
        content = kwargs["messages"][0]["content"]
        self.assertIsInstance(content, list)
        self.assertGreaterEqual(len(content), 2)

    async def test_first_user_block_has_cache_control(self):
        """Stable context (portfolio + learning) must be marked cacheable."""
        agent, mock_client = self._make_agent()
        kwargs = await self._call_and_capture(agent, mock_client)
        first_block = kwargs["messages"][0]["content"][0]
        self.assertIn("cache_control", first_block)
        self.assertEqual(first_block["cache_control"]["type"], "ephemeral")

    async def test_last_user_block_has_no_cache_control(self):
        """Dynamic market data must NOT be cached."""
        agent, mock_client = self._make_agent()
        kwargs = await self._call_and_capture(agent, mock_client)
        last_block = kwargs["messages"][0]["content"][-1]
        self.assertNotIn("cache_control", last_block)

    async def test_stable_context_contains_portfolio(self):
        agent = ClaudeAgent()
        with patch("agents.claude_agent.build_portfolio_context", return_value="MY_PORTFOLIO"), \
             patch("agents.claude_agent.get_learning_summary", return_value=""):
            stable = agent._build_stable_context({})
        self.assertIn("MY_PORTFOLIO", stable)

    async def test_dynamic_context_contains_symbol_prices(self):
        agent = ClaudeAgent()
        ctx = {"AAPL": {"price": 199.0, "bars": None, "news": [], "stats": {}}}
        with patch("agents.claude_agent.build_portfolio_context", return_value=""), \
             patch("agents.claude_agent.get_learning_summary", return_value=""), \
             patch("agents.claude_agent.news_service") as mock_news, \
             patch("agents.claude_agent.format_technicals", return_value=""), \
             patch("agents.claude_agent.format_composite", return_value=""):
            mock_news.format_for_prompt.return_value = ""
            dynamic = agent._build_dynamic_context(ctx, ["AAPL"])
        self.assertIn("AAPL", dynamic)

    async def test_cache_token_counts_logged(self):
        """cache_creation and cache_read token counts must appear in the log."""
        agent, _ = self._make_agent()
        agent._client.messages.create = AsyncMock(
            return_value=_make_cache_mock_response(cache_creation=750, cache_read=250)
        )
        with patch("agents.claude_agent.HAS_ANTHROPIC", True), \
             patch("agents.claude_agent.config") as cfg, \
             patch("agents.claude_agent.get_learning_summary", return_value=""), \
             patch("agents.claude_agent.news_service") as mock_news, \
             patch("agents.claude_agent.format_technicals", return_value=""), \
             patch("agents.claude_agent.format_composite", return_value=""), \
             patch("agents.claude_agent.save_token_log", new_callable=AsyncMock):
            cfg.ANTHROPIC_API_KEY = "key"
            cfg.WATCHLIST = ["AAPL"]
            cfg.MAX_POSITION_SIZE = 0.10
            mock_news.format_for_prompt.return_value = ""
            with self.assertLogs("agents.claude_agent", level="INFO") as cm:
                await agent._get_claude_decisions(_make_ctx(["AAPL"]), ["AAPL"])
        log_text = " ".join(cm.output)
        self.assertIn("750", log_text)   # cache_creation
        self.assertIn("250", log_text)   # cache_read


if __name__ == "__main__":
    unittest.main()
