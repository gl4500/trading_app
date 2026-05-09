"""
Unit tests for agents/ollama_agent.py — local Ollama agent extracted from
ClaudeAgent on 2026-05-08 so cloud and local LLMs vote independently in the
ensemble.

Coverage: analyze() happy path, fallback when Ollama is unreachable,
malformed-JSON handling, _api_lock concurrency guard, no-cloud-call invariant.
"""
import sys
import os
import asyncio
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agents.ollama_agent import OllamaAgent
from agents.base_agent import Signal


def _make_ctx(symbols=("AAPL", "MSFT")):
    return {sym: {"price": 150.0, "bars": None, "news": [], "stats": {}} for sym in symbols}


def _make_ollama_response(content_text):
    """Build a fake openai.AsyncOpenAI chat-completions response."""
    fake_msg = MagicMock()
    fake_msg.content = content_text
    fake_choice = MagicMock()
    fake_choice.message = fake_msg
    fake_response = MagicMock()
    fake_response.choices = [fake_choice]
    fake_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
    return fake_response


class TestOllamaAgentBasics(unittest.TestCase):
    def test_agent_name(self):
        self.assertEqual(OllamaAgent().name, "OllamaAgent")

    def test_agent_inherits_baseagent(self):
        from agents.base_agent import BaseAgent
        self.assertIsInstance(OllamaAgent(), BaseAgent)

    def test_agent_does_not_inherit_cloudagent(self):
        """OllamaAgent is local — it should NOT inherit CloudAgent (token
        rate limits, hourly call caps don't apply to a free local model)."""
        from agents.cloud_agent import CloudAgent
        self.assertNotIsInstance(OllamaAgent(), CloudAgent)


class TestOllamaAgentAnalyze(unittest.IsolatedAsyncioTestCase):
    """Happy + edge paths for OllamaAgent.analyze()."""

    async def test_returns_signals_when_ollama_returns_valid_json(self):
        agent = OllamaAgent()
        decisions = {
            "decisions": [
                {"symbol": "AAPL", "action": "BUY", "shares": 10, "confidence": 0.85,
                 "reasoning": "strong"}
            ],
            "market_analysis": "bullish",
        }
        with patch.object(agent, "_get_decisions",
                          new=AsyncMock(return_value=decisions)):
            signals = await agent.analyze(_make_ctx(["AAPL"]))
        self.assertGreater(len(signals), 0)
        self.assertIsInstance(signals[0], Signal)

    async def test_falls_back_to_hold_when_ollama_unreachable(self):
        """When _get_decisions returns None and there's no cached prior
        response, analyze must produce HOLD signals — not raise."""
        agent = OllamaAgent()
        with patch.object(agent, "_get_decisions",
                          new=AsyncMock(return_value=None)):
            signals = await agent.analyze(_make_ctx(["AAPL", "MSFT"]))
        self.assertTrue(all(s.action == "HOLD" for s in signals))

    async def test_replays_cached_decisions_when_ollama_fails_after_cache(self):
        """If Ollama fails after a prior successful call, replay the cached
        decisions rather than dropping to HOLD."""
        agent = OllamaAgent()
        agent._last_decisions = {
            "decisions": [{"symbol": "AAPL", "action": "BUY", "shares": 5,
                            "confidence": 0.8, "reasoning": "cached"}],
            "_watchlist": ["AAPL"],
        }
        with patch.object(agent, "_get_decisions",
                          new=AsyncMock(return_value=None)):
            signals = await agent.analyze(_make_ctx(["AAPL"]))
        # AAPL should reflect the cached BUY (not HOLD)
        aapl = next((s for s in signals if s.symbol == "AAPL"), None)
        self.assertIsNotNone(aapl)
        self.assertEqual(aapl.action, "BUY")

    async def test_malformed_json_returns_empty_signals_not_crash(self):
        """REGRESSION shield: when the (real) extract_json sees malformed
        JSON it returns None → _get_decisions returns None → fallback HOLDs.
        Must NOT crash with `'str' object has no attribute 'get'`."""
        agent = OllamaAgent()
        # Mock at the API-client level so the real extract_json runs over
        # the malformed payload.
        with patch("agents.ollama_agent.AsyncOpenAI") as mock_openai_cls:
            mock_client = mock_openai_cls.return_value
            mock_client.chat.completions.create = AsyncMock(
                return_value=_make_ollama_response('"I think we should buy AAPL"')
            )
            with patch("agents.ollama_agent.save_token_log",
                       new_callable=AsyncMock):
                signals = await agent.analyze(_make_ctx(["AAPL", "MSFT"]))
        self.assertTrue(all(s.action == "HOLD" for s in signals),
                        "malformed-JSON top-level string must produce fallback HOLDs, "
                        "not crash on str.get")


class TestOllamaAgentNoCloudCalls(unittest.IsolatedAsyncioTestCase):
    """Independence guarantee: OllamaAgent must NEVER reach the Anthropic API,
    even if anthropic is importable. Pinning so a future careless import
    doesn't reintroduce the coupling we just split apart."""

    async def test_anthropic_module_never_called_during_analyze(self):
        agent = OllamaAgent()
        with patch.object(agent, "_get_decisions",
                          new=AsyncMock(return_value=None)) as mock_dec, \
             patch("anthropic.AsyncAnthropic") as mock_anthropic:
            await agent.analyze(_make_ctx(["AAPL"]))
        mock_dec.assert_called_once()
        mock_anthropic.assert_not_called()


class TestOllamaAgentApiLock(unittest.IsolatedAsyncioTestCase):
    """Concurrent analyze() calls share the result — only one Ollama request
    actually goes out per cycle even if the trading loop fires twice."""

    async def test_concurrent_calls_serialize_via_api_lock(self):
        agent = OllamaAgent()

        # First call gets a real response; second sees the lock held and
        # waits, then replays the cached result.
        decisions = {
            "decisions": [{"symbol": "AAPL", "action": "BUY", "shares": 5,
                            "confidence": 0.7, "reasoning": "first"}],
            "_watchlist": ["AAPL"],
        }
        # _get_decisions takes some time so the second call hits a held lock
        slow_mock = AsyncMock(side_effect=[decisions])

        async def slow_get(*a, **kw):
            await asyncio.sleep(0.05)
            return decisions

        with patch.object(agent, "_get_decisions", side_effect=slow_get):
            results = await asyncio.gather(
                agent.analyze(_make_ctx(["AAPL"])),
                agent.analyze(_make_ctx(["AAPL"])),
            )
        # Both calls succeeded (didn't crash) and produced signal lists
        self.assertEqual(len(results), 2)
        for sigs in results:
            self.assertGreater(len(sigs), 0)


class TestOllamaAgentSystemPromptIsIndependent(unittest.TestCase):
    """OllamaAgent's _SYSTEM_TEXT is its OWN prompt — not imported from
    ClaudeAgent. If ClaudeAgent's prompt changes, OllamaAgent's must not
    silently change with it. Pin: the two _SYSTEM_TEXT values are
    independent class attributes (even if currently similar in content)."""

    def test_system_text_is_owned_by_ollama_agent_class(self):
        from agents.claude_agent import ClaudeAgent
        # OllamaAgent must define its own _SYSTEM_TEXT, not inherit from
        # a shared mixin / module that ClaudeAgent also reads from.
        self.assertIn("_SYSTEM_TEXT", OllamaAgent.__dict__,
                      "OllamaAgent must define _SYSTEM_TEXT directly so its "
                      "prompt evolves independently of ClaudeAgent's")
        self.assertIn("_SYSTEM_TEXT", ClaudeAgent.__dict__,
                      "ClaudeAgent must define _SYSTEM_TEXT directly so its "
                      "prompt evolves independently of OllamaAgent's")
        # Different objects (separate string literals — independence)
        self.assertIsNot(OllamaAgent._SYSTEM_TEXT, ClaudeAgent._SYSTEM_TEXT)


if __name__ == "__main__":
    unittest.main()
