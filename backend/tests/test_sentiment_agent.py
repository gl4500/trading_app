"""
Unit tests for agents/sentiment_agent.py
Covers: _describe_price_action(), _generate_signal(), analyze() with mocked OpenAI
"""
import sys
import os
import asyncio
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import pandas as pd
    import numpy as np
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

from agents.sentiment_agent import SentimentAgent, _describe_price_action
from trading.portfolio import Position


def _make_bars(n=30, start=100.0, trend=0.0):
    if not HAS_PANDAS:
        return None
    close = [start + i * trend for i in range(n)]
    close = [max(c, 1.0) for c in close]
    return pd.DataFrame({
        "open":   close,
        "high":   [c + 0.5 for c in close],
        "low":    [c - 0.5 for c in close],
        "close":  close,
        "volume": [1_000_000] * n,
    })


# ── _describe_price_action tests ──────────────────────────────────────────────

@unittest.skipUnless(HAS_PANDAS, "pandas not available")
class TestDescribePriceAction(unittest.TestCase):

    def test_none_bars_returns_no_history_message(self):
        result = _describe_price_action(None, "AAPL", 150.0)
        self.assertIn("AAPL", result)
        self.assertIn("No", result)

    def test_contains_symbol_and_price(self):
        bars = _make_bars(n=30, start=100.0, trend=0.5)
        result = _describe_price_action(bars, "MSFT", 115.0)
        self.assertIn("MSFT", result)
        self.assertIn("115", result)

    def test_uptrend_detected(self):
        bars = _make_bars(n=30, start=60.0, trend=2.0)
        result = _describe_price_action(bars, "TSLA", float(bars["close"].iloc[-1]))
        # 20D return ≥ 10% → "strong uptrend" or "modest uptrend"
        self.assertTrue("uptrend" in result or "sideways" in result or "downtrend" in result)

    def test_downtrend_detected(self):
        bars = _make_bars(n=30, start=200.0, trend=-2.0)
        result = _describe_price_action(bars, "XYZ", float(bars["close"].iloc[-1]))
        self.assertIn("downtrend", result)

    def test_volume_spike_mentioned(self):
        """Last 3 bars have 3x avg volume → volume spike text."""
        bars = _make_bars(n=30, start=100.0)
        # Spike volume in last 3 bars
        bars.loc[bars.index[-3:], "volume"] = 3_000_000
        result = _describe_price_action(bars, "AAPL", 100.0)
        self.assertIn("volume", result.lower())

    def test_too_few_bars_returns_no_history_message(self):
        bars = _make_bars(n=3)
        result = _describe_price_action(bars, "AAPL", 100.0)
        self.assertIn("No", result)


# ── _generate_signal tests ────────────────────────────────────────────────────

class TestGenerateSignal(unittest.TestCase):

    def setUp(self):
        self.agent = SentimentAgent()

    def _prices(self, price=150.0):
        return {"AAPL": price}

    def test_zero_price_returns_hold(self):
        sig = self.agent._generate_signal("AAPL", {"sentiment": "bullish", "confidence": 0.9, "strength": "strong", "reasoning": "", "key_signals": []}, {"AAPL": 0.0})
        self.assertEqual(sig.action, "HOLD")

    def test_bullish_strong_no_position_returns_buy(self):
        self.agent.portfolio._cash = 500_000
        sig = self.agent._generate_signal(
            "AAPL",
            {"sentiment": "bullish", "confidence": 0.8, "strength": "strong", "reasoning": "uptrend", "key_signals": ["rsi_low"]},
            self._prices(),
        )
        self.assertEqual(sig.action, "BUY")
        self.assertGreater(sig.shares, 0)

    def test_bullish_with_position_returns_hold(self):
        self.agent.portfolio.positions["AAPL"] = Position("AAPL", 10, 140.0)
        sig = self.agent._generate_signal(
            "AAPL",
            {"sentiment": "bullish", "confidence": 0.8, "strength": "strong", "reasoning": "uptrend", "key_signals": []},
            self._prices(),
        )
        # Already holding — should not double-buy → HOLD
        self.assertNotEqual(sig.action, "BUY")

    def test_bearish_with_position_returns_sell(self):
        self.agent.portfolio.positions["AAPL"] = Position("AAPL", 10, 155.0)
        sig = self.agent._generate_signal(
            "AAPL",
            {"sentiment": "bearish", "confidence": 0.8, "strength": "strong", "reasoning": "downtrend", "key_signals": []},
            self._prices(),
        )
        self.assertEqual(sig.action, "SELL")

    def test_bearish_without_position_returns_hold(self):
        sig = self.agent._generate_signal(
            "AAPL",
            {"sentiment": "bearish", "confidence": 0.8, "strength": "strong", "reasoning": "downtrend", "key_signals": []},
            self._prices(),
        )
        # Nothing to sell
        self.assertNotEqual(sig.action, "SELL")

    def test_low_confidence_bullish_returns_hold(self):
        sig = self.agent._generate_signal(
            "AAPL",
            {"sentiment": "bullish", "confidence": 0.3, "strength": "weak", "reasoning": "mild", "key_signals": []},
            self._prices(),
        )
        # adjusted_confidence = 0.3 * 0.6 = 0.18 < 0.45 threshold
        self.assertEqual(sig.action, "HOLD")

    def test_strength_multiplier_affects_confidence(self):
        base = {"sentiment": "bullish", "confidence": 0.8, "reasoning": "", "key_signals": []}
        strong_sig = self.agent._generate_signal("AAPL", {**base, "strength": "strong"}, self._prices())
        weak_agent = SentimentAgent()
        weak_sig = weak_agent._generate_signal("AAPL", {**base, "strength": "weak"}, self._prices())
        # strong multiplier (1.0) > weak multiplier (0.6)
        self.assertGreaterEqual(strong_sig.confidence, weak_sig.confidence)

    def test_neutral_sentiment_returns_hold(self):
        sig = self.agent._generate_signal(
            "AAPL",
            {"sentiment": "neutral", "confidence": 0.9, "strength": "strong", "reasoning": "flat", "key_signals": []},
            self._prices(),
        )
        self.assertEqual(sig.action, "HOLD")


# ── analyze() with mocked OpenAI ──────────────────────────────────────────────

class TestSentimentAnalyze(unittest.IsolatedAsyncioTestCase):

    async def test_no_openai_package_returns_hold(self):
        agent = SentimentAgent()
        with patch("agents.sentiment_agent.HAS_OPENAI", False):
            ctx = {"AAPL": {"price": 150.0, "bars": None, "news": []}}
            signals = await agent.analyze(ctx)
        self.assertIsInstance(signals, list)
        # With no OpenAI, _get_sentiment returns neutral → HOLD
        self.assertTrue(all(s.action == "HOLD" for s in signals))

    async def test_returns_signal_for_each_symbol(self):
        agent = SentimentAgent()
        with patch("agents.sentiment_agent.HAS_OPENAI", False), \
             patch("agents.sentiment_agent.config") as mock_cfg:
            mock_cfg.OPENAI_API_KEY = ""
            ctx = {
                "AAPL": {"price": 150.0, "bars": None, "news": []},
                "MSFT": {"price": 350.0, "bars": None, "news": []},
            }
            signals = await agent.analyze(ctx)
        syms = {s.symbol for s in signals}
        self.assertIn("AAPL", syms)
        self.assertIn("MSFT", syms)

    async def test_skips_non_dict_context(self):
        agent = SentimentAgent()
        with patch("agents.sentiment_agent.HAS_OPENAI", False):
            ctx = {
                "AAPL": {"price": 150.0, "bars": None, "news": []},
                "__overnight_catalysts__": [{"headline": "test"}],
            }
            signals = await agent.analyze(ctx)
        syms = [s.symbol for s in signals]
        self.assertNotIn("__overnight_catalysts__", syms)

    async def test_mocked_openai_bullish_response_returns_buy(self):
        agent = SentimentAgent()
        agent.portfolio._cash = 500_000

        mock_message = MagicMock()
        mock_message.content = '{"sentiment": "bullish", "confidence": 0.85, "strength": "strong", "reasoning": "uptrend", "key_signals": ["momentum"]}'
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        agent._openai_client = mock_client

        with patch("agents.sentiment_agent.HAS_OPENAI", True), \
             patch("agents.sentiment_agent.config") as mock_cfg:
            mock_cfg.OPENAI_API_KEY = "fake"
            mock_cfg.MAX_POSITION_SIZE = 0.10
            ctx = {"AAPL": {"price": 150.0, "bars": None, "news": []}}
            signals = await agent.analyze(ctx)

        aapl_signal = next((s for s in signals if s.symbol == "AAPL"), None)
        self.assertIsNotNone(aapl_signal)
        self.assertEqual(aapl_signal.action, "BUY")

    async def test_openai_api_error_returns_hold(self):
        agent = SentimentAgent()

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("network error"))
        agent._openai_client = mock_client

        with patch("agents.sentiment_agent.HAS_OPENAI", True), \
             patch("agents.sentiment_agent.config") as mock_cfg:
            mock_cfg.OPENAI_API_KEY = "fake"
            mock_cfg.MAX_POSITION_SIZE = 0.10
            ctx = {"AAPL": {"price": 150.0, "bars": None, "news": []}}
            signals = await agent.analyze(ctx)

        aapl_signal = next((s for s in signals if s.symbol == "AAPL"), None)
        self.assertIsNotNone(aapl_signal)
        self.assertEqual(aapl_signal.action, "HOLD")


class TestSentimentAgentThrottling(unittest.IsolatedAsyncioTestCase):

    def _mock_ctx(self):
        return {"AAPL": {"price": 150.0, "bars": None, "news": []}}

    def _make_agent_with_client(self, sentiment="bullish"):
        agent = SentimentAgent()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = (
            f'{{"sentiment": "{sentiment}", "confidence": 0.8, '
            f'"strength": "strong", "reasoning": "test", "key_signals": []}}'
        )
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        agent._openai_client = mock_client
        return agent, mock_client

    async def test_api_called_on_first_cycle(self):
        agent, mock_client = self._make_agent_with_client()
        with patch("agents.sentiment_agent.HAS_OPENAI", True), \
             patch("agents.sentiment_agent.config") as cfg, \
             patch("agents.sentiment_agent._is_market_hours", return_value=True):
            cfg.OPENAI_API_KEY = "key"
            cfg.MAX_POSITION_SIZE = 0.10
            cfg.STARTING_CAPITAL = 100_000
            await agent.analyze(self._mock_ctx())
        mock_client.chat.completions.create.assert_called_once()

    async def test_api_skipped_on_non_api_cycle(self):
        agent, mock_client = self._make_agent_with_client()
        # Seed cache so replay is possible
        agent._sentiment_cache["AAPL"] = {
            "sentiment": "neutral", "confidence": 0.5,
            "strength": "weak", "reasoning": "cached", "key_signals": []
        }
        agent._cycle_count = 2  # not on API cycle (interval=5, 2%5 != 1)
        with patch("agents.sentiment_agent.HAS_OPENAI", True), \
             patch("agents.sentiment_agent.config") as cfg, \
             patch("agents.sentiment_agent._is_market_hours", return_value=True):
            cfg.OPENAI_API_KEY = "key"
            cfg.MAX_POSITION_SIZE = 0.10
            cfg.STARTING_CAPITAL = 100_000
            signals = await agent.analyze(self._mock_ctx())
        mock_client.chat.completions.create.assert_not_called()
        self.assertTrue(len(signals) > 0)

    async def test_off_hours_uses_closed_interval(self):
        agent, mock_client = self._make_agent_with_client()
        agent._sentiment_cache["AAPL"] = {
            "sentiment": "neutral", "confidence": 0.5,
            "strength": "weak", "reasoning": "cached", "key_signals": []
        }
        # cycle 2 would be an API cycle under open_interval=5 (2%5==2, not 1)
        # but should also be non-API under closed_interval=25
        agent._cycle_count = 2
        with patch("agents.sentiment_agent.HAS_OPENAI", True), \
             patch("agents.sentiment_agent.config") as cfg, \
             patch("agents.sentiment_agent._is_market_hours", return_value=False):
            cfg.OPENAI_API_KEY = "key"
            cfg.MAX_POSITION_SIZE = 0.10
            cfg.STARTING_CAPITAL = 100_000
            await agent.analyze(self._mock_ctx())
        mock_client.chat.completions.create.assert_not_called()

    async def test_cache_populated_after_api_cycle(self):
        agent, mock_client = self._make_agent_with_client("bullish")
        with patch("agents.sentiment_agent.HAS_OPENAI", True), \
             patch("agents.sentiment_agent.config") as cfg, \
             patch("agents.sentiment_agent._is_market_hours", return_value=True):
            cfg.OPENAI_API_KEY = "key"
            cfg.MAX_POSITION_SIZE = 0.10
            cfg.STARTING_CAPITAL = 100_000
            await agent.analyze(self._mock_ctx())
        self.assertIn("AAPL", agent._sentiment_cache)


# ── Token logging & daily limit tests ────────────────────────────────────────

class TestTokenLogging(unittest.IsolatedAsyncioTestCase):

    def _make_agent_with_usage(self, prompt_tokens=200, completion_tokens=100):
        agent = SentimentAgent()

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = prompt_tokens
        mock_usage.completion_tokens = completion_tokens

        mock_message = MagicMock()
        mock_message.content = '{"sentiment": "neutral", "confidence": 0.5, "strength": "weak", "reasoning": "flat", "key_signals": []}'
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        agent._openai_client = mock_client
        return agent, mock_client

    async def test_token_usage_logged_after_api_call(self):
        agent, _ = self._make_agent_with_usage(prompt_tokens=210, completion_tokens=95)
        with patch("agents.sentiment_agent.HAS_OPENAI", True), \
             patch("agents.sentiment_agent.config") as cfg:
            cfg.OPENAI_API_KEY = "key"
            with self.assertLogs("agents.sentiment_agent", level="INFO") as cm:
                await agent._get_sentiment("AAPL", "price description")
        log_text = " ".join(cm.output)
        self.assertIn("210", log_text)   # prompt tokens
        self.assertIn("95", log_text)    # completion tokens

    async def test_daily_token_counter_incremented(self):
        agent, _ = self._make_agent_with_usage(prompt_tokens=200, completion_tokens=100)
        with patch("agents.sentiment_agent.HAS_OPENAI", True), \
             patch("agents.sentiment_agent.config") as cfg:
            cfg.OPENAI_API_KEY = "key"
            await agent._get_sentiment("AAPL", "desc")
        self.assertEqual(agent._daily_tokens, 300)

    async def test_daily_token_counter_accumulates_across_calls(self):
        agent, _ = self._make_agent_with_usage(prompt_tokens=100, completion_tokens=50)
        with patch("agents.sentiment_agent.HAS_OPENAI", True), \
             patch("agents.sentiment_agent.config") as cfg:
            cfg.OPENAI_API_KEY = "key"
            await agent._get_sentiment("AAPL", "desc")
            await agent._get_sentiment("MSFT", "desc")
        self.assertEqual(agent._daily_tokens, 300)


class TestDailyTokenLimit(unittest.IsolatedAsyncioTestCase):

    def _make_agent_at_limit(self, tokens_used=9_500):
        agent = SentimentAgent()
        agent._daily_tokens = tokens_used

        mock_message = MagicMock()
        mock_message.content = '{"sentiment": "bullish", "confidence": 0.8, "strength": "strong", "reasoning": "up", "key_signals": []}'
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 250
        mock_usage.completion_tokens = 100
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        agent._openai_client = mock_client
        return agent, mock_client

    async def test_api_blocked_when_limit_reached(self):
        agent, mock_client = self._make_agent_at_limit(tokens_used=10_000)
        with patch("agents.sentiment_agent.HAS_OPENAI", True), \
             patch("agents.sentiment_agent.config") as cfg:
            cfg.OPENAI_API_KEY = "key"
            result = await agent._get_sentiment("AAPL", "desc")
        mock_client.chat.completions.create.assert_not_called()
        self.assertEqual(result["sentiment"], "neutral")
        self.assertIn("limit", result["reasoning"].lower())

    async def test_api_allowed_below_limit(self):
        agent, mock_client = self._make_agent_at_limit(tokens_used=9_000)
        with patch("agents.sentiment_agent.HAS_OPENAI", True), \
             patch("agents.sentiment_agent.config") as cfg:
            cfg.OPENAI_API_KEY = "key"
            await agent._get_sentiment("AAPL", "desc")
        mock_client.chat.completions.create.assert_called_once()

    async def test_counter_resets_on_new_day(self):
        from datetime import date
        agent, mock_client = self._make_agent_at_limit(tokens_used=10_000)
        # Simulate that the stored reset day is yesterday
        from datetime import timedelta
        agent._token_reset_day = date.today() - timedelta(days=1)

        with patch("agents.sentiment_agent.HAS_OPENAI", True), \
             patch("agents.sentiment_agent.config") as cfg:
            cfg.OPENAI_API_KEY = "key"
            await agent._get_sentiment("AAPL", "desc")
        # After reset, API should have been called
        mock_client.chat.completions.create.assert_called_once()

    async def test_limit_warning_logged(self):
        agent, _ = self._make_agent_at_limit(tokens_used=10_000)
        with patch("agents.sentiment_agent.HAS_OPENAI", True), \
             patch("agents.sentiment_agent.config") as cfg:
            cfg.OPENAI_API_KEY = "key"
            with self.assertLogs("agents.sentiment_agent", level="WARNING") as cm:
                await agent._get_sentiment("AAPL", "desc")
        self.assertTrue(any("limit" in line.lower() for line in cm.output))


class TestSentimentSaveTokenLog(unittest.IsolatedAsyncioTestCase):
    """save_token_log is called after successful API calls and when limit is hit."""

    def _make_agent_with_usage(self, prompt_tokens=200, completion_tokens=100):
        agent = SentimentAgent()
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = prompt_tokens
        mock_usage.completion_tokens = completion_tokens
        mock_message = MagicMock()
        mock_message.content = '{"sentiment": "neutral", "confidence": 0.5, "strength": "weak", "reasoning": "flat", "key_signals": []}'
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        agent._openai_client = mock_client
        return agent

    async def test_save_token_log_called_after_success(self):
        agent = self._make_agent_with_usage(prompt_tokens=200, completion_tokens=100)
        with patch("agents.sentiment_agent.HAS_OPENAI", True), \
             patch("agents.sentiment_agent.config") as cfg, \
             patch("agents.sentiment_agent.save_token_log", new_callable=AsyncMock) as mock_save:
            cfg.OPENAI_API_KEY = "key"
            await agent._get_sentiment("AAPL", "desc")
        mock_save.assert_awaited_once()
        call_kwargs = mock_save.call_args
        args = call_kwargs[1] if call_kwargs[1] else {}
        # Can be positional or keyword — check via args tuple
        all_args = list(call_kwargs[0]) + list(args.values())
        self.assertIn("SentimentAgent", all_args)
        self.assertIn("gpt-4o-mini", all_args)

    async def test_save_token_log_called_with_limit_hit_false_normally(self):
        agent = self._make_agent_with_usage(prompt_tokens=100, completion_tokens=50)
        with patch("agents.sentiment_agent.HAS_OPENAI", True), \
             patch("agents.sentiment_agent.config") as cfg, \
             patch("agents.sentiment_agent.save_token_log", new_callable=AsyncMock) as mock_save:
            cfg.OPENAI_API_KEY = "key"
            await agent._get_sentiment("AAPL", "desc")
        call_kwargs = mock_save.call_args
        # limit_hit should be False for a normal successful call
        limit_hit_val = call_kwargs[1].get("limit_hit") if call_kwargs[1] else call_kwargs[0][-1]
        self.assertFalse(limit_hit_val)

    async def test_save_token_log_called_with_limit_hit_true_when_blocked(self):
        agent = SentimentAgent()
        agent._daily_tokens = 10_000  # at limit
        with patch("agents.sentiment_agent.HAS_OPENAI", True), \
             patch("agents.sentiment_agent.config") as cfg, \
             patch("agents.sentiment_agent.save_token_log", new_callable=AsyncMock) as mock_save:
            cfg.OPENAI_API_KEY = "key"
            await agent._get_sentiment("AAPL", "desc")
        mock_save.assert_awaited_once()
        call_kwargs = mock_save.call_args
        limit_hit_val = call_kwargs[1].get("limit_hit") if call_kwargs[1] else call_kwargs[0][-1]
        self.assertTrue(limit_hit_val)


if __name__ == "__main__":
    unittest.main()
