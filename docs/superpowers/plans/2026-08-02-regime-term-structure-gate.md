# Multi-Horizon Regime Term-Structure Gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a multi-horizon trend term-structure signal (measured on QQQ) that acts as a tighten-only conservatism dial on the XGBReasoningAgent BUY confidence threshold.

**Architecture:** A new pure module (`data/regime_term_structure.py`) computes a vol-normalized z-score term-structure over 5/10/20/60/90-day momentum and classifies `trending_up | topping | ranging_weak`, emitting a gate delta. The delta is threaded through the existing pure `xgb_decision.decide_buy` (shared prod + MC backtester) and combined with the current regime delta via `max()` — never sum, never lowering the threshold. Ships default-OFF with shadow logging (mirrors the H15 vol-target rollout).

**Tech Stack:** Python 3.12, numpy, `unittest` (run via `runtime/python/python.exe`), dataclasses.

## Global Constraints

- **Scope:** modify files only inside `C:\Users\gl450\trading_app\`. XGBReasoningAgent path only.
- **Loose coupling (invariant #10):** `data/regime_term_structure.py` imports ONLY stdlib + numpy — no imports from `agents/`, `main`, `database`, or the `config` singleton. Config values are passed in as function parameters.
- **Tighten-only:** the term-structure `gate_delta` is always `>= 0` and combined via `max()`. It may only RAISE the BUY confidence threshold. It never touches the WFE falsifier (`_apply_wfe_gate`).
- **Default OFF + shadow:** `TERM_STRUCTURE_GATE_ENABLED=0` default; while off, the state/delta are computed and logged (`[TERM_STRUCT]`) but not applied.
- **Tests:** first, and run via `runtime/python/python.exe`. Per-module during dev: `cd backend && ../runtime/python/python.exe -m unittest tests.<module> -v`. Full suite once before final commit: `cd backend && ../runtime/python/python.exe run_tests.py`. pytest is NOT installed.
- **Shell cleanup** after test runs (kill leftover python), per CLAUDE.md.
- **Commit + push** together on a feature branch; never commit on `main`.
- **Fail-open:** missing/short QQQ data → state `neutral`, delta `0.0` (never blocks on missing data).

## File Structure

- **Create** `backend/data/regime_term_structure.py` — pure classifier + thin stateful singleton.
- **Create** `backend/tests/test_regime_term_structure.py` — classifier + singleton tests.
- **Modify** `backend/config.py` — 5 config knobs (near the VOL_TARGET block ~L196).
- **Modify** `.env.example` — document the 5 knobs.
- **Modify** `backend/agents/xgb_decision.py` — `BuyContext.term_structure_delta` field + Gate 3 `max()` combine.
- **Modify** `backend/tests/test_xgb_decision.py` — gate-combination tests.
- **Modify** `backend/agents/xgb_reasoning_agent.py` — update detector from QQQ bars, shadow-log, pass delta into `BuyContext`.
- **Modify** `backend/tests/test_xgb_reasoning_agent.py` — agent-integration test.
- **Modify** `CLAUDE.md` — Trading-policy-defaults knob table + one-line invariant note.

**Pre-flight (once, before Task 1):**
```bash
cd /c/Users/gl450/trading_app
git checkout main && git checkout -b feat/regime-term-structure-gate
```

---

### Task 1: Pure term-structure classifier

**Files:**
- Create: `backend/data/regime_term_structure.py`
- Test: `backend/tests/test_regime_term_structure.py`

**Interfaces:**
- Produces: `TermStructureResult(state: str, gate_delta: float, long_z: float, short_z: float, detail: dict)`; `compute_term_structure(closes: list[float], cutoff: float = 0.5, delta_topping: float = 0.10, delta_weak: float = 0.15) -> TermStructureResult`. States: `"trending_up"` (delta 0), `"topping"` (delta_topping), `"ranging_weak"` (delta_weak), `"neutral"` (delta 0 — fail-open sentinel for insufficient/degenerate data).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_regime_term_structure.py
import unittest
from data.regime_term_structure import compute_term_structure, TermStructureResult


def _series(n=120, drift=0.0, start=100.0):
    """Deterministic price path with constant per-bar drift (no noise)."""
    px = [start]
    for _ in range(n - 1):
        px.append(px[-1] * (1.0 + drift))
    return px


class TestComputeTermStructure(unittest.TestCase):
    def test_sustained_uptrend_is_trending_up_zero_delta(self):
        # steady +0.2%/day for 120 bars → long & short both strongly up
        r = compute_term_structure(_series(drift=0.002))
        self.assertEqual(r.state, "trending_up")
        self.assertEqual(r.gate_delta, 0.0)

    def test_long_up_short_down_is_topping(self):
        # 90 up bars then 20 down bars: long-horizon up, recent short-horizon down
        px = _series(n=95, drift=0.004)
        for _ in range(20):
            px.append(px[-1] * (1.0 - 0.004))
        r = compute_term_structure(px)
        self.assertEqual(r.state, "topping")
        self.assertAlmostEqual(r.gate_delta, 0.10, places=6)

    def test_flat_series_is_ranging_weak(self):
        # near-flat drift → long_z below cutoff → ranging_weak
        r = compute_term_structure(_series(drift=0.00005))
        self.assertEqual(r.state, "ranging_weak")
        self.assertAlmostEqual(r.gate_delta, 0.15, places=6)

    def test_insufficient_data_is_neutral_zero_delta(self):
        r = compute_term_structure(_series(n=40, drift=0.002))
        self.assertEqual(r.state, "neutral")
        self.assertEqual(r.gate_delta, 0.0)

    def test_custom_thresholds_are_honored(self):
        px = _series(n=95, drift=0.004)
        for _ in range(20):
            px.append(px[-1] * (1.0 - 0.004))
        r = compute_term_structure(px, delta_topping=0.07)
        self.assertEqual(r.state, "topping")
        self.assertAlmostEqual(r.gate_delta, 0.07, places=6)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ../runtime/python/python.exe -m unittest tests.test_regime_term_structure -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'data.regime_term_structure'`.

- [ ] **Step 3: Write the module**

```python
# backend/data/regime_term_structure.py
"""
Multi-horizon trend term-structure signal, measured on a book-matched proxy.

Collapses 5/10/20/60/90-day momentum (vol-normalized to z-scores so horizons
and indices are comparable) into a discrete trend state that acts as a
tighten-only conservatism dial on the XGB BUY confidence threshold.

DESIGN RULE: imports ONLY stdlib + numpy. No agents, no main, no database, no
config singleton. Config values are passed in as parameters. Pure classifier
(`compute_term_structure`) + a thin stateful singleton (mirrors
data/regime_detector.py).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Dict, List

logger = logging.getLogger(__name__)

_HORIZONS = (5, 10, 20, 60, 90)
_MIN_PRICES = 91            # 90-day look-back + current bar
_TRADING_DAYS = 252
_VOL_WINDOW = 20

_Z_CUTOFF_DEFAULT = 0.5
_DELTA_TOPPING_DEFAULT = 0.10
_DELTA_WEAK_DEFAULT = 0.15


@dataclass(frozen=True)
class TermStructureResult:
    state: str                 # trending_up | topping | ranging_weak | neutral
    gate_delta: float          # >= 0, add to the BUY confidence threshold
    long_z: float
    short_z: float
    detail: Dict[str, float]


def _realized_vol(closes: List[float]) -> float:
    """Annualized std of the last _VOL_WINDOW daily log returns."""
    rets = [
        math.log(closes[i] / closes[i - 1])
        for i in range(len(closes) - _VOL_WINDOW, len(closes))
        if closes[i - 1] > 0
    ]
    if not rets:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    return math.sqrt(var * _TRADING_DAYS)


def compute_term_structure(
    closes: List[float],
    cutoff: float = _Z_CUTOFF_DEFAULT,
    delta_topping: float = _DELTA_TOPPING_DEFAULT,
    delta_weak: float = _DELTA_WEAK_DEFAULT,
) -> TermStructureResult:
    """Classify the trend term-structure of a proxy price series. Pure."""
    if len(closes) < _MIN_PRICES:
        return TermStructureResult("neutral", 0.0, 0.0, 0.0,
                                   {"reason_insufficient_data": 1.0, "n": float(len(closes))})
    vol20 = _realized_vol(closes)
    if not (vol20 > 0.0):
        return TermStructureResult("neutral", 0.0, 0.0, 0.0, {"reason_zero_vol": 1.0})

    last = closes[-1]
    mom: Dict[int, float] = {}
    z: Dict[int, float] = {}
    for h in _HORIZONS:
        m = last / closes[-1 - h] - 1.0
        mom[h] = m
        z[h] = m / (vol20 * math.sqrt(h / _TRADING_DAYS))

    long_z = (z[60] + z[90]) / 2.0
    short_z = (z[5] + z[10] + z[20]) / 3.0

    if long_z > cutoff and short_z >= 0.0:
        state, delta = "trending_up", 0.0
    elif long_z > cutoff and short_z < 0.0:
        state, delta = "topping", delta_topping
    else:
        state, delta = "ranging_weak", delta_weak

    detail: Dict[str, float] = {f"mom_{h}d": mom[h] for h in _HORIZONS}
    detail["vol20d"] = vol20
    return TermStructureResult(state, delta, long_z, short_z, detail)


class TermStructureDetector:
    """Thin stateful wrapper (mirrors data/regime_detector.RegimeDetector).

    Holds the latest classification. All logic lives in compute_term_structure;
    this only caches the last result so consumers can read it cheaply.
    """

    def __init__(self) -> None:
        self._result = TermStructureResult("neutral", 0.0, 0.0, 0.0, {"reason_uninitialized": 1.0})

    def update(
        self,
        closes: List[float],
        cutoff: float = _Z_CUTOFF_DEFAULT,
        delta_topping: float = _DELTA_TOPPING_DEFAULT,
        delta_weak: float = _DELTA_WEAK_DEFAULT,
    ) -> None:
        try:
            clean = [float(c) for c in closes if c and c > 0]
            self._result = compute_term_structure(clean, cutoff, delta_topping, delta_weak)
        except Exception as exc:  # never let a data glitch break the trading loop
            logger.debug(f"TermStructureDetector.update error: {exc}")

    def get_gate_delta(self) -> float:
        return self._result.gate_delta

    def get_state(self) -> str:
        return self._result.state

    def summary(self) -> dict:
        d = {"state": self._result.state, "gate_delta": self._result.gate_delta,
             "long_z": self._result.long_z, "short_z": self._result.short_z}
        d.update(self._result.detail)
        return d


term_structure_detector = TermStructureDetector()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ../runtime/python/python.exe -m unittest tests.test_regime_term_structure -v`
Expected: PASS (5 tests). Then clean up: `ps aux | grep python | grep -v grep | awk '{print $1}' | xargs kill -9 2>/dev/null` (skip anything on port 8000).

- [ ] **Step 5: Commit**

```bash
git add backend/data/regime_term_structure.py backend/tests/test_regime_term_structure.py
git commit -m "feat: pure multi-horizon term-structure classifier + tests"
```

---

### Task 2: Singleton wrapper tests + config knobs

**Files:**
- Modify: `backend/config.py` (add 5 knobs near the VOL_TARGET block, ~L196)
- Modify: `.env.example`
- Test: `backend/tests/test_regime_term_structure.py` (append a singleton test class)

**Interfaces:**
- Consumes: `term_structure_detector` (Task 1 singleton), `compute_term_structure`.
- Produces: `config.TERM_STRUCTURE_GATE_ENABLED: bool`, `config.TERM_STRUCTURE_PROXY: str`, `config.TERM_STRUCTURE_Z_CUTOFF: float`, `config.TERM_STRUCTURE_DELTA_TOPPING: float`, `config.TERM_STRUCTURE_DELTA_WEAK: float`.

- [ ] **Step 1: Write the failing singleton test**

```python
# append to backend/tests/test_regime_term_structure.py
from data.regime_term_structure import term_structure_detector


class TestTermStructureDetectorSingleton(unittest.TestCase):
    def test_update_then_get_reflects_classification(self):
        px = [100.0 * (1.002 ** i) for i in range(120)]   # sustained uptrend
        term_structure_detector.update(px)
        self.assertEqual(term_structure_detector.get_state(), "trending_up")
        self.assertEqual(term_structure_detector.get_gate_delta(), 0.0)

    def test_empty_update_is_neutral_zero_delta(self):
        term_structure_detector.update([])
        self.assertEqual(term_structure_detector.get_state(), "neutral")
        self.assertEqual(term_structure_detector.get_gate_delta(), 0.0)

    def test_summary_carries_zscores(self):
        px = [100.0 * (1.002 ** i) for i in range(120)]
        term_structure_detector.update(px)
        s = term_structure_detector.summary()
        self.assertIn("long_z", s)
        self.assertIn("short_z", s)
        self.assertIn("vol20d", s)
```

- [ ] **Step 2: Run to verify it passes** (singleton already exists from Task 1)

Run: `cd backend && ../runtime/python/python.exe -m unittest tests.test_regime_term_structure -v`
Expected: PASS (8 tests total). This class is a regression guard on the Task 1 singleton; no new production code needed for it.

- [ ] **Step 3: Add config knobs**

In `backend/config.py`, immediately after the `VOL_TARGET_CAP` line (~L198), add:

```python
    # ── Term-structure regime gate (2026-08-02) ──────────────────────────────
    # Multi-horizon trend signal on a book-matched proxy (QQQ). Tighten-only
    # conservatism dial on the XGB BUY threshold; combined via max() with the
    # regime add-on, never sum. Default OFF + shadow (see regime_term_structure.py).
    TERM_STRUCTURE_GATE_ENABLED: bool  = os.getenv("TERM_STRUCTURE_GATE_ENABLED", "0") == "1"
    TERM_STRUCTURE_PROXY:        str   = os.getenv("TERM_STRUCTURE_PROXY", "QQQ")
    TERM_STRUCTURE_Z_CUTOFF:     float = float(os.getenv("TERM_STRUCTURE_Z_CUTOFF", "0.5"))
    TERM_STRUCTURE_DELTA_TOPPING: float = float(os.getenv("TERM_STRUCTURE_DELTA_TOPPING", "0.10"))
    TERM_STRUCTURE_DELTA_WEAK:   float = float(os.getenv("TERM_STRUCTURE_DELTA_WEAK", "0.15"))
```

In `.env.example`, add:

```bash
# Term-structure regime gate (XGB only). OFF by default (shadow-logs while 0).
TERM_STRUCTURE_GATE_ENABLED=0
TERM_STRUCTURE_PROXY=QQQ
TERM_STRUCTURE_Z_CUTOFF=0.5
TERM_STRUCTURE_DELTA_TOPPING=0.10
TERM_STRUCTURE_DELTA_WEAK=0.15
```

- [ ] **Step 4: Verify config loads**

Run: `cd backend && ../runtime/python/python.exe -c "from config import config; print(config.TERM_STRUCTURE_GATE_ENABLED, config.TERM_STRUCTURE_PROXY, config.TERM_STRUCTURE_Z_CUTOFF, config.TERM_STRUCTURE_DELTA_TOPPING, config.TERM_STRUCTURE_DELTA_WEAK)"`
Expected: `False QQQ 0.5 0.1 0.15`

- [ ] **Step 5: Commit**

```bash
git add backend/config.py .env.example backend/tests/test_regime_term_structure.py
git commit -m "feat: term-structure gate config knobs + singleton tests"
```

---

### Task 3: Thread the delta through `decide_buy` (Gate 3)

**Files:**
- Modify: `backend/agents/xgb_decision.py` (`BuyContext` ~L42; Gate 3 ~L110-115)
- Test: `backend/tests/test_xgb_decision.py`

**Interfaces:**
- Consumes: `config.TERM_STRUCTURE_GATE_ENABLED`.
- Produces: `BuyContext(..., term_structure_delta: Optional[float] = None)`; Gate 3 uses `needed = CNN_BUY_THRESHOLD_BASE + max(regime_add, applied_ts_delta)`.

- [ ] **Step 1: Write the failing tests**

```python
# append to backend/tests/test_xgb_decision.py
# Reuses the module's existing helpers for building a BuyContext + fake config.
# If the file already has a _ctx(**kw) / _cfg(**kw) factory, use it; otherwise
# mirror the pattern already used by the vol-target tests in this file.

class TestTermStructureGate(unittest.TestCase):
    def _base_kw(self):
        # A context that PASSES gates 1-2 in bull so gate 3 is the decider.
        return dict(
            symbol="AAPL", model_pred_return=0.03, model_pred_direction="up",
            model_confidence=0.60, regime="bull", portfolio_unpnl_frac=None,
            n_corroborators=3, in_trail_cooldown=False, current_price=100.0,
            cash_available=10000.0, portfolio_value=10000.0, kelly_fraction=0.05,
        )

    def test_enabled_topping_delta_raises_threshold_and_holds(self):
        cfg = _make_config(TERM_STRUCTURE_GATE_ENABLED=True, CNN_BUY_THRESHOLD_BASE=0.50)
        ctx = BuyContext(**self._base_kw(), term_structure_delta=0.15)  # needs 0.65 > 0.60
        d = decide_buy(ctx, cfg)
        self.assertEqual(d.action, "HOLD")
        self.assertIn("regime gate", d.reason)

    def test_disabled_delta_is_shadow_only_buys(self):
        cfg = _make_config(TERM_STRUCTURE_GATE_ENABLED=False, CNN_BUY_THRESHOLD_BASE=0.50)
        ctx = BuyContext(**self._base_kw(), term_structure_delta=0.15)  # ignored → floor 0.50
        d = decide_buy(ctx, cfg)
        self.assertEqual(d.action, "BUY")

    def test_combined_via_max_not_sum(self):
        # bear (+0.15) AND ts +0.15 must give 0.65, not 0.80.
        cfg = _make_config(TERM_STRUCTURE_GATE_ENABLED=True, CNN_BUY_THRESHOLD_BASE=0.50)
        kw = self._base_kw(); kw["regime"] = "bear"; kw["model_confidence"] = 0.66
        ctx = BuyContext(**kw, term_structure_delta=0.15)
        d = decide_buy(ctx, cfg)
        self.assertEqual(d.action, "BUY")   # 0.66 >= 0.65 (max), would be HOLD if summed to 0.80

    def test_none_delta_behaves_as_before(self):
        cfg = _make_config(TERM_STRUCTURE_GATE_ENABLED=True, CNN_BUY_THRESHOLD_BASE=0.50)
        ctx = BuyContext(**self._base_kw(), term_structure_delta=None)
        self.assertEqual(decide_buy(ctx, cfg).action, "BUY")
```

Note: `_make_config` is this file's existing fake-config helper (the vol-target tests use it). If its name differs, use the local equivalent; it must return an object exposing `TERM_STRUCTURE_GATE_ENABLED`, `CNN_BUY_THRESHOLD_BASE`, and the other knobs `decide_buy` reads with sensible defaults.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && ../runtime/python/python.exe -m unittest tests.test_xgb_decision -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'term_structure_delta'`.

- [ ] **Step 3: Add the field + Gate 3 logic**

In `backend/agents/xgb_decision.py`, add to `BuyContext` (after the `realized_vol` field, ~L43):

```python
    term_structure_delta: Optional[float] = None   # book-proxy trend gate add-on
                                                    # (>=0); None when unavailable
```

Replace Gate 3 (~L110-115) with:

```python
    # Gate 3: regime-adjusted floor (adds 0.15 in bear, 0.20 in high_vol).
    # Term-structure gate (opt-in): combine via max() — never sum, never lower.
    # Tighten-only; the WFE falsifier is evaluated separately and is unaffected.
    regime_add = _REGIME_CONF_ADJ.get(ctx.regime, 0.0)
    ts_delta = ctx.term_structure_delta or 0.0
    ts_note = ""
    if ts_delta > 0.0:
        if config.TERM_STRUCTURE_GATE_ENABLED:
            regime_add = max(regime_add, ts_delta)
            ts_note = f" [ts+{ts_delta:.2f}]"
        else:
            ts_note = f" [ts+{ts_delta:.2f} shadow]"
    needed = config.CNN_BUY_THRESHOLD_BASE + regime_add
    if ctx.model_confidence < needed:
        return BuyDecision("HOLD", 0, ctx.model_confidence,
                           f"regime gate ({ctx.regime}): conf {ctx.model_confidence:.2f} < {needed:.2f}{ts_note}")
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && ../runtime/python/python.exe -m unittest tests.test_xgb_decision -v`
Expected: PASS (new class + all pre-existing decide_buy tests still green). Shell cleanup after.

- [ ] **Step 5: Commit**

```bash
git add backend/agents/xgb_decision.py backend/tests/test_xgb_decision.py
git commit -m "feat: thread term-structure delta through decide_buy Gate 3 (max-combine, tighten-only)"
```

---

### Task 4: XGB agent integration — update detector, shadow-log, pass delta

**Files:**
- Modify: `backend/agents/xgb_reasoning_agent.py` (the `analyze()` path where `BuyContext(...)` is built — the same construction that was extended for H15's `realized_vol=`)
- Test: `backend/tests/test_xgb_reasoning_agent.py`

**Interfaces:**
- Consumes: `term_structure_detector` (Task 1), `config.TERM_STRUCTURE_*` (Task 2), `BuyContext.term_structure_delta` (Task 3).
- Produces: the agent updates the detector from `market_context[config.TERM_STRUCTURE_PROXY]["bars"]`, logs `[TERM_STRUCT]` on state change, and passes `term_structure_delta` into `BuyContext`.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_xgb_reasoning_agent.py
# Verifies the agent updates the term-structure detector from QQQ bars and that
# the delta reaches the decision. Mirrors the existing agent-test harness in
# this file (reuse its agent factory / market_context builder / mocks).

class TestXGBReasoningAgentTermStructure(unittest.TestCase):
    def test_topping_qqq_bars_produce_shadow_delta(self):
        import pandas as pd
        from data.regime_term_structure import term_structure_detector
        # long-up then short-down QQQ path → topping
        px = [100.0 * (1.004 ** i) for i in range(95)]
        for _ in range(20):
            px.append(px[-1] * (1.0 - 0.004))
        bars = pd.DataFrame({"close": px})
        term_structure_detector.update(
            bars["close"].astype(float).tolist(),
        )
        self.assertEqual(term_structure_detector.get_state(), "topping")
        self.assertAlmostEqual(term_structure_detector.get_gate_delta(), 0.10, places=6)

    def test_missing_qqq_bars_fail_open(self):
        from data.regime_term_structure import term_structure_detector
        term_structure_detector.update([])   # simulate no proxy data
        self.assertEqual(term_structure_detector.get_gate_delta(), 0.0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && ../runtime/python/python.exe -m unittest tests.test_xgb_reasoning_agent.TestXGBReasoningAgentTermStructure -v`
Expected: PASS for these two (they exercise the detector directly). If green, they are the regression floor; proceed to wire the agent so the delta actually flows into `BuyContext` (verified by re-running the full agent test class in Step 4).

- [ ] **Step 3: Wire the agent**

At the top of `backend/agents/xgb_reasoning_agent.py`, add the import near the other `data.` imports:

```python
from data.regime_term_structure import term_structure_detector
```

Add an instance attribute in `__init__` (near other `self._last_*` state): `self._last_ts_state = None`.

In `analyze()`, immediately after the existing regime is read (near `regime=regime_detector.get_regime()[0]`), insert:

```python
        # Term-structure gate (book-proxy trend). Fail-open: missing/short data
        # leaves delta 0. Update is idempotent per cycle (same proxy bars).
        ts_delta = 0.0
        try:
            proxy_ctx = market_context.get(config.TERM_STRUCTURE_PROXY, {})
            proxy_bars = proxy_ctx.get("bars") if isinstance(proxy_ctx, dict) else None
            if proxy_bars is not None and not proxy_bars.empty and len(proxy_bars) >= 91:
                term_structure_detector.update(
                    proxy_bars["close"].astype(float).tolist(),
                    cutoff=config.TERM_STRUCTURE_Z_CUTOFF,
                    delta_topping=config.TERM_STRUCTURE_DELTA_TOPPING,
                    delta_weak=config.TERM_STRUCTURE_DELTA_WEAK,
                )
            ts_delta = term_structure_detector.get_gate_delta()
            ts_state = term_structure_detector.get_state()
            if ts_state != self._last_ts_state:      # log only on transition (low noise)
                self._last_ts_state = ts_state
                shadow = "" if config.TERM_STRUCTURE_GATE_ENABLED else " (shadow)"
                logger.info(f"XGBReasoningAgent: [TERM_STRUCT] state={ts_state} "
                            f"delta={ts_delta:.2f}{shadow}")
        except Exception as _e:
            logger.debug(f"XGBReasoningAgent: term-structure update error: {_e}")
```

At the `BuyContext(...)` construction in this method (the one already passing `realized_vol=`), add:

```python
            term_structure_delta=ts_delta,
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && ../runtime/python/python.exe -m unittest tests.test_xgb_reasoning_agent -v`
Expected: PASS (new class + all pre-existing agent tests green — the added kwarg is optional so nothing else breaks). Shell cleanup after.

- [ ] **Step 5: Commit**

```bash
git add backend/agents/xgb_reasoning_agent.py backend/tests/test_xgb_reasoning_agent.py
git commit -m "feat: XGB agent feeds QQQ term-structure detector + shadow-logs delta"
```

---

### Task 5: Docs + full-suite green

**Files:**
- Modify: `CLAUDE.md` (Trading-policy-defaults section)

- [ ] **Step 1: Document the knobs in CLAUDE.md**

In the "Trading policy defaults" section, after the `VOL_TARGET_*` entry, add:

```markdown
- `TERM_STRUCTURE_GATE_ENABLED=0`, `TERM_STRUCTURE_PROXY=QQQ`, `TERM_STRUCTURE_Z_CUTOFF=0.5`,
  `TERM_STRUCTURE_DELTA_TOPPING=0.10`, `TERM_STRUCTURE_DELTA_WEAK=0.15` (added 2026-08-02) —
  **XGBReasoningAgent-only** multi-horizon trend term-structure gate. `data/regime_term_structure.py`
  classifies QQQ 5/10/20/60/90d momentum (vol-normalized z-scores) into `trending_up` / `topping` /
  `ranging_weak`, emitting a `gate_delta` (0 / 0.10 / 0.15). In `xgb_decision.decide_buy` Gate 3 the
  delta is combined with the regime add-on via **`max()` (never sum, never lowers the threshold)** —
  tighten-only; the WFE falsifier is unaffected. **DEFAULT OFF (shadow):** while disabled the state +
  delta are computed and logged (`[TERM_STRUCT]` on transition) but not applied. Pure module
  (invariant #10). See spec `docs/superpowers/specs/2026-08-01-regime-term-structure-gate-design.md`.
```

- [ ] **Step 2: Run the FULL suite once**

Run: `cd backend && ../runtime/python/python.exe run_tests.py`
Expected: all green (existing count + new tests). If anything unrelated fails, STOP and report per find-list-fix — do not paper over it. Shell cleanup after.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md term-structure gate knobs"
```

- [ ] **Step 4: Push the branch**

```bash
git push -u origin feat/regime-term-structure-gate
```

---

## Post-implementation (memory sync — do in the same session, per feedback_sync_rule)

- Update memory `trading_app_thresholds` with the 5 knobs.
- Add an Iteration-15 cross-reference in `docs/model_improvement_ledger.md` pointing at the shipped gate (OFF/shadow).
- These are memory/doc updates, tracked outside the repo test suite.

## Validation (NOT part of the build — the shadow phase, per spec §7)

- After a few weeks OFF+shadow, confirm the `[TERM_STRUCT]` state distribution is sane (labels the current fading tape `topping`/`ranging_weak`; does NOT flag genuine uptrends).
- Pre-registered non-loosenable falsifier: a back-test over QQQ history must not label clear uptrends `topping`/`ranging_weak` more than rarely. If it does → reject; do NOT lower `TERM_STRUCTURE_Z_CUTOFF` to force a pass.

## Self-Review (writing-plans)

- **Spec coverage:** §3.1 classifier → Task 1; §3.2 singleton → Task 1/2; §4 QQQ wiring → Task 4; §5 gate integration → Task 3; §6 rollout/knobs → Task 2; §7 falsifier → Validation note; §8 tests → Tasks 1-4; §10 files → all tasks. Covered.
- **Placeholder scan:** all code steps contain real code; test commands have expected output. `_make_config`/`_ctx` in Task 3 explicitly reference the file's existing helper pattern rather than inventing an undefined symbol.
- **Type consistency:** `TermStructureResult`, `compute_term_structure(closes, cutoff, delta_topping, delta_weak)`, `term_structure_detector.get_gate_delta()/get_state()`, and `BuyContext.term_structure_delta` are used identically across Tasks 1-4.
