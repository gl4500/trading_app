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
                # analyst_consensus set high enough (0.5) so the entropy pre-filter
                # (mean abs threshold = 0.08) does not suppress signals in tests.
                "analyst_consensus":    {"score": 0.5},
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

    async def test_buy_blocked_when_mean_wfe_negative(self):
        """High-conviction BUY must be downgraded to HOLD when mean_wfe < 0."""
        # Use the SELECTOR singleton (resolves to SignalCNN or SignalXGBoost
        # based on MODEL_BACKEND), since cnn_reasoning_agent imports `signal_cnn`
        # via that selector. .env may set MODEL_BACKEND=xgboost in which case
        # data.cnn_model.signal_cnn would be a different object.
        from data.signal_model import signal_model as signal_cnn
        mkt = _make_market(["AAPL"], price=150.0)
        buy_resp = {"action": "BUY", "confidence": 0.85, "reasoning": "strong"}
        # Simulate a completed walk-forward retrain with a bad mean_wfe
        original_mean_wfe = signal_cnn._mean_wfe
        try:
            signal_cnn._mean_wfe = -0.43
            with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
                 patch.object(self.agent, "_ollama_decision",
                              new=AsyncMock(return_value=buy_resp)):
                signals = await self.agent.analyze(mkt)
            buys = [s for s in signals if s.action == "BUY"]
            holds = [s for s in signals if s.action == "HOLD"]
            self.assertEqual(len(buys), 0,
                             "WFE gate must downgrade BUY to HOLD when mean_wfe < 0")
            self.assertEqual(len(holds), 1)
            self.assertIn("WFE gate", holds[0].reasoning)
        finally:
            signal_cnn._mean_wfe = original_mean_wfe

    async def test_buy_allowed_when_mean_wfe_positive(self):
        """When mean_wfe >= 0, BUY signals should pass the gate."""
        # Use the SELECTOR singleton (resolves to SignalCNN or SignalXGBoost
        # based on MODEL_BACKEND), since that's what cnn_reasoning_agent
        # imports as `signal_cnn`. Local .env may set MODEL_BACKEND=xgboost,
        # in which case data.cnn_model.signal_cnn would be a different
        # object than the agent uses.
        from data.signal_model import signal_model as signal_cnn
        mkt = _make_market(["AAPL"], price=150.0)
        buy_resp = {"action": "BUY", "confidence": 0.85, "reasoning": "strong"}
        original_mean_wfe = signal_cnn._mean_wfe
        try:
            signal_cnn._mean_wfe = 0.10
            with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
                 patch.object(self.agent, "_ollama_decision",
                              new=AsyncMock(return_value=buy_resp)):
                signals = await self.agent.analyze(mkt)
            buys = [s for s in signals if s.action == "BUY"]
            self.assertEqual(len(buys), 1, "WFE gate must not block when mean_wfe >= 0")
        finally:
            signal_cnn._mean_wfe = original_mean_wfe

    async def test_buy_allowed_when_mean_wfe_unmeasured(self):
        """When mean_wfe is None (no walk-forward retrain yet), gate is inactive."""
        # Use the SELECTOR singleton (resolves to SignalCNN or SignalXGBoost
        # based on MODEL_BACKEND), since that's what cnn_reasoning_agent
        # imports as `signal_cnn`. Local .env may set MODEL_BACKEND=xgboost,
        # in which case data.cnn_model.signal_cnn would be a different
        # object than the agent uses.
        from data.signal_model import signal_model as signal_cnn
        mkt = _make_market(["AAPL"], price=150.0)
        buy_resp = {"action": "BUY", "confidence": 0.85, "reasoning": "strong"}
        original_mean_wfe = signal_cnn._mean_wfe
        try:
            signal_cnn._mean_wfe = None
            with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
                 patch.object(self.agent, "_ollama_decision",
                              new=AsyncMock(return_value=buy_resp)):
                signals = await self.agent.analyze(mkt)
            buys = [s for s in signals if s.action == "BUY"]
            self.assertEqual(len(buys), 1, "WFE gate must be inactive when mean_wfe is None")
        finally:
            signal_cnn._mean_wfe = original_mean_wfe

    async def test_unrealized_drawdown_gate_blocks_buy_when_underwater(self):
        """When CNN's open positions have collective uPnL < threshold,
        new BUYs must downgrade to HOLD. Mirror today's incident: 32 open
        positions at -$2.1k unrealized triggered nothing because there
        was no portfolio-level guard."""
        from config import config
        # Pre-load CNN's portfolio with a deeply-underwater position. Default
        # STARTING_CAPITAL is $100k, so we need a meaningful loss to push
        # uPnL_pct below -2%. Position: 200 shares @ $200 cost, current $100
        # → uPnL = (100-200)*200 = -$20,000. Portfolio total value = $100k
        # cash + 200*$100 = $120k. uPnL_pct = -20000/120000 ≈ -16.7% << -2%,
        # gate fires definitively.
        self.agent.portfolio.positions["NVDA"] = Position(
            symbol="NVDA", shares=200, avg_cost=200.0,
        )
        mkt = {
            "NVDA": _make_ctx(price=100.0, composite=0.5),    # crashed
            "AAPL": _make_ctx(price=150.0, composite=0.5),    # the BUY candidate
            "__overnight_catalysts__": [],
        }
        buy_resp = {"action": "BUY", "confidence": 0.85, "reasoning": "strong"}
        from data.signal_model import signal_model as signal_cnn
        original_mean_wfe = signal_cnn._mean_wfe
        try:
            signal_cnn._mean_wfe = 0.10   # WFE gate inactive (positive)
            with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
                 patch.object(self.agent, "_ollama_decision",
                              new=AsyncMock(return_value=buy_resp)):
                signals = await self.agent.analyze(mkt)
            aapl_buys = [s for s in signals if s.symbol == "AAPL" and s.action == "BUY"]
            aapl_holds = [s for s in signals if s.symbol == "AAPL" and s.action == "HOLD"]
            self.assertEqual(len(aapl_buys), 0,
                "uPnL drawdown gate must block AAPL BUY when CNN portfolio is underwater")
            self.assertEqual(len(aapl_holds), 1)
            self.assertIn("uPnL drawdown gate", aapl_holds[0].reasoning)
        finally:
            signal_cnn._mean_wfe = original_mean_wfe
            self.agent.portfolio.positions.pop("NVDA", None)

    async def test_unrealized_drawdown_gate_passes_when_portfolio_healthy(self):
        """If CNN's open positions are flat or in profit, gate stays inactive."""
        # Position at break-even: 100 shares @ $150, current $150
        self.agent.portfolio.positions["NVDA"] = Position(
            symbol="NVDA", shares=100, avg_cost=150.0,
        )
        mkt = {
            "NVDA": _make_ctx(price=150.0, composite=0.5),
            "AAPL": _make_ctx(price=150.0, composite=0.5),
            "__overnight_catalysts__": [],
        }
        buy_resp = {"action": "BUY", "confidence": 0.85, "reasoning": "strong"}
        from data.signal_model import signal_model as signal_cnn
        original_mean_wfe = signal_cnn._mean_wfe
        try:
            signal_cnn._mean_wfe = 0.10
            with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
                 patch.object(self.agent, "_ollama_decision",
                              new=AsyncMock(return_value=buy_resp)):
                signals = await self.agent.analyze(mkt)
            aapl_buys = [s for s in signals if s.symbol == "AAPL" and s.action == "BUY"]
            self.assertEqual(len(aapl_buys), 1,
                "Healthy portfolio: gate must pass; BUY should fire")
        finally:
            signal_cnn._mean_wfe = original_mean_wfe
            self.agent.portfolio.positions.pop("NVDA", None)

    async def test_unrealized_drawdown_gate_does_not_block_sells(self):
        """SELLs always pass — we never want to trap a position because
        the rest of the portfolio is underwater (that would compound the
        drawdown). Verifies the gate is asymmetric: only BUYs."""
        # Same setup as the underwater test, but Ollama returns SELL on AAPL
        # (which CNN holds, so the SELL is valid).
        self.agent.portfolio.positions["NVDA"] = Position(
            symbol="NVDA", shares=100, avg_cost=150.0,
        )
        self.agent.portfolio.positions["AAPL"] = Position(
            symbol="AAPL", shares=10, avg_cost=180.0,  # also underwater
        )
        mkt = {
            "NVDA": _make_ctx(price=130.0, composite=0.5),    # -$2k uPnL
            "AAPL": _make_ctx(price=160.0, composite=0.5),    # SELL candidate
            "__overnight_catalysts__": [],
        }
        sell_resp = {"action": "SELL", "confidence": 0.80, "reasoning": "exit"}
        from data.signal_model import signal_model as signal_cnn
        original_mean_wfe = signal_cnn._mean_wfe
        try:
            signal_cnn._mean_wfe = 0.10
            with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
                 patch.object(self.agent, "_ollama_decision",
                              new=AsyncMock(return_value=sell_resp)):
                signals = await self.agent.analyze(mkt)
            aapl_sells = [s for s in signals if s.symbol == "AAPL" and s.action == "SELL"]
            self.assertEqual(len(aapl_sells), 1,
                "uPnL drawdown gate must NEVER block SELLs (always allow exits)")
        finally:
            signal_cnn._mean_wfe = original_mean_wfe
            self.agent.portfolio.positions.pop("NVDA", None)
            self.agent.portfolio.positions.pop("AAPL", None)

    async def test_buy_threshold_uses_config_value_065(self):
        """Confidence ratchet: BUY threshold is config.CNN_BUY_THRESHOLD_BASE
        (0.65 default), not the legacy 0.50. A 0.55 confidence — which
        cleared the old gate — must NOT clear the new gate in bull/neutral."""
        from config import config
        mkt = _make_market(["AAPL"], price=150.0)
        # Confidence between old (0.50) and new (0.65) thresholds
        mid_conf_buy = {"action": "BUY", "confidence": 0.55, "reasoning": "borderline"}
        from data.signal_model import signal_model as signal_cnn
        original_mean_wfe = signal_cnn._mean_wfe
        try:
            signal_cnn._mean_wfe = 0.10
            with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
                 patch.object(self.agent, "_ollama_decision",
                              new=AsyncMock(return_value=mid_conf_buy)):
                signals = await self.agent.analyze(mkt)
            buys = [s for s in signals if s.action == "BUY"]
            self.assertEqual(len(buys), 0,
                f"With CNN_BUY_THRESHOLD_BASE={config.CNN_BUY_THRESHOLD_BASE}, "
                f"a 0.55-confidence BUY must NOT pass (was 0.50 threshold pre-fix)")
        finally:
            signal_cnn._mean_wfe = original_mean_wfe

    async def test_max_open_positions_gate_blocks_buy_for_new_symbol_when_at_cap(self):
        """When CNN already holds CNN_MAX_OPEN_POSITIONS distinct symbols,
        a BUY on a NEW symbol must downgrade to HOLD. Prevents the
        diversification-creep failure mode the model review flagged
        (66 open positions on CNNReasoningAgent — far past Kelly-optimal).

        Pinning the test at cap=2 (overridden via patched config) keeps the
        fixture small. Real default is much higher; this just validates the
        gate logic."""
        from config import config
        # Pre-load CNN's portfolio with 2 distinct held symbols (at cap=2)
        self.agent.portfolio.positions["NVDA"] = Position(
            symbol="NVDA", shares=10, avg_cost=150.0,
        )
        self.agent.portfolio.positions["MSFT"] = Position(
            symbol="MSFT", shares=10, avg_cost=300.0,
        )
        mkt = {
            "NVDA": _make_ctx(price=150.0, composite=0.5),
            "MSFT": _make_ctx(price=300.0, composite=0.5),
            "AAPL": _make_ctx(price=150.0, composite=0.5),    # NEW symbol — should be blocked
            "__overnight_catalysts__": [],
        }
        buy_resp = {"action": "BUY", "confidence": 0.85, "reasoning": "strong"}
        from data.signal_model import signal_model as signal_cnn
        original_mean_wfe = signal_cnn._mean_wfe
        original_cap = config.CNN_MAX_OPEN_POSITIONS
        try:
            signal_cnn._mean_wfe = 0.10                # WFE gate inactive
            config.CNN_MAX_OPEN_POSITIONS = 2          # at cap
            with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
                 patch.object(self.agent, "_ollama_decision",
                              new=AsyncMock(return_value=buy_resp)):
                signals = await self.agent.analyze(mkt)
            aapl_buys = [s for s in signals if s.symbol == "AAPL" and s.action == "BUY"]
            aapl_holds = [s for s in signals if s.symbol == "AAPL" and s.action == "HOLD"]
            self.assertEqual(len(aapl_buys), 0,
                "Max-open-positions gate must block BUY on NEW symbol when at cap")
            self.assertEqual(len(aapl_holds), 1)
            self.assertIn("max-open-positions", aapl_holds[0].reasoning.lower())
        finally:
            signal_cnn._mean_wfe = original_mean_wfe
            config.CNN_MAX_OPEN_POSITIONS = original_cap
            self.agent.portfolio.positions.pop("NVDA", None)
            self.agent.portfolio.positions.pop("MSFT", None)

    async def test_max_open_positions_gate_allows_buy_for_already_held_symbol(self):
        """Averaging-into an existing position does NOT increase the count
        of distinct held symbols, so the cap must NOT block it. Otherwise
        we'd kill conviction add-ons (Kelly-style scale-in) — which is the
        opposite of what we want."""
        from config import config
        self.agent.portfolio.positions["NVDA"] = Position(
            symbol="NVDA", shares=10, avg_cost=150.0,
        )
        self.agent.portfolio.positions["MSFT"] = Position(
            symbol="MSFT", shares=10, avg_cost=300.0,
        )
        mkt = {
            "NVDA": _make_ctx(price=150.0, composite=0.5),    # already-held — BUY = avg-down
            "MSFT": _make_ctx(price=300.0, composite=0.5),
            "__overnight_catalysts__": [],
        }
        buy_resp = {"action": "BUY", "confidence": 0.85, "reasoning": "scale in"}
        from data.signal_model import signal_model as signal_cnn
        original_mean_wfe = signal_cnn._mean_wfe
        original_cap = config.CNN_MAX_OPEN_POSITIONS
        try:
            signal_cnn._mean_wfe = 0.10
            config.CNN_MAX_OPEN_POSITIONS = 2
            with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
                 patch.object(self.agent, "_ollama_decision",
                              new=AsyncMock(return_value=buy_resp)):
                signals = await self.agent.analyze(mkt)
            nvda_buys = [s for s in signals if s.symbol == "NVDA" and s.action == "BUY"]
            self.assertEqual(len(nvda_buys), 1,
                "BUY on already-held symbol must pass even at cap (scale-in)")
        finally:
            signal_cnn._mean_wfe = original_mean_wfe
            config.CNN_MAX_OPEN_POSITIONS = original_cap
            self.agent.portfolio.positions.pop("NVDA", None)
            self.agent.portfolio.positions.pop("MSFT", None)

    async def test_max_open_positions_gate_does_not_block_sells(self):
        """SELLs always pass — the cap is asymmetric. Otherwise we'd trap
        positions when the agent is already over-diversified, which is the
        exact moment we MOST want to allow exits."""
        from config import config
        self.agent.portfolio.positions["NVDA"] = Position(
            symbol="NVDA", shares=10, avg_cost=150.0,
        )
        self.agent.portfolio.positions["MSFT"] = Position(
            symbol="MSFT", shares=10, avg_cost=300.0,
        )
        self.agent.portfolio.positions["AAPL"] = Position(
            symbol="AAPL", shares=5, avg_cost=180.0,
        )
        mkt = {
            "NVDA": _make_ctx(price=150.0, composite=0.5),
            "MSFT": _make_ctx(price=300.0, composite=0.5),
            "AAPL": _make_ctx(price=200.0, composite=0.5),  # SELL candidate
            "__overnight_catalysts__": [],
        }
        sell_resp = {"action": "SELL", "confidence": 0.80, "reasoning": "exit"}
        from data.signal_model import signal_model as signal_cnn
        original_mean_wfe = signal_cnn._mean_wfe
        original_cap = config.CNN_MAX_OPEN_POSITIONS
        try:
            signal_cnn._mean_wfe = 0.10
            config.CNN_MAX_OPEN_POSITIONS = 2          # over cap (3 held vs cap=2)
            with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
                 patch.object(self.agent, "_ollama_decision",
                              new=AsyncMock(return_value=sell_resp)):
                signals = await self.agent.analyze(mkt)
            aapl_sells = [s for s in signals if s.symbol == "AAPL" and s.action == "SELL"]
            self.assertEqual(len(aapl_sells), 1,
                "Max-open-positions gate must NEVER block SELLs (always allow exits)")
        finally:
            signal_cnn._mean_wfe = original_mean_wfe
            config.CNN_MAX_OPEN_POSITIONS = original_cap
            for sym in ("NVDA", "MSFT", "AAPL"):
                self.agent.portfolio.positions.pop(sym, None)

    async def test_max_open_positions_gate_inactive_when_under_cap(self):
        """When held-symbol count is below the cap, BUY on a NEW symbol
        passes normally. Pin so a tightening of the cap doesn't accidentally
        also tighten the inactive-state behaviour."""
        from config import config
        self.agent.portfolio.positions["NVDA"] = Position(
            symbol="NVDA", shares=10, avg_cost=150.0,
        )
        mkt = {
            "NVDA": _make_ctx(price=150.0, composite=0.5),
            "AAPL": _make_ctx(price=150.0, composite=0.5),    # NEW — under cap, should pass
            "__overnight_catalysts__": [],
        }
        buy_resp = {"action": "BUY", "confidence": 0.85, "reasoning": "strong"}
        from data.signal_model import signal_model as signal_cnn
        original_mean_wfe = signal_cnn._mean_wfe
        original_cap = config.CNN_MAX_OPEN_POSITIONS
        try:
            signal_cnn._mean_wfe = 0.10
            config.CNN_MAX_OPEN_POSITIONS = 5          # 1 held vs cap=5 — under
            with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
                 patch.object(self.agent, "_ollama_decision",
                              new=AsyncMock(return_value=buy_resp)):
                signals = await self.agent.analyze(mkt)
            aapl_buys = [s for s in signals if s.symbol == "AAPL" and s.action == "BUY"]
            self.assertEqual(len(aapl_buys), 1,
                "Under cap: gate inactive; BUY should fire normally")
        finally:
            signal_cnn._mean_wfe = original_mean_wfe
            config.CNN_MAX_OPEN_POSITIONS = original_cap
            self.agent.portfolio.positions.pop("NVDA", None)

    async def test_lonewolf_discount_when_no_corroborators(self):
        """BUY with 0 other agents agreeing → size_pct halved; reasoning has marker."""
        mkt = _make_market(["AAPL"], price=150.0)
        # No __agent_signals__ → no corroborators
        buy_resp = {"action": "BUY", "confidence": 0.85, "size_pct": 0.10, "reasoning": "strong"}
        with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
             patch.object(self.agent, "_ollama_decision",
                          new=AsyncMock(return_value=buy_resp)):
            signals = await self.agent.analyze(mkt)
        buys = [s for s in signals if s.action == "BUY"]
        self.assertEqual(len(buys), 1)
        self.assertIn("LONE-WOLF", buys[0].reasoning)
        # 10% × 0.5 = 5% of $100k = $5k → $5k / $150 ≈ 33 shares
        self.assertLessEqual(buys[0].shares, 35,
                             "lone-wolf discount must reduce shares")

    async def test_lonewolf_discount_skipped_when_corroborated(self):
        """BUY with 2+ other BUY signals → no discount, no marker."""
        mkt = _make_market(["AAPL"], price=150.0)
        # Inject corroborating BUY signals from two other agents
        mkt["__agent_signals__"] = {
            "AAPL": {
                "TechAgent":     ("BUY", 0.7),
                "MomentumAgent": ("BUY", 0.6),
            }
        }
        buy_resp = {"action": "BUY", "confidence": 0.85, "size_pct": 0.10, "reasoning": "strong"}
        with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
             patch.object(self.agent, "_ollama_decision",
                          new=AsyncMock(return_value=buy_resp)):
            signals = await self.agent.analyze(mkt)
        buys = [s for s in signals if s.action == "BUY"]
        self.assertEqual(len(buys), 1)
        self.assertNotIn("LONE-WOLF", buys[0].reasoning)

    async def test_lonewolf_discount_only_counts_BUY_signals(self):
        """SELL/HOLD signals from other agents do NOT count as corroboration."""
        mkt = _make_market(["AAPL"], price=150.0)
        mkt["__agent_signals__"] = {
            "AAPL": {
                "TechAgent":     ("SELL", 0.7),  # disagreement
                "MomentumAgent": ("HOLD", 0.5),  # neutral, not a buy
            }
        }
        buy_resp = {"action": "BUY", "confidence": 0.85, "size_pct": 0.10, "reasoning": "strong"}
        with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
             patch.object(self.agent, "_ollama_decision",
                          new=AsyncMock(return_value=buy_resp)):
            signals = await self.agent.analyze(mkt)
        buys = [s for s in signals if s.action == "BUY"]
        self.assertEqual(len(buys), 1)
        self.assertIn("LONE-WOLF", buys[0].reasoning,
                      "SELL/HOLD must not count as corroboration")

    async def test_daily_move_risk_alert_injected_when_position_drops(self):
        """Held position down >5% today triggers risk alert injected into prompt."""
        # Setup: buy AAPL at $100, then today's price drops to $94 (-6%)
        self.agent.portfolio.execute_buy("AAPL", 10, 100.0)
        mkt = _make_market(["AAPL"], price=94.0)
        hold_resp = {"action": "HOLD", "confidence": 0.5, "reasoning": "test"}
        captured_prompts = []

        async def _capture(prompt):
            captured_prompts.append(prompt)
            return hold_resp

        with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
             patch.object(self.agent, "_ollama_decision", side_effect=_capture):
            await self.agent.analyze(mkt)

        self.assertEqual(len(captured_prompts), 1)
        self.assertIn("RISK ALERT", captured_prompts[0])
        self.assertIn("6.0% TODAY", captured_prompts[0])

    async def test_daily_move_risk_alert_not_injected_below_threshold(self):
        """Held position down 3% (below 5% threshold) → no risk alert."""
        self.agent.portfolio.execute_buy("AAPL", 10, 100.0)
        mkt = _make_market(["AAPL"], price=97.0)  # only -3%
        hold_resp = {"action": "HOLD", "confidence": 0.5, "reasoning": "test"}
        captured_prompts = []

        async def _capture(prompt):
            captured_prompts.append(prompt)
            return hold_resp

        with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
             patch.object(self.agent, "_ollama_decision", side_effect=_capture):
            await self.agent.analyze(mkt)

        self.assertEqual(len(captured_prompts), 1)
        self.assertNotIn("RISK ALERT", captured_prompts[0])

    async def test_daily_move_risk_alert_not_for_unowned_symbol(self):
        """Symbol we don't hold → never triggers a risk alert (no position to alert on)."""
        # No execute_buy — we don't hold AAPL
        mkt = _make_market(["AAPL"], price=50.0)  # massive "drop" from non-existent open
        hold_resp = {"action": "HOLD", "confidence": 0.5, "reasoning": "test"}
        captured_prompts = []

        async def _capture(prompt):
            captured_prompts.append(prompt)
            return hold_resp

        with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
             patch.object(self.agent, "_ollama_decision", side_effect=_capture):
            await self.agent.analyze(mkt)

        self.assertEqual(len(captured_prompts), 1)
        self.assertNotIn("RISK ALERT", captured_prompts[0])

    async def test_risk_alert_bypasses_entropy_prefilter(self):
        """When a risk alert fires, the entropy pre-filter must NOT skip Ollama."""
        self.agent.portfolio.execute_buy("AAPL", 10, 100.0)
        # Build a market context with low source magnitudes (would normally
        # trigger entropy skip)
        ctx = _make_ctx(price=92.0)  # -8% drop today
        ctx["composite_signal"] = {
            "composite_score": 0.0,
            "sources": {
                "analyst_consensus":    {"score": 0.0},
                "earnings_surprise":    {"score": 0.0},
                "alpaca_news":          {"score": 0.0},
                "yahoo_news":           {"score": 0.0},
                "congressional_trades": {"score": 0.0},
            },
        }
        mkt = {"AAPL": ctx}
        hold_resp = {"action": "HOLD", "confidence": 0.5, "reasoning": "test"}

        with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
             patch.object(self.agent, "_ollama_decision",
                          new=AsyncMock(return_value=hold_resp)) as mock_ollama:
            await self.agent.analyze(mkt)

        # Ollama must have been called despite low magnitude — risk alert overrides
        self.assertEqual(mock_ollama.await_count, 1)


class TestCNNPromptCatalystsAndMacro(unittest.TestCase):
    """_build_prompt includes sentinel catalysts and macro context when present."""

    def setUp(self):
        self.agent = CNNReasoningAgent()
        self.base_kwargs = dict(
            symbol="AAPL", price=150.0, pred_return=0.01, direction="bull",
            cnn_conf=0.7,
            # learned_weights keys are CNN channel names (Task #22 renamed earnings).
            # current_scores keys are LLM-source names (signed values for prompt context).
            learned_weights={"analyst_consensus": 0.35, "earnings_magnitude": 0.22,
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

    def test_step5_treats_cnn_confidence_as_one_input(self):
        """Step 5 must instruct Ollama to compute its OWN confidence from
        evidence agreement, not copy the CNN confidence as a default."""
        prompt = self.agent._build_prompt(**self.base_kwargs, catalysts=None, macro_text="")
        self.assertIn("Set your OWN confidence", prompt)
        self.assertIn("ONE input among many", prompt)
        # Must NOT instruct the LLM to set confidence to CNN value
        self.assertNotIn("Set confidence to the CNN confidence value", prompt)

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
                "composite_signal": {
                    "composite_score": 0.1,
                    "sources": {"analyst_consensus": {"score": 0.5}},
                },
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
                "composite_signal": {
                    "composite_score": 0.1,
                    "sources": {"analyst_consensus": {"score": 0.5}},
                },
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


# ── Portfolio context + goal-aware sizing tests ───────────────────────────────

class TestCNNPortfolioContext(unittest.TestCase):
    """_build_portfolio_context computes the right values."""

    def setUp(self):
        self.agent = CNNReasoningAgent()

    def test_returns_required_keys(self):
        ctx = self.agent._build_portfolio_context({})
        for key in ("total_value", "cash", "deployed_pct", "ytd_pnl", "annual_goal", "pace_diff"):
            self.assertIn(key, ctx)

    def test_deployed_pct_zero_when_all_cash(self):
        ctx = self.agent._build_portfolio_context({})
        self.assertAlmostEqual(ctx["deployed_pct"], 0.0, places=1)

    def test_ytd_pnl_negative_when_below_starting_capital(self):
        self.agent.portfolio.cash = 80_000.0
        ctx = self.agent._build_portfolio_context({})
        self.assertLess(ctx["ytd_pnl"], 0)

    def test_ytd_pnl_positive_when_above_starting_capital(self):
        self.agent.portfolio.cash = 120_000.0
        ctx = self.agent._build_portfolio_context({})
        self.assertGreater(ctx["ytd_pnl"], 0)

    def test_annual_goal_matches_config(self):
        from config import config
        ctx = self.agent._build_portfolio_context({})
        self.assertEqual(ctx["annual_goal"], config.ANNUAL_GOAL)

    def test_pace_diff_negative_when_behind(self):
        """Starting at $100K with no gains → always behind a non-zero annual goal."""
        ctx = self.agent._build_portfolio_context({})
        self.assertLess(ctx["pace_diff"], 0)


class TestCNNPromptPortfolioSection(unittest.TestCase):
    """_build_prompt includes Portfolio Context when portfolio_context is provided."""

    def setUp(self):
        self.agent = CNNReasoningAgent()
        self.base_kwargs = dict(
            symbol="AAPL", price=150.0, pred_return=0.01, direction="bull",
            cnn_conf=0.7,
            # learned_weights keys are CNN channel names (Task #22 renamed earnings).
            learned_weights={"analyst_consensus": 0.35, "earnings_magnitude": 0.22,
                             "alpaca_news": 0.18, "yahoo_news": 0.12,
                             "congressional_trades": 0.13},
            current_scores={"analyst_consensus": 0.1, "earnings_surprise": None,
                            "alpaca_news": 0.0, "yahoo_news": 0.0,
                            "congressional_trades": 0.0},
            composite_score=0.05,
            catalysts=None,
            macro_text="",
        )

    def test_portfolio_section_absent_when_not_provided(self):
        prompt = self.agent._build_prompt(**self.base_kwargs)
        self.assertNotIn("Portfolio Context", prompt)

    def test_portfolio_section_present_when_provided(self):
        pctx = {"total_value": 95000, "cash": 60000, "deployed_pct": 37.0,
                "ytd_pnl": -5000, "annual_goal": 50000, "pace_diff": -8000}
        prompt = self.agent._build_prompt(**self.base_kwargs, portfolio_context=pctx)
        self.assertIn("Portfolio Context", prompt)

    def test_total_value_in_prompt(self):
        pctx = {"total_value": 95000, "cash": 60000, "deployed_pct": 37.0,
                "ytd_pnl": -5000, "annual_goal": 50000, "pace_diff": -8000}
        prompt = self.agent._build_prompt(**self.base_kwargs, portfolio_context=pctx)
        self.assertIn("95,000", prompt)

    def test_annual_goal_in_prompt(self):
        pctx = {"total_value": 95000, "cash": 60000, "deployed_pct": 37.0,
                "ytd_pnl": -5000, "annual_goal": 50000, "pace_diff": -8000}
        prompt = self.agent._build_prompt(**self.base_kwargs, portfolio_context=pctx)
        self.assertIn("50,000", prompt)

    def test_behind_pace_label_in_prompt(self):
        pctx = {"total_value": 95000, "cash": 60000, "deployed_pct": 37.0,
                "ytd_pnl": -5000, "annual_goal": 50000, "pace_diff": -8000}
        prompt = self.agent._build_prompt(**self.base_kwargs, portfolio_context=pctx)
        self.assertIn("behind", prompt)

    def test_ahead_pace_label_in_prompt(self):
        pctx = {"total_value": 160000, "cash": 60000, "deployed_pct": 37.0,
                "ytd_pnl": 60000, "annual_goal": 50000, "pace_diff": 10000}
        prompt = self.agent._build_prompt(**self.base_kwargs, portfolio_context=pctx)
        self.assertIn("ahead", prompt)

    def test_step5_mentions_size_pct(self):
        """Step 5 must ask Ollama to return size_pct."""
        prompt = self.agent._build_prompt(**self.base_kwargs)
        self.assertIn("size_pct", prompt)

    def test_json_schema_includes_size_pct(self):
        """Output JSON schema in prompt must include size_pct field."""
        prompt = self.agent._build_prompt(**self.base_kwargs)
        self.assertIn('"size_pct"', prompt)


class TestCNNGoalAwareSizing(unittest.IsolatedAsyncioTestCase):
    """analyze() uses size_pct from Ollama to size BUY positions."""

    def setUp(self):
        self.agent = CNNReasoningAgent()
        self.agent.portfolio.cash = 100_000.0

    async def test_buy_uses_size_pct_from_ollama(self):
        """size_pct=0.10 → 10% of $100k portfolio at $100/share = 100 shares.
        Inject 2 corroborators so the lone-wolf discount doesn't apply."""
        mkt = _make_market(["AAPL"], price=100.0)
        mkt["__agent_signals__"] = {"AAPL": {
            "TechAgent":     ("BUY", 0.7),
            "MomentumAgent": ("BUY", 0.6),
        }}
        buy_resp = {"action": "BUY", "confidence": 0.80, "size_pct": 0.10, "reasoning": "strong"}
        with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
             patch.object(self.agent, "_ollama_decision", new=AsyncMock(return_value=buy_resp)):
            signals = await self.agent.analyze(mkt)
        buys = [s for s in signals if s.action == "BUY"]
        self.assertEqual(len(buys), 1)
        self.assertEqual(buys[0].shares, 100)

    async def test_size_pct_clamped_at_max_position_size(self):
        """size_pct > MAX_POSITION_SIZE is clamped to MAX_POSITION_SIZE (15%)."""
        from config import config
        mkt = _make_market(["AAPL"], price=100.0)
        buy_resp = {"action": "BUY", "confidence": 0.90, "size_pct": 0.99, "reasoning": "all in"}
        with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
             patch.object(self.agent, "_ollama_decision", new=AsyncMock(return_value=buy_resp)):
            signals = await self.agent.analyze(mkt)
        buys = [s for s in signals if s.action == "BUY"]
        # MAX_POSITION_SIZE of $100k at $100 = 150 shares max
        self.assertLessEqual(buys[0].shares, int(100_000 * config.MAX_POSITION_SIZE / 100) + 1)

    async def test_size_pct_clamped_below_2pct(self):
        """size_pct < 0.02 is raised to 0.02 (minimum meaningful position)."""
        mkt = _make_market(["AAPL"], price=100.0)
        buy_resp = {"action": "BUY", "confidence": 0.75, "size_pct": 0.001, "reasoning": "tiny"}
        with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
             patch.object(self.agent, "_ollama_decision", new=AsyncMock(return_value=buy_resp)):
            signals = await self.agent.analyze(mkt)
        buys = [s for s in signals if s.action == "BUY"]
        # 2% of $100k at $100 = 20 shares minimum
        self.assertGreaterEqual(buys[0].shares, 20)

    async def test_missing_size_pct_defaults_to_10pct(self):
        """If Ollama omits size_pct, fall back to 10% of portfolio value.
        Inject 2 corroborators so the lone-wolf discount doesn't apply."""
        mkt = _make_market(["AAPL"], price=100.0)
        mkt["__agent_signals__"] = {"AAPL": {
            "TechAgent":     ("BUY", 0.7),
            "MomentumAgent": ("BUY", 0.6),
        }}
        buy_resp = {"action": "BUY", "confidence": 0.75, "reasoning": "no size"}
        with patch.object(self.agent, "_ensure_model", new=AsyncMock()), \
             patch.object(self.agent, "_ollama_decision", new=AsyncMock(return_value=buy_resp)):
            signals = await self.agent.analyze(mkt)
        buys = [s for s in signals if s.action == "BUY"]
        # 10% of $100k at $100 = 100 shares
        self.assertEqual(buys[0].shares, 100)


if __name__ == "__main__":
    unittest.main()
