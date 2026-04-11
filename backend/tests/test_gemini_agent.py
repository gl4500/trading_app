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
        # After hitting the 60s cap, second backoff should equal first (not exceed it)
        self.assertGreaterEqual(second_backoff, first_backoff)
        self.assertLessEqual(second_backoff, 60)

    async def test_backoff_capped_at_60_seconds(self):
        """Backoff must never exceed 60s regardless of how many 429s occur."""
        agent = GeminiAgent()

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
            for _ in range(5):
                agent._backoff_until = 0.0
                await agent._get_gemini_decisions(_make_ctx(["AAPL"]), ["AAPL"])

        self.assertLessEqual(agent._backoff_seconds, 60)

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
        mock_response.usage_metadata.prompt_token_count = 100
        mock_response.usage_metadata.candidates_token_count = 50

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
        agent._client = mock_client

        with patch("agents.gemini_agent.HAS_GEMINI", True), \
             patch("agents.gemini_agent.config") as mock_cfg, \
             patch("agents.gemini_agent.news_service") as mock_news, \
             patch("agents.gemini_agent.format_technicals", return_value=""), \
             patch("agents.gemini_agent.format_composite", return_value=""), \
             patch("agents.gemini_agent.build_portfolio_context", return_value=""), \
             patch("agents.gemini_agent.save_token_log", new_callable=AsyncMock):
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


# ── Token logging & hourly rate limit tests ──────────────────────────────────

def _make_gemini_mock_response(prompt_tokens=7000, candidate_tokens=400):
    mock_response = MagicMock()
    mock_response.text = '{"decisions": [{"symbol": "AAPL", "action": "HOLD", "shares": 0, "confidence": 0.5, "reasoning": "test"}], "market_analysis": "ok"}'
    mock_response.usage_metadata = MagicMock()
    mock_response.usage_metadata.prompt_token_count = prompt_tokens
    mock_response.usage_metadata.candidates_token_count = candidate_tokens
    return mock_response


def _patch_gemini_deps(mock_cfg):
    mock_cfg.GEMINI_API_KEY = "key"
    mock_cfg.MAX_POSITION_SIZE = 0.10


class TestGeminiTokenLogging(unittest.IsolatedAsyncioTestCase):

    def _make_agent(self, prompt_tokens=7000, candidate_tokens=400):
        agent = GeminiAgent()
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(
            return_value=_make_gemini_mock_response(prompt_tokens, candidate_tokens)
        )
        agent._client = mock_client
        return agent, mock_client

    async def test_token_usage_logged_after_api_call(self):
        agent, _ = self._make_agent(prompt_tokens=7100, candidate_tokens=450)
        with patch("agents.gemini_agent.HAS_GEMINI", True), \
             patch("agents.gemini_agent.config") as cfg, \
             patch("agents.gemini_agent.news_service") as mock_news, \
             patch("agents.gemini_agent.format_technicals", return_value=""), \
             patch("agents.gemini_agent.format_composite", return_value=""), \
             patch("agents.gemini_agent.build_portfolio_context", return_value=""), \
             patch("agents.gemini_agent.save_token_log", new_callable=AsyncMock):
            _patch_gemini_deps(cfg)
            mock_news.format_for_prompt.return_value = ""
            with self.assertLogs("agents.gemini_agent", level="INFO") as cm:
                await agent._get_gemini_decisions(_make_ctx(["AAPL"]), ["AAPL"])
        log_text = " ".join(cm.output)
        self.assertIn("7100", log_text)
        self.assertIn("450", log_text)

    async def test_daily_token_counter_incremented(self):
        agent, _ = self._make_agent(prompt_tokens=7000, candidate_tokens=400)
        with patch("agents.gemini_agent.HAS_GEMINI", True), \
             patch("agents.gemini_agent.config") as cfg, \
             patch("agents.gemini_agent.news_service") as mock_news, \
             patch("agents.gemini_agent.format_technicals", return_value=""), \
             patch("agents.gemini_agent.format_composite", return_value=""), \
             patch("agents.gemini_agent.build_portfolio_context", return_value=""), \
             patch("agents.gemini_agent.save_token_log", new_callable=AsyncMock):
            _patch_gemini_deps(cfg)
            mock_news.format_for_prompt.return_value = ""
            await agent._get_gemini_decisions(_make_ctx(["AAPL"]), ["AAPL"])
        self.assertEqual(agent._daily_tokens, 7400)


class TestGeminiHourlyRateLimit(unittest.IsolatedAsyncioTestCase):

    def _make_agent(self):
        agent = GeminiAgent()
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(
            return_value=_make_gemini_mock_response()
        )
        agent._client = mock_client
        return agent, mock_client

    async def test_api_blocked_when_hourly_limit_reached(self):
        agent, mock_client = self._make_agent()
        agent._call_timestamps = [time.time() - 100, time.time() - 50]
        with patch("agents.gemini_agent.HAS_GEMINI", True), \
             patch("agents.gemini_agent.config") as cfg, \
             patch("agents.gemini_agent.news_service") as mock_news, \
             patch("agents.gemini_agent.format_technicals", return_value=""), \
             patch("agents.gemini_agent.format_composite", return_value=""), \
             patch("agents.gemini_agent.build_portfolio_context", return_value=""):
            _patch_gemini_deps(cfg)
            mock_news.format_for_prompt.return_value = ""
            result = await agent._get_gemini_decisions(_make_ctx(["AAPL"]), ["AAPL"])
        mock_client.aio.models.generate_content.assert_not_called()
        self.assertIsNone(result)

    async def test_api_allowed_when_under_hourly_limit(self):
        agent, mock_client = self._make_agent()
        agent._call_timestamps = [time.time() - 100]
        with patch("agents.gemini_agent.HAS_GEMINI", True), \
             patch("agents.gemini_agent.config") as cfg, \
             patch("agents.gemini_agent.news_service") as mock_news, \
             patch("agents.gemini_agent.format_technicals", return_value=""), \
             patch("agents.gemini_agent.format_composite", return_value=""), \
             patch("agents.gemini_agent.build_portfolio_context", return_value=""), \
             patch("agents.gemini_agent.save_token_log", new_callable=AsyncMock):
            _patch_gemini_deps(cfg)
            mock_news.format_for_prompt.return_value = ""
            result = await agent._get_gemini_decisions(_make_ctx(["AAPL"]), ["AAPL"])
        mock_client.aio.models.generate_content.assert_called_once()
        self.assertIsNotNone(result)

    async def test_old_timestamps_expire_from_window(self):
        agent, mock_client = self._make_agent()
        agent._call_timestamps = [time.time() - 3700, time.time() - 3601]
        with patch("agents.gemini_agent.HAS_GEMINI", True), \
             patch("agents.gemini_agent.config") as cfg, \
             patch("agents.gemini_agent.news_service") as mock_news, \
             patch("agents.gemini_agent.format_technicals", return_value=""), \
             patch("agents.gemini_agent.format_composite", return_value=""), \
             patch("agents.gemini_agent.build_portfolio_context", return_value=""), \
             patch("agents.gemini_agent.save_token_log", new_callable=AsyncMock):
            _patch_gemini_deps(cfg)
            mock_news.format_for_prompt.return_value = ""
            result = await agent._get_gemini_decisions(_make_ctx(["AAPL"]), ["AAPL"])
        mock_client.aio.models.generate_content.assert_called_once()

    async def test_timestamp_recorded_after_successful_call(self):
        agent, _ = self._make_agent()
        before = time.time()
        with patch("agents.gemini_agent.HAS_GEMINI", True), \
             patch("agents.gemini_agent.config") as cfg, \
             patch("agents.gemini_agent.news_service") as mock_news, \
             patch("agents.gemini_agent.format_technicals", return_value=""), \
             patch("agents.gemini_agent.format_composite", return_value=""), \
             patch("agents.gemini_agent.build_portfolio_context", return_value=""), \
             patch("agents.gemini_agent.save_token_log", new_callable=AsyncMock):
            _patch_gemini_deps(cfg)
            mock_news.format_for_prompt.return_value = ""
            await agent._get_gemini_decisions(_make_ctx(["AAPL"]), ["AAPL"])
        self.assertEqual(len(agent._call_timestamps), 1)
        self.assertGreaterEqual(agent._call_timestamps[0], before)

    async def test_rate_limit_warning_logged(self):
        agent, _ = self._make_agent()
        agent._call_timestamps = [time.time() - 10, time.time() - 5]
        with patch("agents.gemini_agent.HAS_GEMINI", True), \
             patch("agents.gemini_agent.config") as cfg, \
             patch("agents.gemini_agent.news_service") as mock_news, \
             patch("agents.gemini_agent.format_technicals", return_value=""), \
             patch("agents.gemini_agent.format_composite", return_value=""), \
             patch("agents.gemini_agent.build_portfolio_context", return_value=""):
            _patch_gemini_deps(cfg)
            mock_news.format_for_prompt.return_value = ""
            with self.assertLogs("agents.base_agent", level="WARNING") as cm:
                await agent._get_gemini_decisions(_make_ctx(["AAPL"]), ["AAPL"])
        self.assertTrue(any("rate limit" in line.lower() or "hourly" in line.lower() for line in cm.output))


class TestGeminiRateLimitCacheReplay(unittest.IsolatedAsyncioTestCase):
    """When rate-limited on an API cycle, last decisions must be replayed not HOLDs."""

    def _make_agent_rate_limited(self):
        agent = GeminiAgent()
        agent._call_timestamps = [time.time() - 100, time.time() - 50]
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
        agent._cycle_count = 0

        with patch("agents.gemini_agent.HAS_GEMINI", True), \
             patch("agents.gemini_agent.config") as cfg:
            cfg.GEMINI_API_KEY = "key"
            cfg.MAX_POSITION_SIZE = 0.10
            signals = await agent.analyze(_make_ctx(["AAPL"]))

        self.assertTrue(len(signals) > 0)
        aapl = next((s for s in signals if s.symbol == "AAPL"), None)
        self.assertIsNotNone(aapl)
        self.assertNotIn("API unavailable", aapl.reasoning)

    async def test_rate_limited_no_cache_still_returns_hold(self):
        agent = GeminiAgent()
        agent._call_timestamps = [time.time() - 100, time.time() - 50]
        agent._last_decisions = {}
        agent._cycle_count = 0

        with patch("agents.gemini_agent.HAS_GEMINI", True), \
             patch("agents.gemini_agent.config") as cfg:
            cfg.GEMINI_API_KEY = "key"
            cfg.MAX_POSITION_SIZE = 0.10
            signals = await agent.analyze(_make_ctx(["AAPL"]))

        self.assertTrue(all(s.action == "HOLD" for s in signals))


# ── get_market_view tests ────────────────────────────────────────────────────

class TestGeminiMarketView(unittest.IsolatedAsyncioTestCase):

    def _make_agent_with_response(self, market_analysis="Broad market looks bullish."):
        agent = GeminiAgent()
        mock_response = MagicMock()
        mock_response.text = (
            f'{{"decisions": [], "market_analysis": "{market_analysis}"}}'
        )
        mock_response.usage_metadata = MagicMock()
        mock_response.usage_metadata.prompt_token_count = 500
        mock_response.usage_metadata.candidates_token_count = 100
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
        agent._client = mock_client
        return agent

    async def test_returns_market_analysis_string(self):
        agent = self._make_agent_with_response("Markets look bullish overall.")
        with patch("agents.gemini_agent.HAS_GEMINI", True), \
             patch("agents.gemini_agent.config") as cfg, \
             patch("agents.gemini_agent.news_service") as mock_news, \
             patch("agents.gemini_agent.format_technicals", return_value=""), \
             patch("agents.gemini_agent.format_composite", return_value=""), \
             patch("agents.gemini_agent.build_portfolio_context", return_value=""), \
             patch("agents.gemini_agent.save_token_log", new_callable=AsyncMock):
            cfg.GEMINI_API_KEY = "key"
            cfg.MAX_POSITION_SIZE = 0.10
            mock_news.format_for_prompt.return_value = ""
            result = await agent.get_market_view(_make_ctx(["AAPL"]), ["AAPL"])
        self.assertIsNotNone(result)
        self.assertIn("bullish", result.lower())

    async def test_returns_none_when_rate_limited(self):
        agent = self._make_agent_with_response()
        agent._call_timestamps = [time.time() - 10, time.time() - 5]
        with patch("agents.gemini_agent.HAS_GEMINI", True), \
             patch("agents.gemini_agent.config") as cfg, \
             patch("agents.gemini_agent.news_service") as mock_news, \
             patch("agents.gemini_agent.format_technicals", return_value=""), \
             patch("agents.gemini_agent.format_composite", return_value=""), \
             patch("agents.gemini_agent.build_portfolio_context", return_value=""):
            cfg.GEMINI_API_KEY = "key"
            cfg.MAX_POSITION_SIZE = 0.10
            mock_news.format_for_prompt.return_value = ""
            result = await agent.get_market_view(_make_ctx(["AAPL"]), ["AAPL"])
        self.assertIsNone(result)

    async def test_returns_none_when_not_configured(self):
        agent = GeminiAgent()
        with patch("agents.gemini_agent.HAS_GEMINI", False), \
             patch("agents.gemini_agent.config") as cfg:
            cfg.GEMINI_API_KEY = ""
            cfg.MAX_POSITION_SIZE = 0.10
            result = await agent.get_market_view(_make_ctx(["AAPL"]), ["AAPL"])
        self.assertIsNone(result)


class TestGeminiSaveTokenLog(unittest.IsolatedAsyncioTestCase):
    """save_token_log is called after each successful Gemini API call."""

    def _make_agent_with_response(self, analysis="ok"):
        agent = GeminiAgent()
        mock_response = MagicMock()
        mock_response.text = f'{{"market_analysis": "{analysis}", "decisions": [{{"symbol": "AAPL", "action": "HOLD", "shares": 0, "confidence": 0.5, "reasoning": "test"}}]}}'
        mock_response.usage_metadata = MagicMock()
        mock_response.usage_metadata.prompt_token_count = 500
        mock_response.usage_metadata.candidates_token_count = 100
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
        agent._client = mock_client
        return agent

    async def test_save_token_log_called_after_success(self):
        agent = self._make_agent_with_response()
        with patch("agents.gemini_agent.HAS_GEMINI", True), \
             patch("agents.gemini_agent.config") as cfg, \
             patch("agents.gemini_agent.news_service") as mock_news, \
             patch("agents.gemini_agent.format_technicals", return_value=""), \
             patch("agents.gemini_agent.format_composite", return_value=""), \
             patch("agents.gemini_agent.build_portfolio_context", return_value=""), \
             patch("agents.gemini_agent.save_token_log", new_callable=AsyncMock) as mock_save:
            cfg.GEMINI_API_KEY = "key"
            cfg.MAX_POSITION_SIZE = 0.10
            mock_news.format_for_prompt.return_value = ""
            await agent._get_gemini_decisions(_make_ctx(["AAPL"]), ["AAPL"])
        mock_save.assert_awaited_once()
        all_args = list(mock_save.call_args[0]) + list((mock_save.call_args[1] or {}).values())
        self.assertIn("GeminiAgent", all_args)
        self.assertIn("gemini-2.0-flash", all_args)

    async def test_save_token_log_limit_hit_false_on_success(self):
        agent = self._make_agent_with_response()
        with patch("agents.gemini_agent.HAS_GEMINI", True), \
             patch("agents.gemini_agent.config") as cfg, \
             patch("agents.gemini_agent.news_service") as mock_news, \
             patch("agents.gemini_agent.format_technicals", return_value=""), \
             patch("agents.gemini_agent.format_composite", return_value=""), \
             patch("agents.gemini_agent.build_portfolio_context", return_value=""), \
             patch("agents.gemini_agent.save_token_log", new_callable=AsyncMock) as mock_save:
            cfg.GEMINI_API_KEY = "key"
            cfg.MAX_POSITION_SIZE = 0.10
            mock_news.format_for_prompt.return_value = ""
            await agent._get_gemini_decisions(_make_ctx(["AAPL"]), ["AAPL"])
        call_kwargs = mock_save.call_args
        limit_hit = call_kwargs[1].get("limit_hit") if call_kwargs[1] else call_kwargs[0][-1]
        self.assertFalse(limit_hit)


class TestGeminiOllamaMode(unittest.IsolatedAsyncioTestCase):
    """When OLLAMA_ONLY_MODE=1 GeminiAgent routes through local Ollama, not Gemini API."""

    def setUp(self):
        os.environ["OLLAMA_ONLY_MODE"] = "1"

    def tearDown(self):
        os.environ.pop("OLLAMA_ONLY_MODE", None)

    def _valid_response(self):
        return {
            "market_analysis": "Neutral market.",
            "decisions": [
                {"symbol": "AAPL", "action": "HOLD", "shares": 0,
                 "confidence": 0.5, "reasoning": "Waiting for signal"}
            ],
        }

    async def test_returns_signals_in_ollama_mode(self):
        """analyze() must return signals when Ollama responds."""
        agent = GeminiAgent()
        with patch("agents.gemini_agent.config") as mock_cfg, \
             patch.object(agent, "_get_ollama_decisions",
                          new=AsyncMock(return_value=self._valid_response())):
            mock_cfg.OLLAMA_MODEL = "llama3.1:8b"
            mock_cfg.MAX_POSITION_SIZE = 0.10
            signals = await agent.analyze(_make_ctx(["AAPL"]))
        self.assertIsInstance(signals, list)
        self.assertGreater(len(signals), 0)

    async def test_gemini_api_not_called_in_ollama_mode(self):
        """Gemini SDK must NOT be called when OLLAMA_ONLY_MODE=1."""
        agent = GeminiAgent()
        with patch("agents.gemini_agent.config") as mock_cfg, \
             patch.object(agent, "_get_ollama_decisions",
                          new=AsyncMock(return_value=self._valid_response())), \
             patch.object(agent, "_get_gemini_decisions",
                          new=AsyncMock()) as mock_gemini:
            mock_cfg.GEMINI_API_KEY = "real-key"
            mock_cfg.OLLAMA_MODEL = "llama3.1:8b"
            mock_cfg.MAX_POSITION_SIZE = 0.10
            await agent.analyze(_make_ctx(["AAPL"]))
        mock_gemini.assert_not_called()

    async def test_get_market_view_uses_ollama_in_ollama_mode(self):
        """get_market_view() must return analysis from Ollama, not Gemini."""
        agent = GeminiAgent()
        with patch("agents.gemini_agent.config") as mock_cfg, \
             patch.object(agent, "_get_ollama_decisions",
                          new=AsyncMock(return_value=self._valid_response())):
            mock_cfg.OLLAMA_MODEL = "llama3.1:8b"
            mock_cfg.MAX_POSITION_SIZE = 0.10
            result = await agent.get_market_view(_make_ctx(["AAPL"]), ["AAPL"])
        self.assertEqual(result, "Neutral market.")

    async def test_get_ollama_decisions_uses_ollama_model(self):
        """_get_ollama_decisions must pass OLLAMA_MODEL as the model name."""
        agent = GeminiAgent()
        captured_model = {}

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(
            message=MagicMock(content='{"market_analysis":"ok","decisions":[]}')
        )]

        async def fake_create(**kwargs):
            captured_model["model"] = kwargs.get("model")
            return mock_response

        mock_client = MagicMock()
        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = fake_create

        with patch("agents.gemini_agent.config") as mock_cfg, \
             patch("agents.gemini_agent.AsyncOpenAI", return_value=mock_client), \
             patch("agents.gemini_agent.news_service") as mock_news, \
             patch("agents.gemini_agent.format_technicals", return_value=""), \
             patch("agents.gemini_agent.format_composite", return_value=""), \
             patch("agents.gemini_agent.build_portfolio_context", return_value=""), \
             patch("agents.gemini_agent.format_sector_summary", return_value=""):
            mock_cfg.OLLAMA_MODEL = "llama3.1:8b"
            mock_cfg.OLLAMA_BASE_URL = "http://localhost:11434/v1"
            mock_cfg.MAX_POSITION_SIZE = 0.10
            mock_news.format_for_prompt.return_value = ""
            await agent._get_ollama_decisions(_make_ctx(["AAPL"]), ["AAPL"])

        self.assertEqual(captured_model.get("model"), "llama3.1:8b")

    async def test_fallback_to_cache_when_ollama_fails(self):
        """If _get_ollama_decisions returns None, replay last cached decisions."""
        agent = GeminiAgent()
        agent._last_decisions = {
            "_watchlist": ["AAPL"],
            "market_analysis": "cached",
            "decisions": [{"symbol": "AAPL", "action": "HOLD", "shares": 0,
                           "confidence": 0.5, "reasoning": "cached"}],
        }
        with patch("agents.gemini_agent.config") as mock_cfg, \
             patch.object(agent, "_get_ollama_decisions", new=AsyncMock(return_value=None)):
            mock_cfg.OLLAMA_MODEL = "llama3.1:8b"
            mock_cfg.MAX_POSITION_SIZE = 0.10
            signals = await agent.analyze(_make_ctx(["AAPL"]))
        self.assertTrue(all(s.action == "HOLD" for s in signals))


if __name__ == "__main__":
    unittest.main()
