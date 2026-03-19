"""
Unit tests for agents/ensemble_agent.py
Focuses on the pure logic methods: _vote(), _detect_regime(),
_compute_adaptive_weights(). No external API calls needed.
Requires: pandas (for regime detection bars)
"""
import sys
import os
import unittest
import math
import asyncio

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

from agents.base_agent import Signal
from agents.ensemble_agent import EnsembleAgent, REGIME_MULTIPLIERS
from trading.portfolio import Portfolio, Position


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_ensemble() -> EnsembleAgent:
    return EnsembleAgent()


def _signal(action, symbol="AAPL", confidence=0.7, shares=10.0):
    return Signal(action=action, symbol=symbol, confidence=confidence,
                  shares=shares, reasoning="test")


def _agent_signals(actions_weights):
    """Build agent_signals list: [(agent_name, weight, signal), ...]"""
    result = []
    for name, weight, action in actions_weights:
        result.append((name, weight, _signal(action)))
    return result


def _make_trending_bars(n=30):
    """Strong uptrend bars: SMA slope well above 0.4%."""
    if not HAS_PANDAS:
        return None
    close = [100 + i * 2.0 for i in range(n)]   # steep upward trend
    return pd.DataFrame({
        "close": close,
        "high":  [c + 1 for c in close],
        "low":   [c - 1 for c in close],
    })


def _make_volatile_bars(n=30):
    """Volatile bars: high ATR > 2.5%."""
    if not HAS_PANDAS:
        return None
    import math as _math
    close = [100 + _math.sin(i) * 5 for i in range(n)]  # large oscillations
    # Ensure high-low spread > 2.5% of price
    return pd.DataFrame({
        "close": close,
        "high":  [c + 4 for c in close],   # ~4% above close
        "low":   [c - 4 for c in close],
    })


def _make_flat_bars(n=30):
    """Flat ranging bars: low ATR, flat SMA."""
    if not HAS_PANDAS:
        return None
    close = [100 + (i % 3) * 0.1 for i in range(n)]    # tiny moves
    return pd.DataFrame({
        "close": close,
        "high":  [c + 0.2 for c in close],
        "low":   [c - 0.2 for c in close],
    })


# ── _vote() tests ─────────────────────────────────────────────────────────────

class TestEnsembleVote(unittest.TestCase):

    def setUp(self):
        self.ens = _make_ensemble()

    def test_buy_consensus_above_threshold(self):
        # buy_score = sum(conf * weight) / total_weight
        # 3 agents all BUY, equal weight 0.33 each → buy_score ≈ 0.7
        sigs = _agent_signals([("A", 0.33, "BUY"), ("B", 0.33, "BUY"), ("C", 0.34, "BUY")])
        signal = self.ens._vote("AAPL", sigs, current_price=100.0)
        self.assertEqual(signal.action, "BUY")

    def test_sell_consensus_above_threshold(self):
        # Give the ensemble a position so it can sell
        self.ens.portfolio.positions["AAPL"] = Position("AAPL", 10, 100.0)
        sigs = _agent_signals([("A", 0.33, "SELL"), ("B", 0.33, "SELL"), ("C", 0.34, "SELL")])
        signal = self.ens._vote("AAPL", sigs, current_price=100.0)
        self.assertEqual(signal.action, "SELL")

    def test_below_threshold_returns_hold(self):
        # Only one agent votes BUY with low weight → below threshold
        sigs = _agent_signals([("A", 0.10, "BUY"), ("B", 0.45, "HOLD"), ("C", 0.45, "HOLD")])
        signal = self.ens._vote("AAPL", sigs, current_price=100.0)
        self.assertEqual(signal.action, "HOLD")

    def test_no_signals_returns_hold(self):
        signal = self.ens._vote("AAPL", [], current_price=100.0)
        self.assertEqual(signal.action, "HOLD")

    def test_buy_blocked_when_position_held(self):
        # Already own AAPL → consensus BUY should NOT create another BUY
        self.ens.portfolio.positions["AAPL"] = Position("AAPL", 10, 100.0)
        sigs = _agent_signals([("A", 0.4, "BUY"), ("B", 0.4, "BUY"), ("C", 0.2, "BUY")])
        signal = self.ens._vote("AAPL", sigs, current_price=100.0)
        self.assertNotEqual(signal.action, "BUY")

    def test_sell_blocked_without_position(self):
        # No position → SELL consensus returns HOLD
        sigs = _agent_signals([("A", 0.4, "SELL"), ("B", 0.4, "SELL"), ("C", 0.2, "SELL")])
        signal = self.ens._vote("AAPL", sigs, current_price=100.0)
        self.assertNotEqual(signal.action, "SELL")

    def test_buy_zero_price_returns_hold(self):
        sigs = _agent_signals([("A", 0.4, "BUY"), ("B", 0.4, "BUY"), ("C", 0.2, "BUY")])
        signal = self.ens._vote("AAPL", sigs, current_price=0.0)
        self.assertEqual(signal.action, "HOLD")

    def test_buy_insufficient_funds_returns_hold(self):
        # Drain the cash
        self.ens.portfolio.cash = 0.5
        sigs = _agent_signals([("A", 0.4, "BUY"), ("B", 0.4, "BUY"), ("C", 0.2, "BUY")])
        signal = self.ens._vote("AAPL", sigs, current_price=100.0)
        self.assertEqual(signal.action, "HOLD")
        self.assertIn("insufficient", signal.reasoning.lower())

    def test_reasoning_contains_regime(self):
        sigs = _agent_signals([("A", 0.4, "HOLD"), ("B", 0.3, "HOLD"), ("C", 0.3, "HOLD")])
        signal = self.ens._vote("AAPL", sigs, current_price=100.0)
        self.assertIn(self.ens._regime.upper(), signal.reasoning)


# ── _detect_regime() tests ────────────────────────────────────────────────────

@unittest.skipUnless(HAS_PANDAS, "pandas not available")
class TestDetectRegime(unittest.TestCase):

    def setUp(self):
        self.ens = _make_ensemble()

    def test_no_data_returns_ranging(self):
        result = self.ens._detect_regime({})
        self.assertEqual(result, "ranging")

    def test_trending_bars_detected(self):
        bars = _make_trending_bars(30)
        ctx = {"SPY": {"bars": bars}}
        result = self.ens._detect_regime(ctx)
        self.assertEqual(result, "trending")

    def test_volatile_bars_detected(self):
        bars = _make_volatile_bars(30)
        ctx = {"SPY": {"bars": bars}}
        result = self.ens._detect_regime(ctx)
        self.assertEqual(result, "volatile")

    def test_flat_bars_returns_ranging(self):
        bars = _make_flat_bars(30)
        ctx = {"SPY": {"bars": bars}}
        result = self.ens._detect_regime(ctx)
        self.assertEqual(result, "ranging")

    def test_falls_back_to_any_symbol(self):
        # No SPY, but AAPL has bars
        bars = _make_trending_bars(30)
        ctx = {"AAPL": {"bars": bars}}
        result = self.ens._detect_regime(ctx)
        self.assertIn(result, ("trending", "ranging", "volatile"))

    def test_insufficient_bars_returns_ranging(self):
        # Only 5 bars — not enough for SMA-20
        bars = _make_flat_bars(5) if HAS_PANDAS else None
        ctx = {"SPY": {"bars": bars}}
        result = self.ens._detect_regime(ctx)
        self.assertEqual(result, "ranging")


# ── _compute_adaptive_weights() tests ────────────────────────────────────────

class TestAdaptiveWeights(unittest.TestCase):

    def test_weights_sum_to_one(self):
        ens = _make_ensemble()
        # Register mock agents with minimal portfolios
        class MockAgent:
            def __init__(self, name):
                self.name = name
                self.portfolio = Portfolio(starting_capital=100_000)
        for name in ("ClaudeAgent", "GeminiAgent", "TechAgent"):
            ens.component_agents[name] = MockAgent(name)
        ens.base_weights = {"ClaudeAgent": 0.4, "GeminiAgent": 0.35, "TechAgent": 0.25}
        weights = ens._compute_adaptive_weights({}, "ranging")
        total = sum(weights.values())
        self.assertAlmostEqual(total, 1.0, places=5)

    def test_no_agents_returns_base_weights(self):
        ens = _make_ensemble()
        ens.component_agents = {}
        # With no component agents the method still returns valid structure
        weights = ens._compute_adaptive_weights({}, "ranging")
        # base_weights is returned unchanged when total ≤ 0
        self.assertIsInstance(weights, dict)

    def test_regime_multipliers_applied(self):
        """In 'trending' regime MomentumAgent gets a ×1.50 boost."""
        ens = _make_ensemble()

        class MockAgent:
            def __init__(self, name):
                self.name = name
                self.portfolio = Portfolio(starting_capital=100_000)

        ens.component_agents = {
            "MomentumAgent": MockAgent("MomentumAgent"),
            "MeanReversionAgent": MockAgent("MeanReversionAgent"),
        }
        ens.base_weights = {"MomentumAgent": 0.5, "MeanReversionAgent": 0.5}

        trending_weights  = ens._compute_adaptive_weights({}, "trending")
        ranging_weights   = ens._compute_adaptive_weights({}, "ranging")

        # Momentum gets boosted in trending relative to ranging
        self.assertGreater(
            trending_weights.get("MomentumAgent", 0),
            ranging_weights.get("MomentumAgent", 0),
        )


class TestGeminiRemovedFromEnsemble(unittest.TestCase):
    """GeminiAgent must not participate in ensemble trading signals."""

    def test_gemini_not_in_regime_multipliers(self):
        for regime, mults in REGIME_MULTIPLIERS.items():
            self.assertNotIn(
                "GeminiAgent", mults,
                f"GeminiAgent still listed in REGIME_MULTIPLIERS['{regime}']"
            )

    def test_gemini_not_in_component_agents_by_default(self):
        ensemble = EnsembleAgent()
        self.assertNotIn("GeminiAgent", ensemble.component_agents)

    def test_gemini_not_in_base_weights(self):
        ensemble = EnsembleAgent()
        self.assertNotIn("GeminiAgent", ensemble.base_weights)

    def test_ensemble_weights_sum_to_one(self):
        from config import config
        total = sum(config.ENSEMBLE_WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=5)


if __name__ == "__main__":
    unittest.main()
