"""
Tests for OpenClawAgent — local model routing via OpenClaw gateway.
"""
import asyncio
import json
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import pandas as pd

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── Stub heavy dependencies that may not be available in the test environment ──
def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules.setdefault(name, mod)
    return mod

# Stub pydantic_core so alpaca can be imported without the native extension
_pydantic_core_inner = _stub("pydantic_core._pydantic_core", __version__="2.0.0")
_pydantic_core       = _stub("pydantic_core", __version__="2.0.0",
                              _pydantic_core=_pydantic_core_inner,
                              core_schema=_stub("pydantic_core.core_schema"))
_stub("pydantic.version", VERSION="2.0.0", version_short=lambda: "2.0")
_stub("pydantic.warnings")
_stub("pydantic._migration", getattr_migration=lambda _: lambda *a, **kw: None)
_stub("pydantic",
      BaseModel=object, Field=lambda *a, **kw: None,
      validator=lambda *a, **kw: lambda f: f,
      root_validator=lambda *a, **kw: lambda f: f)

_stub("alpaca")
_stub("alpaca.common")
_stub("alpaca.common.models", ValidateBaseModel=object)
_stub("alpaca.common.rest", RESTClient=object)
_stub("alpaca.data")
_stub("alpaca.data.models")
_stub("alpaca.data.models.bars")
_stub("alpaca.data.historical")
_stub("alpaca.data.historical.news", NewsClient=object)
_stub("alpaca.data.requests", NewsRequest=object)
# ──────────────────────────────────────────────────────────────────────────────

from agents.openclaw_agent import OpenClawAgent, _build_compact_prompt


def _run(coro):
    return asyncio.run(coro)


def _make_context(symbols=("AAPL", "MSFT")):
    ctx = {}
    for sym in symbols:
        bars = pd.DataFrame({
            "timestamp": ["2026-03-15", "2026-03-16", "2026-03-17", "2026-03-18", "2026-03-19"],
            "open":  [180.0, 181.0, 182.0, 183.0, 184.0],
            "high":  [185.0, 186.0, 187.0, 188.0, 189.0],
            "low":   [179.0, 180.0, 181.0, 182.0, 183.0],
            "close": [182.0, 183.0, 184.0, 185.0, 186.0],
            "volume": [1_000_000] * 5,
        })
        ctx[sym] = {
            "price": 186.0,
            "bars": bars,
            "stats": {"price_change_1d": 1.2, "price_change_5d": 2.5, "price_change_20d": 5.0},
            "indicators": {"rsi": 54.0, "macd_signal": "bullish"},
            "news": [{"headline": f"{sym} quarterly results beat estimates", "summary": "Strong growth.", "source": "Reuters", "date": "2026-03-19"}],
        }
    return ctx


MOCK_RESPONSE = {
    "decisions": [
        {"symbol": "AAPL", "action": "BUY",  "shares": 10, "confidence": 0.75, "reasoning": "Strong momentum"},
        {"symbol": "MSFT", "action": "HOLD", "shares": 0,  "confidence": 0.55, "reasoning": "Neutral"},
    ]
}


class TestCompactPromptBuilder(unittest.TestCase):
    """Unit tests for the compact prompt builder (no API calls)."""

    def test_prompt_contains_symbols(self):
        ctx = _make_context(["AAPL", "MSFT"])
        prompt = _build_compact_prompt(ctx, ["AAPL", "MSFT"], cash=50_000.0, positions={})
        self.assertIn("AAPL", prompt)
        self.assertIn("MSFT", prompt)

    def test_prompt_contains_price(self):
        ctx = _make_context(["AAPL"])
        prompt = _build_compact_prompt(ctx, ["AAPL"], cash=50_000.0, positions={})
        self.assertIn("186", prompt)

    def test_prompt_contains_news_headline(self):
        ctx = _make_context(["AAPL"])
        prompt = _build_compact_prompt(ctx, ["AAPL"], cash=50_000.0, positions={})
        self.assertIn("beat", prompt)

    def test_prompt_shorter_than_full_prompt(self):
        ctx = _make_context(["AAPL", "MSFT", "GOOGL", "TSLA", "NVDA"])
        prompt = _build_compact_prompt(ctx, ["AAPL", "MSFT", "GOOGL", "TSLA", "NVDA"], cash=50_000.0, positions={})
        # Compact prompt should be under 3000 chars for 5 symbols
        self.assertLess(len(prompt), 3000)

    def test_prompt_includes_portfolio_cash(self):
        ctx = _make_context(["AAPL"])
        prompt = _build_compact_prompt(ctx, ["AAPL"], cash=75_000.0, positions={})
        self.assertIn("75000", prompt.replace(",", "").replace(".00", ""))

    def test_prompt_skips_non_dict_context_entries(self):
        ctx = _make_context(["AAPL"])
        ctx["__massive_macro__"] = "Some macro string"
        prompt = _build_compact_prompt(ctx, ["AAPL"], cash=50_000.0, positions={})
        self.assertIn("AAPL", prompt)
        self.assertNotIn("__massive_macro__", prompt)


class TestOpenClawAgentInit(unittest.TestCase):
    def test_agent_name(self):
        agent = OpenClawAgent()
        self.assertEqual(agent.name, "OpenClawAgent")

    def test_no_client_without_config(self):
        agent = OpenClawAgent()
        with patch("agents.openclaw_agent.config") as mock_cfg:
            mock_cfg.OPENCLAW_BASE_URL = ""
            mock_cfg.OPENCLAW_TOKEN = ""
            client = agent._get_client()
        self.assertIsNone(client)


class TestOpenClawAgentFallback(unittest.TestCase):
    """Agent falls back gracefully when OpenClaw is not configured or not running."""

    def test_returns_signals_when_unconfigured(self):
        agent = OpenClawAgent()
        ctx = _make_context(["AAPL", "MSFT"])
        with patch("agents.openclaw_agent.config") as mock_cfg:
            mock_cfg.OPENCLAW_BASE_URL = ""
            mock_cfg.OPENCLAW_TOKEN = ""
            mock_cfg.MAX_POSITION_SIZE = 0.15
            mock_cfg.WATCHLIST = ["AAPL", "MSFT"]
            signals = _run(agent.analyze(ctx))
        self.assertIsInstance(signals, list)

    def test_returns_signals_on_connection_error(self):
        agent = OpenClawAgent()
        ctx = _make_context(["AAPL", "MSFT"])

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=ConnectionRefusedError("OpenClaw not running")
        )

        with patch("agents.openclaw_agent.config") as mock_cfg:
            mock_cfg.OPENCLAW_BASE_URL = "http://127.0.0.1:18789/v1"
            mock_cfg.OPENCLAW_TOKEN = "test_token"
            mock_cfg.OPENCLAW_MODEL = "llama3.2"
            mock_cfg.MAX_POSITION_SIZE = 0.15
            mock_cfg.WATCHLIST = ["AAPL", "MSFT"]
            agent._get_client = MagicMock(return_value=mock_client)
            signals = _run(agent.analyze(ctx))

        self.assertIsInstance(signals, list)


class TestOpenClawAgentParsesResponse(unittest.TestCase):
    """Agent parses a valid OpenClaw JSON response into signals."""

    def _run_with_mock_response(self, json_body: dict):
        agent = OpenClawAgent()
        ctx = _make_context(["AAPL", "MSFT"])

        mock_choice = MagicMock()
        mock_choice.message.content = json.dumps(json_body)
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("agents.openclaw_agent.config") as mock_cfg:
            mock_cfg.OPENCLAW_BASE_URL = "http://127.0.0.1:18789/v1"
            mock_cfg.OPENCLAW_TOKEN = "test_token"
            mock_cfg.OPENCLAW_MODEL = "llama3.2"
            mock_cfg.MAX_POSITION_SIZE = 0.15
            mock_cfg.WATCHLIST = ["AAPL", "MSFT"]
            agent._get_client = MagicMock(return_value=mock_client)
            return _run(agent.analyze(ctx))

    def test_buy_signal_parsed(self):
        signals = self._run_with_mock_response(MOCK_RESPONSE)
        buy_signals = [s for s in signals if s.action == "BUY" and s.symbol == "AAPL"]
        self.assertTrue(len(buy_signals) >= 1)

    def test_hold_signal_parsed(self):
        signals = self._run_with_mock_response(MOCK_RESPONSE)
        hold_signals = [s for s in signals if s.action == "HOLD" and s.symbol == "MSFT"]
        self.assertTrue(len(hold_signals) >= 1)

    def test_signals_have_reasoning(self):
        signals = self._run_with_mock_response(MOCK_RESPONSE)
        for s in signals:
            self.assertIsInstance(s.reasoning, str)

    def test_handles_json_wrapped_in_markdown(self):
        """Model sometimes wraps JSON in ```json ... ``` code fences."""
        wrapped = {"decisions": MOCK_RESPONSE["decisions"]}
        agent = OpenClawAgent()
        ctx = _make_context(["AAPL", "MSFT"])

        mock_choice = MagicMock()
        mock_choice.message.content = f"```json\n{json.dumps(wrapped)}\n```"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("agents.openclaw_agent.config") as mock_cfg:
            mock_cfg.OPENCLAW_BASE_URL = "http://127.0.0.1:18789/v1"
            mock_cfg.OPENCLAW_TOKEN = "test_token"
            mock_cfg.OPENCLAW_MODEL = "llama3.2"
            mock_cfg.MAX_POSITION_SIZE = 0.15
            mock_cfg.WATCHLIST = ["AAPL", "MSFT"]
            agent._get_client = MagicMock(return_value=mock_client)
            signals = _run(agent.analyze(ctx))

        self.assertIsInstance(signals, list)
        self.assertTrue(len(signals) >= 1)


class TestOpenClawAgentCaching(unittest.TestCase):
    """Agent reuses cached decisions between API call intervals."""

    def test_reuses_cache_on_second_cycle(self):
        agent = OpenClawAgent()
        ctx = _make_context(["AAPL", "MSFT"])

        mock_choice = MagicMock()
        mock_choice.message.content = json.dumps(MOCK_RESPONSE)
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        call_count = 0

        async def counting_create(**kwargs):
            nonlocal call_count
            call_count += 1
            return mock_response

        mock_client = MagicMock()
        mock_client.chat.completions.create = counting_create

        def patched_analyze():
            with patch("agents.openclaw_agent.config") as mock_cfg:
                mock_cfg.OPENCLAW_BASE_URL = "http://127.0.0.1:18789/v1"
                mock_cfg.OPENCLAW_TOKEN = "test_token"
                mock_cfg.OPENCLAW_MODEL = "llama3.2"
                mock_cfg.MAX_POSITION_SIZE = 0.15
                mock_cfg.WATCHLIST = ["AAPL", "MSFT"]
                agent._get_client = MagicMock(return_value=mock_client)
                return _run(agent.analyze(ctx))

        # First call → hits API
        patched_analyze()
        first_call_count = call_count
        self.assertEqual(first_call_count, 1)

        # Second call immediately → should use cache (interval > 1)
        patched_analyze()
        self.assertEqual(call_count, first_call_count)  # no extra API call


if __name__ == "__main__":
    unittest.main()
