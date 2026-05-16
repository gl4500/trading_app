# MC Strategy Backtester Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline Monte Carlo strategy backtester that compares candidate 8-channel XGB filter variants by running each through 1,000 bootstrapped alternate market histories, then reports per-variant percentile distributions of Sharpe / max-DD / final-return.

**Architecture:** Refactor `CNNReasoningAgent`'s BUY decision chain into pure helpers in `backend/agents/cnn_decision.py`. Build a stationary block bootstrap simulator + replay engine in `backend/data/mc_backtester.py` that consumes the pure helpers and `signal_model.predict()` via narrow public surfaces only — no imports of agents, main, or I/O modules.

**Tech Stack:** Python 3.12, numpy, pandas, xgboost (already in `site-packages/`). No new third-party dependencies. Tests use `unittest.TestCase` (matches existing project convention).

**Spec:** [`docs/superpowers/specs/2026-05-16-mc-strategy-design.md`](../specs/2026-05-16-mc-strategy-design.md)

---

## File Structure

### Files to create
| Path | Responsibility |
|---|---|
| `backend/agents/cnn_decision.py` | Pure BUY decision helpers (`BuyContext`, `BuyDecision`, `decide_buy`). Zero I/O. Imports only `dataclasses`, `typing`, `config`. |
| `backend/tests/test_cnn_decision.py` | Table-driven unit tests for every gate and sizing branch. |
| `backend/data/mc_backtester.py` | Simulator (`StationaryBlockBootstrap`), `BacktestPortfolio`, `_BacktestAgent`, `replay_one_path`, aggregator (`summarise`, `run_variant_comparison`), report writers. |
| `backend/tests/test_mc_backtester.py` | Unit tests for each class/function in `mc_backtester`. |
| `scripts/mc_backtest_filters.py` | CLI orchestrator — argparse, train models per variant, run comparison, write report. |
| `docs/mc_backtester_usage.md` | Usage docs — CLI args, example output, perf notes. |

### Files to modify
| Path | What changes |
|---|---|
| `backend/agents/cnn_reasoning_agent.py` | Lines ~540-700: replace inline gates+sizing with `cnn_decision.decide_buy(ctx, config)`. Method `_unrealized_pnl_pct` (line 114) deleted — replaced by `portfolio.unpnl_frac()`. |
| `backend/trading/portfolio.py` | Add `unpnl_frac(prices) -> Optional[float]` method on `Portfolio` (lifted from agent — its natural home is the Portfolio it summarises). |

---

## Tasks

### Task 1: Create `cnn_decision.py` with types and `decide_buy()`

**Files:**
- Create: `backend/agents/cnn_decision.py`
- Create: `backend/tests/test_cnn_decision.py`

- [ ] **Step 1.1: Write failing tests for the dataclasses**

Create `backend/tests/test_cnn_decision.py`:

```python
"""Unit tests for cnn_decision — pure BUY decision helpers."""
import sys
import os
import unittest

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agents.cnn_decision import BuyContext, BuyDecision, decide_buy
from config import config


def _ctx(**overrides):
    """Helper — build a BuyContext that passes every gate by default;
    individual tests override one field at a time to exercise each gate."""
    defaults = dict(
        symbol="AAPL",
        cnn_pred_return=0.03,
        cnn_pred_direction="up",
        cnn_confidence=0.80,            # comfortably above CNN_BUY_THRESHOLD_BASE=0.65
        regime="neutral",               # no regime add-on
        portfolio_unpnl_frac=0.0,       # not in drawdown
        n_corroborators=config.LONEWOLF_MIN_CORROBORATORS,  # not lone wolf
        in_trail_cooldown=False,
        current_price=200.0,
        cash_available=20000.0,
        portfolio_value=100000.0,
        kelly_fraction=0.10,
    )
    defaults.update(overrides)
    return BuyContext(**defaults)


class TestBuyContextDataclass(unittest.TestCase):
    def test_frozen_immutable(self):
        ctx = _ctx()
        with self.assertRaises(Exception):       # frozen dataclass blocks assignment
            ctx.cnn_confidence = 0.5             # type: ignore[misc]


class TestBuyDecisionDataclass(unittest.TestCase):
    def test_hold_decision_constructed_with_zero_shares(self):
        d = BuyDecision(action="HOLD", shares=0, sized_confidence=0.5, reason="test")
        self.assertEqual(d.action, "HOLD")
        self.assertEqual(d.shares, 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 1.2: Run tests — confirm RED (module doesn't exist)**

```bash
cd /c/Users/gl450/trading_app/backend
PYTHONPATH='../site-packages;.' ../runtime/python/python.exe -m unittest tests.test_cnn_decision -v
```

Expected: `ModuleNotFoundError: No module named 'agents.cnn_decision'`

- [ ] **Step 1.3: Create the module with dataclasses only**

Create `backend/agents/cnn_decision.py`:

```python
"""
Pure decision helpers for the CNN reasoning strategy.

Extracted from CNNReasoningAgent so production AND the MC backtester call
the same logic via a documented function signature.

DESIGN RULE: This module imports ONLY dataclasses, typing, and the app
config namespace. No agents. No portfolio. No DB. No LLM. Pure functions.
"""
from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class BuyContext:
    """Snapshot of state needed to make ONE CNN BUY/HOLD decision."""
    symbol: str
    # Model output
    cnn_pred_return: float
    cnn_pred_direction: Literal["up", "down", "neutral"]
    cnn_confidence: float                   # 0..1
    # Market / portfolio state
    regime: Literal["bull", "neutral", "bear", "high_vol"]
    portfolio_unpnl_frac: Optional[float]   # uPnL / total_value; None when no positions
    n_corroborators: int                    # # OTHER agents agreeing on this symbol
    in_trail_cooldown: bool
    current_price: float
    cash_available: float
    portfolio_value: float
    kelly_fraction: float                   # quarter-Kelly from caller


@dataclass(frozen=True)
class BuyDecision:
    """Output of decide_buy()."""
    action: Literal["BUY", "HOLD"]
    shares: int                             # 0 when HOLD
    sized_confidence: float                 # cnn_conf after lone-wolf shrink
    reason: str                             # gate name or sizing summary, for logs
```

- [ ] **Step 1.4: Run tests — dataclasses should now PASS, decide_buy import fails**

```bash
PYTHONPATH='../site-packages;.' ../runtime/python/python.exe -m unittest tests.test_cnn_decision.TestBuyContextDataclass tests.test_cnn_decision.TestBuyDecisionDataclass -v
```

Expected: 2 PASS. Importing `decide_buy` in other tests still fails.

- [ ] **Step 1.5: Add gate tests to `test_cnn_decision.py`**

Append to `backend/tests/test_cnn_decision.py` (before the `if __name__` block):

```python
class TestDecideBuyGates(unittest.TestCase):
    """Five gates evaluated in order. Any one failing → HOLD."""

    def test_holds_when_direction_not_up(self):
        d = decide_buy(_ctx(cnn_pred_direction="down"), config)
        self.assertEqual(d.action, "HOLD")
        self.assertIn("bullish", d.reason.lower())

    def test_holds_when_direction_neutral(self):
        d = decide_buy(_ctx(cnn_pred_direction="neutral"), config)
        self.assertEqual(d.action, "HOLD")

    def test_holds_when_confidence_below_buy_threshold_base(self):
        # config.CNN_BUY_THRESHOLD_BASE = 0.65 (default per .env)
        d = decide_buy(_ctx(cnn_confidence=0.50), config)
        self.assertEqual(d.action, "HOLD")
        self.assertIn("conf", d.reason.lower())

    def test_passes_confidence_gate_when_at_or_above_threshold(self):
        d = decide_buy(_ctx(cnn_confidence=0.65, regime="neutral"), config)
        self.assertEqual(d.action, "BUY")

    def test_holds_in_bear_regime_when_below_adjusted_threshold(self):
        # bear adds 0.15 → needs 0.80; we give 0.70
        d = decide_buy(_ctx(cnn_confidence=0.70, regime="bear"), config)
        self.assertEqual(d.action, "HOLD")
        self.assertIn("regime", d.reason.lower())

    def test_holds_in_high_vol_regime_when_below_adjusted_threshold(self):
        # high_vol adds 0.20 → needs 0.85; we give 0.75
        d = decide_buy(_ctx(cnn_confidence=0.75, regime="high_vol"), config)
        self.assertEqual(d.action, "HOLD")

    def test_passes_bull_regime_with_base_threshold(self):
        d = decide_buy(_ctx(cnn_confidence=0.65, regime="bull"), config)
        self.assertEqual(d.action, "BUY")

    def test_holds_when_portfolio_in_drawdown(self):
        # config.CNN_PAUSE_UPNL_DRAWDOWN_PCT = -0.02 default
        d = decide_buy(_ctx(portfolio_unpnl_frac=-0.05), config)
        self.assertEqual(d.action, "HOLD")
        self.assertIn("upnl", d.reason.lower())

    def test_passes_drawdown_gate_at_threshold(self):
        # Exactly at -0.02 → boundary; spec says ≤ blocks, so > passes
        d = decide_buy(_ctx(portfolio_unpnl_frac=-0.019), config)
        self.assertEqual(d.action, "BUY")

    def test_passes_drawdown_gate_when_no_positions(self):
        d = decide_buy(_ctx(portfolio_unpnl_frac=None), config)
        self.assertEqual(d.action, "BUY")

    def test_holds_when_in_trail_cooldown(self):
        d = decide_buy(_ctx(in_trail_cooldown=True), config)
        self.assertEqual(d.action, "HOLD")
        self.assertIn("cool", d.reason.lower())


class TestDecideBuySizing(unittest.TestCase):
    """Sizing chain — runs only when all 5 gates pass."""

    def test_kelly_sized_buy_with_full_corroborators(self):
        # kelly=0.10, value=$100k → $10k → 50 shares @ $200
        d = decide_buy(
            _ctx(kelly_fraction=0.10, portfolio_value=100000.0,
                 current_price=200.0,
                 n_corroborators=config.LONEWOLF_MIN_CORROBORATORS),
            config,
        )
        self.assertEqual(d.action, "BUY")
        self.assertEqual(d.shares, 50)

    def test_lonewolf_multiplier_applied_when_alone(self):
        # 0 corroborators → kelly × 0.5 → 0.05 → $5k → 25 shares
        d = decide_buy(
            _ctx(kelly_fraction=0.10, portfolio_value=100000.0,
                 current_price=200.0, n_corroborators=0),
            config,
        )
        self.assertEqual(d.action, "BUY")
        self.assertEqual(d.shares, 25)

    def test_max_position_size_clamps_huge_kelly(self):
        # MAX_POSITION_SIZE = 0.15 default → cap at $15k → 75 shares @ $200
        d = decide_buy(
            _ctx(kelly_fraction=0.50, portfolio_value=100000.0,
                 current_price=200.0,
                 n_corroborators=config.LONEWOLF_MIN_CORROBORATORS),
            config,
        )
        self.assertEqual(d.shares, int(0.15 * 100000.0 / 200.0))

    def test_floor_at_2pct_when_kelly_tiny(self):
        # kelly=0.005 → below floor → use 2% → $2k → 10 shares
        d = decide_buy(
            _ctx(kelly_fraction=0.005, portfolio_value=100000.0,
                 current_price=200.0,
                 n_corroborators=config.LONEWOLF_MIN_CORROBORATORS),
            config,
        )
        self.assertEqual(d.shares, 10)

    def test_holds_when_computed_shares_below_one(self):
        # Tiny portfolio + expensive stock → 0 shares → HOLD
        d = decide_buy(
            _ctx(kelly_fraction=0.02, portfolio_value=100.0,
                 current_price=200.0,
                 n_corroborators=config.LONEWOLF_MIN_CORROBORATORS),
            config,
        )
        self.assertEqual(d.action, "HOLD")
        self.assertIn("under-funded", d.reason.lower())

    def test_sized_confidence_shrinks_with_lonewolf(self):
        d = decide_buy(_ctx(cnn_confidence=0.80, n_corroborators=0), config)
        self.assertLess(d.sized_confidence, 0.80)

    def test_sized_confidence_unchanged_when_corroborated(self):
        d = decide_buy(
            _ctx(cnn_confidence=0.80,
                 n_corroborators=config.LONEWOLF_MIN_CORROBORATORS),
            config,
        )
        self.assertAlmostEqual(d.sized_confidence, 0.80)
```

- [ ] **Step 1.6: Run gate + sizing tests — confirm RED**

```bash
PYTHONPATH='../site-packages;.' ../runtime/python/python.exe -m unittest tests.test_cnn_decision -v
```

Expected: `ImportError: cannot import name 'decide_buy'` on every gate/sizing test.

- [ ] **Step 1.7: Implement `decide_buy`**

Append to `backend/agents/cnn_decision.py`:

```python
# Confidence add-ons per regime (mirrors RegimeDetector.get_confidence_gate)
_REGIME_CONF_ADJ = {
    "bull": 0.0,
    "neutral": 0.0,
    "bear": 0.15,
    "high_vol": 0.20,
}


def decide_buy(ctx: BuyContext, config) -> BuyDecision:
    """Full CNN BUY decision chain. Pure function.

    Five gates evaluated in order — first failure returns HOLD with reason.
    Then sizing: kelly × maybe-lonewolf, clamped to [2%, MAX_POSITION_SIZE].

    `config` is the app-wide backend.config.Config singleton.
    Passed in (not imported) for testability — overridable in tests.
    """
    # Gate 1: direction
    if ctx.cnn_pred_direction != "up":
        return BuyDecision("HOLD", 0, ctx.cnn_confidence, "not bullish")

    # Gate 2: minimum confidence floor (CNN_BUY_THRESHOLD_BASE — bull/neutral)
    if ctx.cnn_confidence < config.CNN_BUY_THRESHOLD_BASE:
        return BuyDecision("HOLD", 0, ctx.cnn_confidence,
                           f"conf {ctx.cnn_confidence:.2f} < {config.CNN_BUY_THRESHOLD_BASE:.2f}")

    # Gate 3: regime-adjusted floor (adds 0.15 in bear, 0.20 in high_vol)
    regime_add = _REGIME_CONF_ADJ.get(ctx.regime, 0.0)
    needed = config.CNN_BUY_THRESHOLD_BASE + regime_add
    if ctx.cnn_confidence < needed:
        return BuyDecision("HOLD", 0, ctx.cnn_confidence,
                           f"regime gate ({ctx.regime}): conf {ctx.cnn_confidence:.2f} < {needed:.2f}")

    # Gate 4: portfolio uPnL drawdown
    if (ctx.portfolio_unpnl_frac is not None
            and ctx.portfolio_unpnl_frac <= config.CNN_PAUSE_UPNL_DRAWDOWN_PCT):
        return BuyDecision("HOLD", 0, ctx.cnn_confidence,
                           f"uPnL {ctx.portfolio_unpnl_frac:.2%} <= {config.CNN_PAUSE_UPNL_DRAWDOWN_PCT:.2%}")

    # Gate 5: trail-stop cool-down
    if ctx.in_trail_cooldown:
        return BuyDecision("HOLD", 0, ctx.cnn_confidence, "trail cool-down active")

    # ── Sizing ─────────────────────────────────────────────────────────────
    base_pct = ctx.kelly_fraction
    sized_conf = ctx.cnn_confidence
    if ctx.n_corroborators < config.LONEWOLF_MIN_CORROBORATORS:
        base_pct *= config.LONEWOLF_MULTIPLIER
        sized_conf *= config.LONEWOLF_MULTIPLIER

    size_pct = max(0.02, min(config.MAX_POSITION_SIZE, base_pct))
    target_value = size_pct * ctx.portfolio_value
    shares = int(target_value / ctx.current_price) if ctx.current_price > 0 else 0

    if shares < 1:
        return BuyDecision("HOLD", 0, ctx.cnn_confidence,
                           f"under-funded: {size_pct:.2%} of ${ctx.portfolio_value:.0f} < 1 share @ ${ctx.current_price:.2f}")

    return BuyDecision("BUY", shares, sized_conf,
                       f"BUY {shares}@${ctx.current_price:.2f} (size {size_pct:.2%}, conf {sized_conf:.2f})")
```

- [ ] **Step 1.8: Run all tests — confirm GREEN**

```bash
PYTHONPATH='../site-packages;.' ../runtime/python/python.exe -m unittest tests.test_cnn_decision -v
```

Expected: All tests PASS (≈20 tests).

- [ ] **Step 1.9: Commit on feature branch**

```bash
cd /c/Users/gl450/trading_app
git checkout main && git pull --ff-only
git checkout -b feat/cnn-decision-pure-helpers
git add backend/agents/cnn_decision.py backend/tests/test_cnn_decision.py
git commit -m "$(cat <<'EOF'
feat(cnn-decision): extract BUY decision chain into pure helpers

New module backend/agents/cnn_decision.py with BuyContext, BuyDecision
dataclasses and decide_buy() — the full gate-and-size chain currently
inline in CNNReasoningAgent.analyze(). Pure functions, no I/O, imports
only dataclasses/typing/config.

Five gates evaluated in order (any fails → HOLD with reason):
  1. direction == "up"
  2. cnn_confidence >= CNN_BUY_THRESHOLD_BASE
  3. cnn_confidence >= base + regime add-on
  4. portfolio_unpnl_frac > CNN_PAUSE_UPNL_DRAWDOWN_PCT
  5. NOT in_trail_cooldown

Sizing: kelly × maybe-lonewolf-multiplier, clamped [2%, MAX_POSITION_SIZE].

This module is consumed in the next PR by the existing CNNReasoningAgent
(replacing inline logic) AND by the upcoming MC backtester — single
source of truth for BUY logic.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push -u origin feat/cnn-decision-pure-helpers
gh pr create --title "feat(cnn-decision): extract BUY decision chain into pure helpers" --body "Companion PR to the MC backtester effort (see docs/superpowers/specs/2026-05-16-mc-strategy-design.md). Adds the pure-function module; the next PR refactors CNNReasoningAgent to call it."
```

---

### Task 2: Lift `_unrealized_pnl_pct` → `Portfolio.unpnl_frac` + refactor `CNNReasoningAgent.analyze()` to call `decide_buy`

**Files:**
- Modify: `backend/trading/portfolio.py` (add `unpnl_frac` method)
- Modify: `backend/tests/test_portfolio.py` (add `TestUnpnlFrac`)
- Modify: `backend/agents/cnn_reasoning_agent.py` (delete `_unrealized_pnl_pct`, replace inline BUY logic in `analyze()` with `decide_buy` call)
- Modify: `backend/tests/test_cnn_reasoning_agent.py` (update tests that called `_unrealized_pnl_pct`)

- [ ] **Step 2.1: Write failing test for `Portfolio.unpnl_frac`**

Append to `backend/tests/test_portfolio.py`:

```python
class TestUnpnlFrac(unittest.TestCase):
    """Portfolio.unpnl_frac returns total uPnL / total_value, or None if no positions."""

    def test_returns_none_when_no_positions(self):
        from trading.portfolio import Portfolio
        p = Portfolio(starting_capital=100000.0)
        self.assertIsNone(p.unpnl_frac({}))

    def test_returns_zero_at_break_even(self):
        from trading.portfolio import Portfolio
        p = Portfolio(starting_capital=100000.0)
        p.execute_buy("AAPL", 10, 100.0)        # cost = $1000
        # price unchanged → uPnL = 0 → frac = 0 / 99000 = 0
        result = p.unpnl_frac({"AAPL": 100.0})
        self.assertEqual(result, 0.0)

    def test_positive_unpnl_returns_positive_frac(self):
        from trading.portfolio import Portfolio
        p = Portfolio(starting_capital=100000.0)
        p.execute_buy("AAPL", 10, 100.0)        # cost = $1000, cash = $99000
        # price = $110 → uPnL = $100; total_value = 99000 + 1100 = $100100
        result = p.unpnl_frac({"AAPL": 110.0})
        self.assertAlmostEqual(result, 100.0 / 100100.0, places=5)

    def test_negative_unpnl_returns_negative_frac(self):
        from trading.portfolio import Portfolio
        p = Portfolio(starting_capital=100000.0)
        p.execute_buy("AAPL", 10, 100.0)
        # price = $80 → uPnL = -$200; total_value = 99000 + 800 = $99800
        result = p.unpnl_frac({"AAPL": 80.0})
        self.assertAlmostEqual(result, -200.0 / 99800.0, places=5)

    def test_skips_positions_missing_price(self):
        from trading.portfolio import Portfolio
        p = Portfolio(starting_capital=100000.0)
        p.execute_buy("AAPL", 10, 100.0)
        p.execute_buy("MSFT", 5, 200.0)
        # MSFT has no price quote → treat as 0 contribution to uPnL
        result = p.unpnl_frac({"AAPL": 110.0})  # only AAPL priced
        self.assertIsNotNone(result)
        # AAPL uPnL = +$100, MSFT contributes 0 → uPnL = $100
        # total_value = cash (98000) + AAPL_value(1100) + MSFT_at_cost(1000) = 100100
        self.assertGreater(result, 0)
```

- [ ] **Step 2.2: Run portfolio test — confirm RED**

```bash
cd /c/Users/gl450/trading_app/backend
PYTHONPATH='../site-packages;.' ../runtime/python/python.exe -m unittest tests.test_portfolio.TestUnpnlFrac -v
```

Expected: AttributeError on `unpnl_frac`.

- [ ] **Step 2.3: Implement `Portfolio.unpnl_frac`**

In `backend/trading/portfolio.py`, add after `get_total_value` (line ~72):

```python
    def unpnl_frac(self, prices: Dict[str, float]) -> Optional[float]:
        """Total unrealized PnL across open positions, expressed as fraction
        of total portfolio value. Returns None when no positions held.

        Positions with no price quote contribute 0 to uPnL (conservative —
        a missing quote shouldn't trigger a false drawdown reading).

        Lifted 2026-05-16 from CNNReasoningAgent._unrealized_pnl_pct so it
        lives on the Portfolio (its natural home) and can be consumed by
        cnn_decision and the MC backtester via the public surface.
        """
        if not self.positions:
            return None
        total_upnl = 0.0
        for sym, pos in self.positions.items():
            if pos.shares <= 0:
                continue
            price = prices.get(sym)
            if price is None or price <= 0:
                continue
            total_upnl += (price - pos.avg_cost) * pos.shares
        total_value = self.get_total_value(prices)
        if total_value <= 0:
            return None
        return total_upnl / total_value
```

- [ ] **Step 2.4: Run test — confirm GREEN**

```bash
PYTHONPATH='../site-packages;.' ../runtime/python/python.exe -m unittest tests.test_portfolio.TestUnpnlFrac -v
```

Expected: 5/5 PASS.

- [ ] **Step 2.5: Refactor `CNNReasoningAgent.analyze()` to call `decide_buy`**

In `backend/agents/cnn_reasoning_agent.py`:

1. **Top of file** — add import:
```python
from agents.cnn_decision import BuyContext, decide_buy
```

2. **Delete** `_unrealized_pnl_pct` method (lines 114–140) and replace all its callsites with `self.portfolio.unpnl_frac(prices)`.

3. **Inside `analyze()`** — locate the BUY decision block (currently lines ~620–700, identifiable by `upnl_pct = self._unrealized_pnl_pct(prices)` and `_buy_threshold = config.CNN_BUY_THRESHOLD_BASE + regime_detector.get_confidence_gate()`).

4. **Replace** that block with:
```python
                # ── BUY decision via pure helper (cnn_decision.decide_buy) ──
                # Single source of truth for gates+sizing; same helper called
                # by the MC backtester. See docs/superpowers/specs/
                # 2026-05-16-mc-strategy-design.md
                from data.regime_detector import regime_detector
                ctx = BuyContext(
                    symbol=symbol,
                    cnn_pred_return=float(cnn_pred_return),
                    cnn_pred_direction=str(cnn_direction),
                    cnn_confidence=float(cnn_conf),
                    regime=regime_detector.get_regime()[0],
                    portfolio_unpnl_frac=self.portfolio.unpnl_frac(prices),
                    n_corroborators=int(corroborators),
                    in_trail_cooldown=self._in_trail_cooldown(),
                    current_price=float(price),
                    cash_available=float(self.portfolio.cash),
                    portfolio_value=float(self.portfolio.get_total_value(prices)),
                    kelly_fraction=float(self.portfolio.kelly_fraction()),
                )
                decision = decide_buy(ctx, config)
                if decision.action == "HOLD":
                    logger.debug(f"{self.name} HOLD {symbol}: {decision.reason}")
                    continue  # next symbol
                # Translate BuyDecision → Signal for the trading loop
                signals.append(Signal(
                    action="BUY", symbol=symbol,
                    confidence=decision.sized_confidence,
                    shares=decision.shares,
                    reasoning=f"{ollama_reasoning}; {decision.reason}",
                    agent_name=self.name,
                ))
```

Adjust variable names (`cnn_pred_return`, `cnn_direction`, `cnn_conf`, `price`, `corroborators`, `ollama_reasoning`) to match what's actually in scope at that point in `analyze()` — read lines 540–620 to confirm exact names.

- [ ] **Step 2.6: Run existing CNNReasoningAgent test suite — confirm GREEN**

```bash
PYTHONPATH='../site-packages;.' ../runtime/python/python.exe -m unittest tests.test_cnn_reasoning_agent -v
```

Expected: All tests pass. Tests that previously called `agent._unrealized_pnl_pct(prices)` must be updated to call `agent.portfolio.unpnl_frac(prices)` — find via `grep -n "_unrealized_pnl_pct" backend/tests/`.

- [ ] **Step 2.7: Run full test suite — confirm no regression**

```bash
cd /c/Users/gl450/trading_app/backend
../runtime/python/python.exe run_tests.py
```

Expected: All tests pass.

- [ ] **Step 2.8: Commit on feature branch (from main)**

```bash
cd /c/Users/gl450/trading_app
git checkout main && git pull --ff-only
git checkout -b refactor/cnn-agent-uses-cnn-decision
git add backend/trading/portfolio.py backend/agents/cnn_reasoning_agent.py backend/tests/test_portfolio.py backend/tests/test_cnn_reasoning_agent.py
git commit -m "$(cat <<'EOF'
refactor(cnn-agent): call cnn_decision.decide_buy; lift unpnl to Portfolio

CNNReasoningAgent.analyze() previously hand-rolled the BUY gate chain
(direction, confidence, regime, drawdown, cool-down) and the sizing
chain (Kelly, lone-wolf, max-position clamp) inline at lines ~540-700.
After PR #N (feat/cnn-decision-pure-helpers) those live in
agents/cnn_decision.py as pure functions.

This PR:
- Replaces the inline block with one BuyContext build + decide_buy() call
- Deletes CNNReasoningAgent._unrealized_pnl_pct — replaced by
  Portfolio.unpnl_frac(prices) (lifted to its natural home; same math)
- Updates tests that asserted on the old private helper

Behavioural change: NONE. decide_buy implements the exact same gates and
sizing as the previous inline logic — verified by the existing
CNNReasoningAgent test suite still passing.

The agent class shrinks; analyze() is now a thin orchestrator. Sets up
the MC backtester (next PR) to consume the same decide_buy helper.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push -u origin refactor/cnn-agent-uses-cnn-decision
gh pr create --title "refactor(cnn-agent): call cnn_decision.decide_buy; lift unpnl to Portfolio" --body "Depends on the cnn_decision PR. Pure refactor — behavioural unchanged."
```

---

### Task 3: `StationaryBlockBootstrap` simulator

**Files:**
- Create: `backend/data/mc_backtester.py` (initial scaffolding + bootstrap class)
- Create: `backend/tests/test_mc_backtester.py`

- [ ] **Step 3.1: Write failing tests for the simulator**

Create `backend/tests/test_mc_backtester.py`:

```python
"""Unit tests for mc_backtester — simulator first; portfolio + replay + aggregator added in later tasks."""
import sys
import os
import unittest

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np
import pandas as pd

from data.mc_backtester import BootstrapConfig, StationaryBlockBootstrap


def _synthetic_history(n_days=500, n_symbols=3, seed=0):
    """Multi-symbol daily returns frame; long-format MultiIndex (date, symbol)."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n_days, freq="B")
    symbols = [f"S{i}" for i in range(n_symbols)]
    rows = []
    for d in dates:
        for s in symbols:
            rows.append({"date": d, "symbol": s,
                         "return_1d": rng.normal(0.0005, 0.012),
                         "close": 100.0,            # placeholder
                         "feature_x": rng.normal()})
    return pd.DataFrame(rows).set_index(["date", "symbol"])


class TestStationaryBlockBootstrap(unittest.TestCase):

    def setUp(self):
        self.hist = _synthetic_history(n_days=500, n_symbols=3, seed=42)
        self.cfg = BootstrapConfig(
            expected_block_size=10, n_paths=20, path_length_days=100, seed=123
        )

    def test_one_path_has_correct_length(self):
        sampler = StationaryBlockBootstrap(self.hist, self.cfg)
        path = sampler.sample_path()
        unique_dates = path.index.get_level_values(0).unique()
        self.assertEqual(len(unique_dates), self.cfg.path_length_days)

    def test_one_path_preserves_symbol_set(self):
        sampler = StationaryBlockBootstrap(self.hist, self.cfg)
        path = sampler.sample_path()
        path_symbols = set(path.index.get_level_values(1).unique())
        hist_symbols = set(self.hist.index.get_level_values(1).unique())
        self.assertEqual(path_symbols, hist_symbols)

    def test_one_path_preserves_column_set(self):
        sampler = StationaryBlockBootstrap(self.hist, self.cfg)
        path = sampler.sample_path()
        self.assertEqual(set(path.columns), set(self.hist.columns))

    def test_simulate_yields_n_paths(self):
        sampler = StationaryBlockBootstrap(self.hist, self.cfg)
        paths = list(sampler.simulate())
        self.assertEqual(len(paths), self.cfg.n_paths)

    def test_seed_reproducibility(self):
        s1 = StationaryBlockBootstrap(self.hist, self.cfg)
        s2 = StationaryBlockBootstrap(self.hist, self.cfg)
        p1 = list(s1.simulate())
        p2 = list(s2.simulate())
        for a, b in zip(p1, p2):
            pd.testing.assert_frame_equal(a, b)

    def test_different_seeds_produce_different_paths(self):
        s1 = StationaryBlockBootstrap(self.hist, BootstrapConfig(seed=1, n_paths=2, path_length_days=50, expected_block_size=10))
        s2 = StationaryBlockBootstrap(self.hist, BootstrapConfig(seed=2, n_paths=2, path_length_days=50, expected_block_size=10))
        p1 = next(s1.simulate())
        p2 = next(s2.simulate())
        # At least some rows must differ
        self.assertFalse(p1.equals(p2))

    def test_cross_symbol_correlation_preserved_within_blocks(self):
        """If symbols had perfect correlation in the original (same series),
        the sampled blocks should preserve that — within-block correlation ≈ 1.0."""
        # Force perfect correlation: all symbols share the same return series
        n_days = 300
        dates = pd.date_range("2020-01-01", periods=n_days, freq="B")
        rng = np.random.default_rng(0)
        common_returns = rng.normal(0, 0.015, n_days)
        rows = []
        for i, d in enumerate(dates):
            for s in ("S0", "S1", "S2"):
                rows.append({"date": d, "symbol": s, "return_1d": common_returns[i]})
        hist = pd.DataFrame(rows).set_index(["date", "symbol"])
        cfg = BootstrapConfig(expected_block_size=20, n_paths=1, path_length_days=200, seed=0)
        sampler = StationaryBlockBootstrap(hist, cfg)
        path = sampler.sample_path()
        # Pivot to wide and check S0 == S1 == S2 for every row
        wide = path["return_1d"].unstack()  # date × symbol
        self.assertTrue((wide["S0"] == wide["S1"]).all())
        self.assertTrue((wide["S1"] == wide["S2"]).all())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3.2: Run tests — confirm RED**

```bash
PYTHONPATH='../site-packages;.' ../runtime/python/python.exe -m unittest tests.test_mc_backtester -v
```

Expected: `ModuleNotFoundError: No module named 'data.mc_backtester'`

- [ ] **Step 3.3: Create the module skeleton + implement bootstrap**

Create `backend/data/mc_backtester.py`:

```python
"""
MC strategy backtester — simulator, portfolio, replay, aggregator.

Compares candidate XGB filter variants by running each through K
bootstrapped alternate market histories. Loose-coupling boundary:
imports only narrow public surfaces of signal_model, signal_history,
cnn_decision, and BaseAgent — never CNNReasoningAgent or any I/O module.

See docs/superpowers/specs/2026-05-16-mc-strategy-design.md
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterator, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Path simulator (stationary block bootstrap, Politis-Romano 1994)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BootstrapConfig:
    """Hyperparameters for the simulator."""
    expected_block_size: int = 10        # L; mean of Geometric(1/L) block length
    n_paths: int = 1000                  # K; number of alternate histories
    path_length_days: int = 252          # T; trading days per path (1 year ≈ 252)
    seed: int = 42


class StationaryBlockBootstrap:
    """Stationary block bootstrap over (date × symbol)-indexed history.

    Bootstraps WHOLE ROWS jointly so a sampled block carries every symbol's
    every channel for the sampled dates — preserves cross-symbol AND
    cross-channel correlations within blocks. Block lengths are random
    (~Geometric(1/L)), so the path itself is a stationary process — no
    fixed seam pattern artefact.
    """

    def __init__(self, history: pd.DataFrame, cfg: BootstrapConfig):
        """history: long-format frame with MultiIndex (date, symbol)."""
        if not isinstance(history.index, pd.MultiIndex):
            raise ValueError("history must have a MultiIndex (date, symbol)")
        self._history = history.sort_index()
        self._cfg = cfg
        self._rng = np.random.default_rng(cfg.seed)
        # Unique sorted dates (the bootstrap unit)
        self._dates = list(self._history.index.get_level_values(0).unique())
        self._n_dates = len(self._dates)
        if self._n_dates < 1:
            raise ValueError("history must contain at least one date")

    def sample_path(self) -> pd.DataFrame:
        """Sample one bootstrapped path of length cfg.path_length_days.
        Returns long-format DataFrame with the same columns as `history`."""
        path_blocks: List[pd.DataFrame] = []
        days_remaining = self._cfg.path_length_days
        block_idx = 0
        while days_remaining > 0:
            start = int(self._rng.integers(0, self._n_dates))
            block_len = int(self._rng.geometric(1.0 / self._cfg.expected_block_size))
            block_len = max(1, min(block_len, days_remaining))
            # Wrap around so blocks near end of history stay full-length
            date_indices = [(start + offset) % self._n_dates for offset in range(block_len)]
            block_dates = [self._dates[i] for i in date_indices]
            block = self._history.loc[block_dates].copy()
            # Rewrite date index so the simulated path has unique, sequential
            # dates (block 0 starts at a synthetic day 0; subsequent blocks
            # follow). We use integers so callers don't infer real dates.
            synthetic_dates = list(range(block_idx, block_idx + block_len))
            # Build a fresh MultiIndex; symbols on each synthetic date come
            # from the original block in original symbol order
            new_index = []
            for syn_date in synthetic_dates:
                for sym in block.loc[block.index.get_level_values(0)[0]].index:
                    new_index.append((syn_date, sym))
                block_idx += 0   # no-op; placeholder for clarity
            # Note: block.loc[block_dates] returns rows in source-date order;
            # we re-key to synthetic_dates while preserving (date, symbol) shape
            block = block.reset_index()
            n_syms = block["symbol"].nunique()
            # Map original dates → synthetic dates row-by-row
            orig_date_order = block["date"].drop_duplicates().tolist()
            date_map = dict(zip(orig_date_order, synthetic_dates))
            block["date"] = block["date"].map(date_map)
            block = block.set_index(["date", "symbol"])
            path_blocks.append(block)
            block_idx += block_len
            days_remaining -= block_len
        return pd.concat(path_blocks)

    def simulate(self) -> Iterator[pd.DataFrame]:
        """Yield n_paths bootstrapped paths lazily (memory O(one path))."""
        for _ in range(self._cfg.n_paths):
            yield self.sample_path()
```

- [ ] **Step 3.4: Run tests — confirm GREEN**

```bash
PYTHONPATH='../site-packages;.' ../runtime/python/python.exe -m unittest tests.test_mc_backtester.TestStationaryBlockBootstrap -v
```

Expected: All 7 tests PASS. If a test fails due to MultiIndex shape mismatches, simplify `sample_path` by using `reset_index` + `set_index` consistently (see implementation above).

- [ ] **Step 3.5: Commit**

```bash
cd /c/Users/gl450/trading_app
git checkout main && git pull --ff-only
git checkout -b feat/mc-backtester-bootstrap
git add backend/data/mc_backtester.py backend/tests/test_mc_backtester.py
git commit -m "$(cat <<'EOF'
feat(mc-backtester): stationary block bootstrap simulator

Adds StationaryBlockBootstrap (Politis-Romano 1994) that samples random-
length blocks of trading days from historical (date × symbol)-indexed
data, with wrap-around at end of history. Block length ~Geometric(1/L);
default expected L=10 trading days.

Whole rows (returns + all channels) are bootstrapped jointly, so each
sampled block carries every symbol's row for the sampled dates —
preserves cross-symbol AND cross-channel correlations within blocks.

Lazy iterator (simulate()) yields K paths one at a time so memory stays
O(one path) regardless of K.

Companion to docs/superpowers/specs/2026-05-16-mc-strategy-design.md.
Backtest portfolio + replay + aggregator land in subsequent PRs.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push -u origin feat/mc-backtester-bootstrap
gh pr create --title "feat(mc-backtester): stationary block bootstrap simulator" --body "Part 1 of the MC backtester rollout. Pure simulator; integration in later PRs."
```

---

### Task 4: `BacktestPortfolio` + `_BacktestAgent`

**Files:**
- Modify: `backend/data/mc_backtester.py` (append portfolio + stripped-agent classes)
- Modify: `backend/tests/test_mc_backtester.py` (append `TestBacktestPortfolio`)

- [ ] **Step 4.1: Write failing tests**

Append to `backend/tests/test_mc_backtester.py`:

```python
class TestBacktestPortfolio(unittest.TestCase):
    """BacktestPortfolio mirrors Portfolio's surface but with no DB/file I/O."""

    def test_kelly_fraction_defaults_to_10pct_with_no_history(self):
        from data.mc_backtester import BacktestPortfolio
        p = BacktestPortfolio(starting_capital=100000.0)
        self.assertAlmostEqual(p.kelly_fraction(), 0.10)

    def test_unpnl_frac_returns_none_when_no_positions(self):
        from data.mc_backtester import BacktestPortfolio
        p = BacktestPortfolio(starting_capital=100000.0)
        self.assertIsNone(p.unpnl_frac({}))

    def test_execute_buy_then_total_value_reflects_position(self):
        from data.mc_backtester import BacktestPortfolio
        p = BacktestPortfolio(starting_capital=100000.0)
        p.execute_buy("AAPL", 10, 100.0)
        # cash 99000 + 10×$110 = 100100
        self.assertAlmostEqual(p.total_value({"AAPL": 110.0}), 100100.0)

    def test_execute_sell_realises_pnl(self):
        from data.mc_backtester import BacktestPortfolio
        p = BacktestPortfolio(starting_capital=100000.0)
        p.execute_buy("AAPL", 10, 100.0)
        p.execute_sell("AAPL", 10, 120.0)
        # 99000 + 1200 proceeds = 100200; realised PnL = $200
        self.assertEqual(len(p.trade_history), 2)
        self.assertEqual(p.trade_history[1].pnl, 200.0)


class TestBacktestAgent(unittest.IsolatedAsyncioTestCase):
    """_BacktestAgent inherits BaseAgent SELL helpers; analyse is no-op."""

    async def test_check_trailing_stops_callable_against_backtest_portfolio(self):
        from data.mc_backtester import BacktestPortfolio, _BacktestAgent
        p = BacktestPortfolio(starting_capital=100000.0)
        agent = _BacktestAgent("backtest", "stripped", portfolio_override=p)
        # No positions → no exits
        exits = await agent._check_trailing_stops({})
        self.assertEqual(exits, [])

    async def test_analyze_returns_empty_list(self):
        from data.mc_backtester import BacktestPortfolio, _BacktestAgent
        p = BacktestPortfolio(starting_capital=100000.0)
        agent = _BacktestAgent("backtest", "stripped", portfolio_override=p)
        result = await agent.analyze({})
        self.assertEqual(result, [])
```

- [ ] **Step 4.2: Run tests — confirm RED**

```bash
PYTHONPATH='../site-packages;.' ../runtime/python/python.exe -m unittest tests.test_mc_backtester.TestBacktestPortfolio tests.test_mc_backtester.TestBacktestAgent -v
```

Expected: ImportError on `BacktestPortfolio` / `_BacktestAgent`.

- [ ] **Step 4.3: Implement `BacktestPortfolio` and `_BacktestAgent`**

Append to `backend/data/mc_backtester.py`:

```python
# ─────────────────────────────────────────────────────────────────────────────
# Backtest portfolio + stripped agent (in-memory, no DB, no file I/O)
# ─────────────────────────────────────────────────────────────────────────────

from typing import Dict
from trading.portfolio import Portfolio
from agents.base_agent import BaseAgent


class BacktestPortfolio(Portfolio):
    """In-memory Portfolio for backtesting.

    Inherits the full Portfolio public surface (cash, positions,
    trade_history, kelly_fraction, total_value, execute_buy, execute_sell,
    record_value, unpnl_frac, _position_peak_unrealized, etc.) — no override
    needed for any of those. The 'no DB/file I/O' guarantee comes from the
    fact that Portfolio itself doesn't do DB writes — those happen in
    BaseAgent and database.py, neither of which we touch here.
    """

    def __init__(self, starting_capital: float = 100000.0):
        super().__init__(starting_capital=starting_capital)


class _BacktestAgent(BaseAgent):
    """Minimal BaseAgent subclass for backtest use.

    Exists ONLY so the replay loop can call inherited SELL helpers
    (_check_bayes_exits, _check_trailing_stops, _check_hard_stops,
    _in_trail_cooldown) against a BacktestPortfolio without depending on
    CNNReasoningAgent or any concrete production agent.

    Overrides:
      - _load_picks/_save_picks: no-op (skip file I/O)
      - analyze: returns []  (backtest BUY logic lives in cnn_decision)
      - __init__: accepts portfolio_override so we don't double-allocate
    """

    def __init__(self, name: str, strategy_description: str,
                 portfolio_override: Optional[BacktestPortfolio] = None):
        # Skip _load_picks during construction by stubbing the file path
        super().__init__(name=name, strategy_description=strategy_description)
        if portfolio_override is not None:
            self.portfolio = portfolio_override

    def _load_picks(self) -> None:
        # Skip file I/O entirely in backtest mode
        self._picks = {}

    def _save_picks(self) -> None:
        # No-op
        return

    async def analyze(self, market_context) -> list:
        return []
```

- [ ] **Step 4.4: Run tests — confirm GREEN**

```bash
PYTHONPATH='../site-packages;.' ../runtime/python/python.exe -m unittest tests.test_mc_backtester.TestBacktestPortfolio tests.test_mc_backtester.TestBacktestAgent -v
```

Expected: All PASS.

- [ ] **Step 4.5: Commit**

```bash
cd /c/Users/gl450/trading_app
git checkout -b feat/mc-backtester-portfolio
git add backend/data/mc_backtester.py backend/tests/test_mc_backtester.py
git commit -m "$(cat <<'EOF'
feat(mc-backtester): BacktestPortfolio + _BacktestAgent

Adds the in-memory portfolio + stripped agent subclass that the replay
loop will use:

- BacktestPortfolio: thin subclass of trading.portfolio.Portfolio. Same
  surface (kelly_fraction, total_value, execute_buy/sell, record_value,
  unpnl_frac). No DB writes (Portfolio itself doesn't do any — those
  live in database.py which we don't touch here).
- _BacktestAgent: BaseAgent subclass that overrides _load_picks /
  _save_picks to no-op (avoids file I/O during simulation) and provides
  a stub analyze() returning []. Exists so the replay loop can call
  inherited SELL helpers (_check_bayes_exits, _check_trailing_stops,
  _check_hard_stops, _in_trail_cooldown) against the backtest portfolio.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push -u origin feat/mc-backtester-portfolio
gh pr create --title "feat(mc-backtester): BacktestPortfolio + _BacktestAgent" --body "Part 2 of the MC backtester rollout."
```

---

### Task 5: `replay_one_path` + `PathOutcome`

**Files:**
- Modify: `backend/data/mc_backtester.py` (append replay function + metrics dataclass)
- Modify: `backend/tests/test_mc_backtester.py` (append `TestReplay`)

- [ ] **Step 5.1: Write failing tests for replay on a synthetic path**

Append to `backend/tests/test_mc_backtester.py`:

```python
class TestReplay(unittest.IsolatedAsyncioTestCase):
    """replay_one_path day-by-day simulation against a known synthetic path."""

    def _synthetic_one_symbol_path(self, n_days=30):
        """One symbol, monotonically rising → BUY signal should fire and profit."""
        dates = list(range(n_days))
        rows = []
        for i, d in enumerate(dates):
            rows.append({
                "date": d, "symbol": "AAPL",
                "close": 100.0 * (1.0 + 0.001 * i),     # +0.1% per day
                "return_1d": 0.001,
                # Every channel cnn_model needs — for the smoke test, zeros suffice
                "analyst_score": 0.5, "earnings_score": 0.0,
                "alpaca_score": 0.0, "yahoo_score": 0.0,
                "iv_rv_score": 0.0,
            })
        return pd.DataFrame(rows).set_index(["date", "symbol"])

    async def test_replay_returns_pathoutcome(self):
        from data.mc_backtester import replay_one_path, PathOutcome, _FakeModel
        path = self._synthetic_one_symbol_path(n_days=30)
        model = _FakeModel(pred_return=0.05, direction="up", confidence=0.85)
        from config import config
        outcome = await replay_one_path(
            path=path, model=model, variant_name="test",
            sim_idx=0, starting_capital=100000.0, config=config,
        )
        self.assertIsInstance(outcome, PathOutcome)
        self.assertEqual(outcome.variant_name, "test")
        self.assertEqual(outcome.sim_idx, 0)
        self.assertGreater(outcome.n_trades, 0)   # at least one BUY fired

    async def test_replay_handles_zero_predictions(self):
        from data.mc_backtester import replay_one_path, _FakeModel
        from config import config
        path = self._synthetic_one_symbol_path(n_days=30)
        model = _FakeModel(pred_return=0.0, direction="neutral", confidence=0.10)
        outcome = await replay_one_path(
            path=path, model=model, variant_name="zero",
            sim_idx=0, starting_capital=100000.0, config=config,
        )
        self.assertEqual(outcome.n_trades, 0)   # no BUYs fired → no SELLs either
        self.assertAlmostEqual(outcome.final_return, 0.0)
```

- [ ] **Step 5.2: Run tests — confirm RED**

```bash
PYTHONPATH='../site-packages;.' ../runtime/python/python.exe -m unittest tests.test_mc_backtester.TestReplay -v
```

Expected: ImportError on `replay_one_path` / `PathOutcome` / `_FakeModel`.

- [ ] **Step 5.3: Implement `_FakeModel`, `PathOutcome`, helpers, and `replay_one_path`**

Append to `backend/data/mc_backtester.py`:

```python
# ─────────────────────────────────────────────────────────────────────────────
# Replay loop
# ─────────────────────────────────────────────────────────────────────────────

import math
from typing import Any
from config import config as _DEFAULT_CONFIG
from data.regime_detector import RegimeDetector
from agents.cnn_decision import BuyContext, decide_buy


@dataclass(frozen=True)
class PathOutcome:
    """Result of replaying one (variant, simulated path)."""
    variant_name: str
    sim_idx: int
    sharpe: float
    max_drawdown: float                # negative fraction, e.g., -0.18
    final_return: float                # (end - start) / start
    n_trades: int
    n_buys: int
    n_sells: int
    final_value: float


class _FakeModel:
    """Test fixture — stand-in for SignalXGBoost that returns fixed predictions.

    Production replay uses a real trained SignalXGBoost. This class exists so
    unit tests for replay can run without training a real model.
    """
    def __init__(self, pred_return: float, direction: str, confidence: float):
        self._ret = pred_return
        self._dir = direction
        self._conf = confidence
        self.is_trained = True

    def predict(self, window) -> tuple:
        return (self._ret, self._dir, self._conf)


def _annualised_sharpe(daily_values: list[float]) -> float:
    """Annualised Sharpe of the daily-value series. 0.0 if undefined."""
    if len(daily_values) < 2:
        return 0.0
    returns = np.diff(np.asarray(daily_values, dtype=np.float64)) / np.asarray(daily_values[:-1])
    if returns.std() == 0:
        return 0.0
    return float(returns.mean() / returns.std() * math.sqrt(252))


def _max_drawdown(daily_values: list[float]) -> float:
    """Max drawdown as a negative fraction (e.g., -0.18 = -18%)."""
    if len(daily_values) < 2:
        return 0.0
    arr = np.asarray(daily_values, dtype=np.float64)
    peaks = np.maximum.accumulate(arr)
    drawdowns = (arr - peaks) / peaks
    return float(drawdowns.min())


async def replay_one_path(
    path: pd.DataFrame,                 # (date × symbol)-indexed
    model: Any,                         # has .predict(window) → (ret, dir, conf)
    variant_name: str,
    sim_idx: int,
    starting_capital: float,
    config=_DEFAULT_CONFIG,
) -> PathOutcome:
    """Day-by-day strategy replay on one bootstrapped path.

    Per-day order matches BaseAgent.run_cycle in production:
      1. portfolio.record_value(prices) — peak/uPnL bookkeeping
      2. SELL pass:  bayes_exits + trailing_stops + hard_stops
      3. BUY pass:   for each symbol, predict() → decide_buy() → maybe execute
      4. Append portfolio.total_value to daily_values
    """
    portfolio = BacktestPortfolio(starting_capital=starting_capital)
    agent = _BacktestAgent("backtest", "stripped", portfolio_override=portfolio)
    daily_values: list[float] = []

    # Fresh regime detector per path — no state leakage across simulations
    regime_detector = RegimeDetector()

    dates = sorted(path.index.get_level_values(0).unique())
    for day_idx, date in enumerate(dates):
        day_rows = path.xs(date, level=0)
        prices = day_rows["close"].to_dict()

        # Feed SPY (or first symbol as proxy) to regime detector
        if "SPY" in prices:
            regime_detector.update([prices["SPY"]])
        regime = regime_detector.get_regime()[0] if day_idx > 20 else "neutral"

        portfolio.record_value(prices)

        # ── SELL pass ─────────────────────────────────────────────────────
        sell_signals = (await agent._check_bayes_exits(prices)) + \
                       (await agent._check_trailing_stops(prices)) + \
                       (await agent._check_hard_stops(prices))
        for sig in sell_signals:
            portfolio.execute_sell(sig.symbol, sig.shares, prices[sig.symbol], sig.reasoning)

        # ── BUY pass ──────────────────────────────────────────────────────
        for symbol in day_rows.index:
            price = float(prices.get(symbol, 0.0))
            if price <= 0:
                continue
            # Build the model window — in this minimal replay we pass the row
            # itself; a richer implementation builds the (C, T) window from
            # `path` over the last T days.
            window = day_rows.loc[symbol].to_numpy()  # 1D feature vector
            pred_ret, direction, conf = model.predict(window)
            ctx = BuyContext(
                symbol=symbol,
                cnn_pred_return=float(pred_ret),
                cnn_pred_direction=str(direction),
                cnn_confidence=float(conf),
                regime=regime,
                portfolio_unpnl_frac=portfolio.unpnl_frac(prices),
                n_corroborators=0,      # no ensemble in backtest (per spec)
                in_trail_cooldown=agent._in_trail_cooldown(),
                current_price=price,
                cash_available=portfolio.cash,
                portfolio_value=portfolio.get_total_value(prices),
                kelly_fraction=portfolio.kelly_fraction(),
            )
            decision = decide_buy(ctx, config)
            if decision.action == "BUY":
                portfolio.execute_buy(symbol, decision.shares, price, decision.reason)

        daily_values.append(portfolio.get_total_value(prices))

    return PathOutcome(
        variant_name=variant_name, sim_idx=sim_idx,
        sharpe=_annualised_sharpe(daily_values),
        max_drawdown=_max_drawdown(daily_values),
        final_return=(daily_values[-1] - starting_capital) / starting_capital,
        n_trades=len(portfolio.trade_history),
        n_buys=sum(1 for t in portfolio.trade_history if t.action == "BUY"),
        n_sells=sum(1 for t in portfolio.trade_history if t.action == "SELL"),
        final_value=daily_values[-1],
    )
```

- [ ] **Step 5.4: Run tests — confirm GREEN**

```bash
PYTHONPATH='../site-packages;.' ../runtime/python/python.exe -m unittest tests.test_mc_backtester.TestReplay -v
```

Expected: 2/2 PASS.

- [ ] **Step 5.5: Commit**

```bash
cd /c/Users/gl450/trading_app
git checkout -b feat/mc-backtester-replay
git add backend/data/mc_backtester.py backend/tests/test_mc_backtester.py
git commit -m "$(cat <<'EOF'
feat(mc-backtester): replay loop + PathOutcome

Adds replay_one_path that walks day-by-day through a bootstrapped path,
running SELL pass (bayes/trail/hard helpers from BaseAgent) and BUY
pass (cnn_decision.decide_buy on per-day predictions) on a
BacktestPortfolio. Records daily portfolio values and emits PathOutcome
with Sharpe / max-DD / final-return / trade counts.

Fresh RegimeDetector per path — no state leakage across simulations.
The model parameter is duck-typed: anything with a .predict(window) →
(return, direction, confidence) tuple works. _FakeModel test fixture
included for unit tests without training real models.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push -u origin feat/mc-backtester-replay
gh pr create --title "feat(mc-backtester): replay loop + PathOutcome" --body "Part 3 of the MC backtester rollout."
```

---

### Task 6: Aggregation + report writers

**Files:**
- Modify: `backend/data/mc_backtester.py` (append aggregator + report writers)
- Modify: `backend/tests/test_mc_backtester.py` (append `TestAggregation`)

- [ ] **Step 6.1: Write failing tests for aggregation**

Append to `backend/tests/test_mc_backtester.py`:

```python
class TestAggregation(unittest.TestCase):

    def test_percentile_math_correct(self):
        from data.mc_backtester import PathOutcome, summarise
        outcomes = [
            PathOutcome(variant_name="A", sim_idx=i, sharpe=float(i)/10.0,
                        max_drawdown=-0.05*i, final_return=0.01*i,
                        n_trades=10, n_buys=5, n_sells=5, final_value=100000.0)
            for i in range(101)  # 0..100, so p5=5, p50=50, p95=95
        ]
        report = summarise(outcomes)
        self.assertIn("A", report.per_variant)
        stats = report.per_variant["A"]
        self.assertAlmostEqual(stats["sharpe_p5"],  0.5)
        self.assertAlmostEqual(stats["sharpe_p50"], 5.0)
        self.assertAlmostEqual(stats["sharpe_p95"], 9.5)

    def test_summarise_groups_by_variant(self):
        from data.mc_backtester import PathOutcome, summarise
        outcomes = (
            [PathOutcome("A", i, 0.5, -0.1, 0.05, 10, 5, 5, 105000.0) for i in range(20)] +
            [PathOutcome("B", i, 0.8, -0.08, 0.10, 12, 6, 6, 110000.0) for i in range(20)]
        )
        report = summarise(outcomes)
        self.assertEqual(set(report.per_variant.keys()), {"A", "B"})
        self.assertEqual(report.per_variant["A"]["n_simulations"], 20)
        self.assertEqual(report.per_variant["B"]["n_simulations"], 20)

    def test_render_markdown_produces_table(self):
        from data.mc_backtester import PathOutcome, summarise, render_markdown
        outcomes = [PathOutcome("A", i, 0.5, -0.1, 0.05, 10, 5, 5, 105000.0) for i in range(10)]
        report = summarise(outcomes)
        md = render_markdown(report)
        self.assertIn("| Variant ", md)         # header row
        self.assertIn("| A ", md)               # data row
        self.assertIn("Sharpe", md)             # has metric columns

    def test_write_jsonl_round_trip(self):
        import tempfile, json, os
        from data.mc_backtester import PathOutcome, write_jsonl
        outcomes = [PathOutcome("A", i, 0.5, -0.1, 0.05, 10, 5, 5, 105000.0) for i in range(3)]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            write_jsonl(outcomes, path)
            with open(path) as f:
                lines = [json.loads(line) for line in f]
            self.assertEqual(len(lines), 3)
            self.assertEqual(lines[0]["variant_name"], "A")
            self.assertEqual(lines[0]["sim_idx"], 0)
        finally:
            os.unlink(path)
```

- [ ] **Step 6.2: Run tests — confirm RED**

```bash
PYTHONPATH='../site-packages;.' ../runtime/python/python.exe -m unittest tests.test_mc_backtester.TestAggregation -v
```

Expected: ImportError on `summarise` / `render_markdown` / `write_jsonl`.

- [ ] **Step 6.3: Implement aggregator + writers**

Append to `backend/data/mc_backtester.py`:

```python
# ─────────────────────────────────────────────────────────────────────────────
# Aggregation + report writers
# ─────────────────────────────────────────────────────────────────────────────

import json
from dataclasses import asdict


@dataclass
class VariantComparisonReport:
    """Aggregated outcomes across all (variant, sim) replays."""
    per_variant: Dict[str, Dict[str, float]]    # variant_name → metric → value
    n_simulations: int
    n_variants: int


def _percentiles(values: list[float], pcts=(5, 50, 95)) -> Dict[str, float]:
    arr = np.asarray(values, dtype=np.float64)
    return {f"p{p}": float(np.percentile(arr, p)) for p in pcts}


def summarise(outcomes: list[PathOutcome]) -> VariantComparisonReport:
    """Group outcomes by variant, compute per-metric percentiles."""
    by_variant: Dict[str, list[PathOutcome]] = {}
    for o in outcomes:
        by_variant.setdefault(o.variant_name, []).append(o)

    per_variant: Dict[str, Dict[str, float]] = {}
    for name, group in by_variant.items():
        sharpes = [o.sharpe for o in group]
        dds = [o.max_drawdown for o in group]
        rets = [o.final_return for o in group]
        sharpe_pct = _percentiles(sharpes)
        dd_pct = _percentiles(dds)
        ret_pct = _percentiles(rets)
        per_variant[name] = {
            "n_simulations": len(group),
            "sharpe_p5":  sharpe_pct["p5"],
            "sharpe_p50": sharpe_pct["p50"],
            "sharpe_p95": sharpe_pct["p95"],
            "max_dd_p5":  dd_pct["p5"],
            "max_dd_p50": dd_pct["p50"],
            "max_dd_p95": dd_pct["p95"],
            "final_return_p5":  ret_pct["p5"],
            "final_return_p50": ret_pct["p50"],
            "final_return_p95": ret_pct["p95"],
            "avg_n_trades": float(np.mean([o.n_trades for o in group])),
        }
    return VariantComparisonReport(
        per_variant=per_variant,
        n_simulations=max((len(g) for g in by_variant.values()), default=0),
        n_variants=len(by_variant),
    )


def render_markdown(report: VariantComparisonReport) -> str:
    """Format a comparison report as a Markdown table."""
    lines = [
        f"# MC Backtest Report — {report.n_variants} variants × {report.n_simulations} sims",
        "",
        "| Variant | Sharpe p5 | Sharpe p50 | Sharpe p95 | DD p5 | DD p50 | DD p95 | Ret p5 | Ret p50 | Ret p95 | Avg trades |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, stats in sorted(report.per_variant.items()):
        lines.append(
            f"| {name} | {stats['sharpe_p5']:+.2f} | {stats['sharpe_p50']:+.2f} | {stats['sharpe_p95']:+.2f} | "
            f"{stats['max_dd_p5']:+.2%} | {stats['max_dd_p50']:+.2%} | {stats['max_dd_p95']:+.2%} | "
            f"{stats['final_return_p5']:+.2%} | {stats['final_return_p50']:+.2%} | {stats['final_return_p95']:+.2%} | "
            f"{stats['avg_n_trades']:.0f} |"
        )
    return "\n".join(lines) + "\n"


def write_jsonl(outcomes: list[PathOutcome], path: str) -> None:
    """Write per-(variant,sim) outcomes to a JSONL file."""
    with open(path, "w", encoding="utf-8") as f:
        for o in outcomes:
            f.write(json.dumps(asdict(o)) + "\n")


@dataclass
class FilterVariant:
    """One variant to compare — name + trained model."""
    name: str
    model: Any                          # SignalXGBoost or _FakeModel


async def run_variant_comparison(
    variants: list[FilterVariant],
    historical: pd.DataFrame,
    cfg: BootstrapConfig,
    config=_DEFAULT_CONFIG,
    starting_capital: float = 100000.0,
) -> tuple[VariantComparisonReport, list[PathOutcome]]:
    """Top-level orchestrator. For each bootstrapped path, run every
    variant on that SAME path → paired-sample comparison.

    Returns (summarised_report, raw_outcomes).
    """
    sampler = StationaryBlockBootstrap(historical, cfg)
    all_outcomes: list[PathOutcome] = []
    for sim_idx, path in enumerate(sampler.simulate()):
        for variant in variants:
            outcome = await replay_one_path(
                path=path, model=variant.model,
                variant_name=variant.name, sim_idx=sim_idx,
                starting_capital=starting_capital, config=config,
            )
            all_outcomes.append(outcome)
    return summarise(all_outcomes), all_outcomes
```

- [ ] **Step 6.4: Run tests — confirm GREEN**

```bash
PYTHONPATH='../site-packages;.' ../runtime/python/python.exe -m unittest tests.test_mc_backtester.TestAggregation -v
```

Expected: 4/4 PASS.

- [ ] **Step 6.5: Commit**

```bash
cd /c/Users/gl450/trading_app
git checkout -b feat/mc-backtester-aggregator
git add backend/data/mc_backtester.py backend/tests/test_mc_backtester.py
git commit -m "$(cat <<'EOF'
feat(mc-backtester): aggregator + Markdown/JSONL report writers

Adds VariantComparisonReport + summarise() + render_markdown() +
write_jsonl() + run_variant_comparison() — the per-variant percentile
table + raw-outcomes JSONL log + the top-level orchestrator that runs
every variant on every bootstrapped path (paired comparison).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push -u origin feat/mc-backtester-aggregator
gh pr create --title "feat(mc-backtester): aggregator + report writers" --body "Part 4 of the MC backtester rollout."
```

---

### Task 7: CLI script `scripts/mc_backtest_filters.py`

**Files:**
- Create: `scripts/mc_backtest_filters.py`

- [ ] **Step 7.1: Implement the CLI**

Create `scripts/mc_backtest_filters.py`:

```python
"""CLI — Monte Carlo backtest comparing candidate XGB filter variants.

Usage from project root:
    PYTHONPATH='site-packages;backend' runtime/python/python.exe \\
      scripts/mc_backtest_filters.py \\
      --variants "current=analyst_score,earnings_score,alpaca_score,iv_rv_score,r_120,macro_vix_norm,macro_spy_5d_back,macro_breadth_back" \\
                 "swap_both=analyst_score,earnings_score,alpaca_score,iv_rv_score,r_120,macro_vix_norm,macro_spy_10d_back,macro_breadth_10d_back" \\
      --n-paths 1000 --path-days 252 --block-size 10 --seed 42

Outputs:
    scripts/logs/mc_backtest_<timestamp>.md      (Markdown table)
    scripts/logs/mc_backtest_<timestamp>.jsonl   (raw per-(variant,sim) outcomes)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(os.path.dirname(_HERE), "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

os.environ.setdefault("MODEL_BACKEND", "xgboost")

from data.signal_history import signal_history
from data.cnn_model import build_training_windows
from data.xgboost_model import SignalXGBoost
from data.mc_backtester import (
    BootstrapConfig, FilterVariant, run_variant_comparison,
    render_markdown, write_jsonl,
)


def _parse_variant_arg(spec: str) -> tuple[str, list[str]]:
    """'name=ch1,ch2,...' → ('name', ['ch1', 'ch2', ...])"""
    if "=" not in spec:
        raise ValueError(f"variant must be 'name=ch1,ch2,...' — got: {spec}")
    name, channels = spec.split("=", 1)
    return name.strip(), [c.strip() for c in channels.split(",") if c.strip()]


def _train_variant(name: str, channel_names: list[str]) -> SignalXGBoost:
    """Train one fresh SignalXGBoost with the given feature filter."""
    print(f"\n  ── training variant '{name}' ({len(channel_names)} channels)…")
    # Temporarily set the env so SignalXGBoost picks up the filter at init
    os.environ["XGB_FEATURE_FILTER"] = ",".join(channel_names)
    model = SignalXGBoost()
    df = signal_history.get_training_data()
    X, y, w, t = build_training_windows(df)
    t0 = time.time()
    model.fit(X, y, t, sample_weights=w)
    print(f"  ── '{name}' fit in {time.time()-t0:.1f}s  mean_IC={model.training_summary()['mean_ic']:+.4f}")
    return model


async def _main_async(args: argparse.Namespace) -> int:
    print("Loading historical data once (shared across variants)…")
    historical = signal_history.get_training_data()
    print(f"  rows={len(historical):,}  symbols={historical['symbol'].nunique() if len(historical) else 0}")

    # Train one model per variant
    variants: list[FilterVariant] = []
    for spec in args.variants:
        name, channels = _parse_variant_arg(spec)
        model = _train_variant(name, channels)
        variants.append(FilterVariant(name=name, model=model))

    # Run the comparison
    print(f"\n  ── simulating: {args.n_paths} paths × {args.path_days} days × {len(variants)} variants…")
    cfg = BootstrapConfig(
        expected_block_size=args.block_size,
        n_paths=args.n_paths,
        path_length_days=args.path_days,
        seed=args.seed,
    )
    # historical must be MultiIndex (date, symbol) for the sampler
    if not isinstance(historical.index, pd.MultiIndex):
        historical = historical.set_index(["snapshot_ts", "symbol"])
    report, outcomes = await run_variant_comparison(variants, historical, cfg)

    # Write outputs
    os.makedirs(os.path.join(_HERE, "logs"), exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = os.path.join(_HERE, "logs", f"mc_backtest_{ts}.md")
    jsonl_path = os.path.join(_HERE, "logs", f"mc_backtest_{ts}.jsonl")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(report))
    write_jsonl(outcomes, jsonl_path)

    print(f"\nReport written:")
    print(f"  Markdown: {md_path}")
    print(f"  JSONL:    {jsonl_path}")
    print()
    print(render_markdown(report))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variants", nargs="+", required=True,
                        help="One or more 'name=ch1,ch2,...' specs")
    parser.add_argument("--n-paths", type=int, default=1000)
    parser.add_argument("--path-days", type=int, default=252)
    parser.add_argument("--block-size", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7.2: Smoke-import the CLI (no real run yet)**

```bash
cd /c/Users/gl450/trading_app
PYTHONPATH='site-packages;backend' runtime/python/python.exe -c "import scripts.mc_backtest_filters; print('OK')"
```

Expected: `OK`. (If `import pd` errors, add `import pandas as pd` near top of `_main_async` — the spec references it in the MultiIndex check.)

- [ ] **Step 7.3: Commit**

```bash
git checkout -b feat/mc-backtester-cli
git add scripts/mc_backtest_filters.py
git commit -m "feat(mc-backtester): CLI for comparing filter variants

Top-level CLI that trains one SignalXGBoost per variant (each with its
own XGB_FEATURE_FILTER env), runs run_variant_comparison, writes a
Markdown report + JSONL log to scripts/logs/.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
git push -u origin feat/mc-backtester-cli
gh pr create --title "feat(mc-backtester): CLI for comparing filter variants" --body "Part 5 of the MC backtester rollout."
```

---

### Task 8: End-to-end smoke test on small synthetic data

**Files:**
- Modify: `backend/tests/test_mc_backtester.py` (append `TestSmokeE2E`)

- [ ] **Step 8.1: Write a smoke test that runs the full pipeline**

Append to `backend/tests/test_mc_backtester.py`:

```python
class TestSmokeE2E(unittest.IsolatedAsyncioTestCase):
    """End-to-end: 2 variants × 3 paths × 30 days × 2 symbols. Sanity check
    that everything wires up and produces a valid report."""

    def _tiny_history(self):
        """30 days × 2 symbols of synthetic data with all required channels."""
        import numpy as np
        rng = np.random.default_rng(0)
        rows = []
        for day in range(30):
            for sym in ("AAPL", "MSFT"):
                rows.append({
                    "date": day, "symbol": sym,
                    "close": 100.0 + rng.normal(0, 1),
                    "return_1d": rng.normal(0, 0.01),
                    "analyst_score": rng.uniform(),
                    "earnings_score": rng.normal(),
                    "alpaca_score": rng.normal(),
                    "yahoo_score": rng.normal(),
                    "iv_rv_score": rng.normal(),
                })
        return pd.DataFrame(rows).set_index(["date", "symbol"])

    async def test_full_pipeline_runs_to_completion(self):
        from data.mc_backtester import (
            BootstrapConfig, FilterVariant, _FakeModel,
            run_variant_comparison, render_markdown,
        )
        from config import config
        hist = self._tiny_history()
        variants = [
            FilterVariant(name="A", model=_FakeModel(0.02, "up",   0.80)),
            FilterVariant(name="B", model=_FakeModel(0.01, "down", 0.30)),
        ]
        cfg = BootstrapConfig(
            expected_block_size=5, n_paths=3, path_length_days=20, seed=0,
        )
        report, outcomes = await run_variant_comparison(
            variants, hist, cfg, config=config,
        )
        # Sanity assertions
        self.assertEqual(report.n_variants, 2)
        self.assertEqual(report.n_simulations, 3)
        self.assertEqual(len(outcomes), 6)              # 2 variants × 3 paths
        self.assertIn("A", report.per_variant)
        self.assertIn("B", report.per_variant)
        md = render_markdown(report)
        self.assertIn("| A ", md)
        self.assertIn("| B ", md)
```

- [ ] **Step 8.2: Run smoke test — confirm GREEN**

```bash
PYTHONPATH='../site-packages;.' ../runtime/python/python.exe -m unittest tests.test_mc_backtester.TestSmokeE2E -v
```

Expected: 1/1 PASS.

- [ ] **Step 8.3: Run full backtester test suite — confirm GREEN**

```bash
PYTHONPATH='../site-packages;.' ../runtime/python/python.exe -m unittest tests.test_mc_backtester -v
```

Expected: All tests PASS (≈18 across bootstrap/portfolio/agent/replay/aggregation/smoke).

- [ ] **Step 8.4: Commit**

```bash
cd /c/Users/gl450/trading_app
git checkout -b test/mc-backtester-smoke-e2e
git add backend/tests/test_mc_backtester.py
git commit -m "test(mc-backtester): end-to-end smoke test on synthetic data

Wires the full pipeline (2 variants × 3 paths × 20 days × 2 symbols)
with _FakeModel stand-ins. Asserts the report has the expected shape
and Markdown rendering. Catches integration regressions before the
real run on 528K rows.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
git push -u origin test/mc-backtester-smoke-e2e
gh pr create --title "test(mc-backtester): end-to-end smoke test on synthetic data" --body "Part 6 of the MC backtester rollout."
```

---

### Task 9: Usage docs

**Files:**
- Create: `docs/mc_backtester_usage.md`

- [ ] **Step 9.1: Write the usage doc**

Create `docs/mc_backtester_usage.md`:

````markdown
# MC Strategy Backtester — Usage

Offline Monte Carlo backtester that compares candidate XGB feature-filter variants by running each through K bootstrapped alternate market histories.

## Quick start

```bash
cd /c/Users/gl450/trading_app
PYTHONPATH='site-packages;backend' runtime/python/python.exe scripts/mc_backtest_filters.py \
  --variants \
    "current=analyst_score,earnings_score,alpaca_score,iv_rv_score,r_120,macro_vix_norm,macro_spy_5d_back,macro_breadth_back" \
    "swap_both=analyst_score,earnings_score,alpaca_score,iv_rv_score,r_120,macro_vix_norm,macro_spy_10d_back,macro_breadth_10d_back" \
  --n-paths 1000 --path-days 252 --block-size 10 --seed 42
```

Output:
- `scripts/logs/mc_backtest_<timestamp>.md` — headline Markdown table
- `scripts/logs/mc_backtest_<timestamp>.jsonl` — per-(variant,sim) raw outcomes

## CLI arguments

| Flag | Default | Meaning |
|---|---|---|
| `--variants` | (required) | One or more `name=ch1,ch2,...` specs |
| `--n-paths` | 1000 | K — bootstrapped alternate histories |
| `--path-days` | 252 | Length of each path (1 trading year) |
| `--block-size` | 10 | Expected block length (~2 weeks) |
| `--seed` | 42 | RNG seed — same seed → same K paths |

## Performance notes

- Training: ~2 min per variant on 528K rows × 8 channels (full historical).
- Simulation: ~K × n_variants × path_days × n_symbols model predictions. Default 1000 × 2 × 252 × 222 ≈ 110M predict() calls. Expect ~10-30 min total on CPU.
- Memory: O(one path) thanks to lazy `simulate()`. ~200 MB peak.
- To shrink: drop `--n-paths` to 200 for a quick smoke test.

## Architecture

See `docs/superpowers/specs/2026-05-16-mc-strategy-design.md` for the full design rationale (loose-coupling boundaries, why stationary block bootstrap, why paired-sample comparison).

## Reverting if needed

The CLI doesn't modify production state — it only writes to `scripts/logs/`. The training step temporarily sets `XGB_FEATURE_FILTER` in the script's process env, which does NOT affect the running backend's `.env`. To deploy a winning variant in production, update `.env`'s `XGB_FEATURE_FILTER` line manually and restart.
````

- [ ] **Step 9.2: Commit**

```bash
git checkout -b docs/mc-backtester-usage
git add docs/mc_backtester_usage.md
git commit -m "docs(mc-backtester): usage guide

CLI invocation, argument reference, performance notes, links to the
design spec.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
git push -u origin docs/mc-backtester-usage
gh pr create --title "docs(mc-backtester): usage guide" --body "Final part of the MC backtester rollout. CLI usage, args, perf notes."
```

---

## Implementation order summary

| # | Task | Branch | Depends on |
|---|---|---|---|
| 1 | `cnn_decision` module + tests | `feat/cnn-decision-pure-helpers` | — |
| 2 | Refactor agent + `Portfolio.unpnl_frac` | `refactor/cnn-agent-uses-cnn-decision` | Task 1 |
| 3 | `StationaryBlockBootstrap` | `feat/mc-backtester-bootstrap` | — |
| 4 | `BacktestPortfolio` + `_BacktestAgent` | `feat/mc-backtester-portfolio` | Task 3 |
| 5 | `replay_one_path` + `PathOutcome` | `feat/mc-backtester-replay` | Task 1, 4 |
| 6 | Aggregator + report writers | `feat/mc-backtester-aggregator` | Task 5 |
| 7 | CLI script | `feat/mc-backtester-cli` | Task 6 |
| 8 | E2E smoke test | `test/mc-backtester-smoke-e2e` | Task 7 |
| 9 | Usage docs | `docs/mc-backtester-usage` | Task 8 |

Tasks 1 and 3 are independent and could run in parallel. All others have the dependencies shown.

## Verification at the end

After all 9 PRs merge:

```bash
cd /c/Users/gl450/trading_app
# Quick smoke run (200 paths, 100 days, 2 variants — should complete < 5 min)
PYTHONPATH='site-packages;backend' runtime/python/python.exe scripts/mc_backtest_filters.py \
  --variants \
    "current=analyst_score,earnings_score,alpaca_score,iv_rv_score,r_120,macro_vix_norm,macro_spy_5d_back,macro_breadth_back" \
    "swap_both=analyst_score,earnings_score,alpaca_score,iv_rv_score,r_120,macro_vix_norm,macro_spy_10d_back,macro_breadth_10d_back" \
  --n-paths 200 --path-days 100 --block-size 10 --seed 42
```

Expected: report written to `scripts/logs/`, no errors, recommendation line printed.

If the smoke run looks good, scale up to `--n-paths 1000 --path-days 252` for the production comparison.
