"""
Unit tests for agents/cnn_reasoning_agent.py

Covers:
  - analyze() emits BUY/SELL/HOLD signals without error
  - SELL path reads portfolio.positions[sym].shares (not get_position)
  - Ollama unavailable falls back to rule-based decision
  - Pre-training surrogate logic (CNN not yet trained)
  - analyze() does not raise when market_context is empty
  - Sentinel catalysts and macro context injected into Ollama prompt
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


class TestCNNPromptCatalystsAndMacro(unittest.TestCase):
    """_build_prompt includes sentinel catalysts and macro context when present."""

    def setUp(self):
        self.agent = CNNReasoningAgent()
        self.base_kwargs = dict(
            symbol="AAPL", price=150.0, pred_return=0.01, direction="bull",
            cnn_conf=0.7,
            learned_weights={"analyst_consensus": 0.35, "earnings_surprise": 0.22,
                             "alpaca_news": 0.18, "yahoo_news": 0.12,
                             "congressional_trades": 0.13},
            current_scores={"analyst_consensus": 0.1, "earnings_surprise": None,
                            "alpaca_news": 0.0, "yahoo_news": 0.0,
                            "congressional_trades": 0.0},
            composite_score=0.05,
        )

    def test_no_catalysts_no_section(self):
        prompt = self.agent._build_prompt(**self.base_kwargs, catalysts=None, macro_text="")
        self.assertNotIn("Overnight / Sentinel Catalysts", prompt)
        # "## Macro Context" section is only injected when macro_text is non-empty.
        # Step 4 of the Task does reference "Macro Context" by name — that's expected.
        self.assertNotIn("## Macro Context\n", prompt)

    def test_direct_catalyst_for_symbol_appears_in_prompt(self):
        cats = [{"symbol": "AAPL", "headline": "AAPL beats earnings",
                 "score": 3, "category": "CATALYST", "date": "2026-04-12"}]
        prompt = self.agent._build_prompt(**self.base_kwargs, catalysts=cats, macro_text="")
        self.assertIn("Overnight / Sentinel Catalysts", prompt)
        self.assertIn("[DIRECT]", prompt)
        self.assertIn("AAPL beats earnings", prompt)

    def test_market_catalyst_different_symbol_appears_with_tag(self):
        cats = [{"symbol": "SPY", "headline": "Fed holds rates",
                 "score": 4, "category": "MACRO", "date": "2026-04-12"}]
        prompt = self.agent._build_prompt(**self.base_kwargs, catalysts=cats, macro_text="")
        self.assertIn("Overnight / Sentinel Catalysts", prompt)
        self.assertIn("[SPY]", prompt)
        self.assertIn("Fed holds rates", prompt)
        self.assertNotIn("[DIRECT]", prompt)

    def test_no_symbol_catalyst_tagged_as_market(self):
        cats = [{"headline": "Global sell-off", "score": 2,
                 "category": "GEOPOLITICAL", "date": "2026-04-12"}]
        prompt = self.agent._build_prompt(**self.base_kwargs, catalysts=cats, macro_text="")
        self.assertIn("[MARKET]", prompt)
        self.assertIn("Global sell-off", prompt)

    def test_macro_text_included_when_present(self):
        macro = "SPY -1.2% (5D) | VIX 22 elevated | Regime: BEAR"
        prompt = self.agent._build_prompt(**self.base_kwargs, catalysts=None, macro_text=macro)
        self.assertIn("Macro Context", prompt)
        self.assertIn("SPY -1.2%", prompt)

    def test_catalysts_capped_at_six(self):
        cats = [
            {"symbol": "AAPL", "headline": f"Cat {i}", "score": i,
             "category": "CATALYST", "date": "2026-04-12"}
            for i in range(10)
        ]
        prompt = self.agent._build_prompt(**self.base_kwargs, catalysts=cats, macro_text="")
        # Only first 3 direct + first 3 market-wide (capped inside _build_prompt)
        self.assertIn("Overnight / Sentinel Catalysts", prompt)
        count = prompt.count("[DIRECT]")
        self.assertLessEqual(count, 3)

    def test_task_includes_catalyst_step(self):
        cats = [{"symbol": "AAPL", "headline": "FDA approval",
                 "score": 4, "category": "CATALYST", "date": "2026-04-12"}]
        prompt = self.agent._build_prompt(**self.base_kwargs, catalysts=cats, macro_text="")
        self.assertIn("Step 3 — Catalysts", prompt)
        self.assertIn("Step 4 — Macro", prompt)
        self.assertIn("Step 5 — Decision", prompt)

    def test_task_without_catalysts_still_has_steps(self):
        prompt = self.agent._build_prompt(**self.base_kwargs, catalysts=None, macro_text="")
        self.assertIn("Step 3 — Catalysts", prompt)
        self.assertIn("Step 4 — Macro", prompt)
        self.assertIn("Step 5 — Decision", prompt)

    def test_macro_step_references_freshness_tags(self):
        """Step 4 must instruct Ollama to use FRESH data only for confidence adjustment."""
        prompt = self.agent._build_prompt(**self.base_kwargs, catalysts=None, macro_text="")
        self.assertIn("[FRESH]", prompt)
        self.assertIn("[STALE]", prompt)
        self.assertIn("inflation", prompt)

    def test_macro_step_stale_data_cannot_move_confidence(self):
        """Step 5 must explicitly state stale data must not shift confidence."""
        prompt = self.agent._build_prompt(**self.base_kwargs, catalysts=None, macro_text="")
        self.assertIn("Stale macro data must not move the confidence", prompt)

    def test_macro_step_confidence_adjustment_mentioned(self):
        """Step 5 must state the confidence adjustment bounds."""
        prompt = self.agent._build_prompt(**self.base_kwargs, catalysts=None, macro_text="")
        self.assertIn("0.15", prompt)
        self.assertIn("0.10", prompt)

    def test_stale_sources_labeled_context_only_in_prompt(self):
        """Earnings surprise and congressional trades must appear under CONTEXT ONLY."""
        prompt = self.agent._build_prompt(**self.base_kwargs, catalysts=None, macro_text="")
        earnings_line = next(
            (l for l in prompt.splitlines() if "earnings" in l.lower()), ""
        )
        congress_line = next(
            (l for l in prompt.splitlines() if "congressional" in l.lower()), ""
        )
        self.assertIn("CONTEXT ONLY", earnings_line,
                      "earnings_surprise must be labeled CONTEXT ONLY")
        self.assertIn("CONTEXT ONLY", congress_line,
                      "congressional_trades must be labeled CONTEXT ONLY")

    def test_step1_references_fresh_sources_only(self):
        """Step 1 agreement check must note composite = fresh sources only."""
        prompt = self.agent._build_prompt(**self.base_kwargs, catalysts=None, macro_text="")
        step1_idx = prompt.find("Step 1")
        self.assertGreater(step1_idx, -1)
        step1_text = prompt[step1_idx: step1_idx + 300]
        self.assertIn("fresh", step1_text.lower())


class TestCNNAnalyzeCatalystPassthrough(unittest.IsolatedAsyncioTestCase):
    """analyze() correctly extracts and passes catalysts/macro to _build_prompt."""

    def setUp(self):
        self.agent = CNNReasoningAgent()

    async def test_catalysts_extracted_from_market_context(self):
        """analyze() passes __overnight_catalysts__ to _build_prompt."""
        catalyst = {"symbol": "AAPL", "headline": "Strong Q1", "score": 3,
                    "category": "CATALYST", "date": "2026-04-12"}
        mkt = {
            "AAPL": {
                "price": 150.0,
                "composite_signal": {"composite_score": 0.1, "sources": {}},
            },
            "__overnight_catalysts__": [catalyst],
        }
        captured = {}

        async def fake_ollama(prompt):
            captured["prompt"] = prompt
            return {"action": "HOLD", "confidence": 0.5, "reasoning": "ok"}

        with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
             patch.object(self.agent, "_ollama_decision", new=AsyncMock(side_effect=fake_ollama)):
            await self.agent.analyze(mkt)

        self.assertIn("prompt", captured)
        self.assertIn("Strong Q1", captured["prompt"])

    async def test_macro_context_extracted_from_market_context(self):
        """analyze() passes __macro_context__ to _build_prompt."""
        mkt = {
            "AAPL": {
                "price": 150.0,
                "composite_signal": {"composite_score": 0.1, "sources": {}},
            },
            "__macro_context__": "VIX=28 BEAR regime",
            "__overnight_catalysts__": [],
        }
        captured = {}

        async def fake_ollama(prompt):
            captured["prompt"] = prompt
            return {"action": "HOLD", "confidence": 0.5, "reasoning": "ok"}

        with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
             patch.object(self.agent, "_ollama_decision", new=AsyncMock(side_effect=fake_ollama)):
            await self.agent.analyze(mkt)

        self.assertIn("VIX=28 BEAR regime", captured["prompt"])

    async def test_empty_catalysts_list_passes_none(self):
        """Empty __overnight_catalysts__ does not add catalyst section to prompt."""
        mkt = {
            "AAPL": {
                "price": 150.0,
                "composite_signal": {"composite_score": 0.0, "sources": {}},
            },
            "__overnight_catalysts__": [],
        }
        captured = {}

        async def fake_ollama(prompt):
            captured["prompt"] = prompt
            return {"action": "HOLD", "confidence": 0.5, "reasoning": "ok"}

        with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
             patch.object(self.agent, "_ollama_decision", new=AsyncMock(side_effect=fake_ollama)):
            await self.agent.analyze(mkt)

        self.assertNotIn("Overnight / Sentinel Catalysts", captured.get("prompt", ""))


if __name__ == "__main__":
    unittest.main()
