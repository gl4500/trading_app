# Design Spec — Multi-Horizon Regime Term-Structure Gate (XGB)

**Date:** 2026-08-01
**Status:** Design approved (brainstorm), pending spec review → plan → TDD build
**Scope:** `trading_app` only. XGBReasoningAgent path only.
**Related:** `docs/model_improvement_ledger.md` (Iteration 14), `backend/data/regime_detector.py`,
`backend/data/regime_leading.py`, CLAUDE.md invariant #10 (loose coupling).

---

## 1. Problem

The XGBReasoningAgent's BUYs are gated off because the model's walk-forward edge is currently
absent (live model, retrained 2026-07-31: `mean_ic = −0.053`, `mean_wfe = −0.140`, most-recent
fold IC `−0.176`). That gating is **correct** — we do not trade a model with no measured edge.

Separately, the system's regime signal is too coarse to describe *why* the environment is
hostile to the model. Two blind spots were found during diagnosis:

1. **Single-horizon.** `regime_detector` classifies off a single **SPY 20-day** momentum + vol
   window. A gradual multi-week roll-over never breaches its ±2% / 20%-vol thresholds, so it
   labels a decelerating tape `neutral`. A multi-horizon view (5/10/20/60/90d) shows the medium
   trend fading fold-over-fold (60d: +14% → +10% → +6% across Jun–Jul) while the short end goes
   flat — a "topping" shape the 20d window collapses to nothing.
2. **Wrong index.** The detector watches **SPY**, but the traded book is tech/semi-heavy
   (MU, WOLF, FATE, AMD, DDOG; beta ≈ 1.3 to SPY) and tracks the **NASDAQ**. Over Jun 1 → Jul 31,
   SPY was roughly flat-to-up while the NASDAQ fell **−6.3%**. A regime measured on SPY reports
   "constructive" during exactly the stretch the book declined.

### Evidence (multi-horizon SPY momentum at each fold end)

| Fold window · model IC | 5d | 10d | 20d | 60d | 90d | vol20d |
|---|---|---|---|---|---|---|
| fold 0 · Jun 15–23 · IC **+0.040** | −2.6% | −0.5% | −1.4% | **+14.0%** | +6.6% | 16.8% |
| fold 1 · Jun 24–Jul 07 · IC −0.022 | +0.9% | +0.5% | +1.6% | **+10.3%** | +8.4% | 15.4% |
| fold 2 · Jul 07–21 · IC **−0.176** (= live model) | −0.5% | +0.1% | +0.5% | **+5.9%** | +11.2% | 11.7% |

On the book's proxy (NASDAQ) the same windows were declining, not rising — the index gap.

---

## 2. Goal & non-goals

**Goal.** Add a multi-horizon **trend term-structure** signal, measured on a **book-matched
proxy (QQQ)**, that collapses to a discrete *trend state* and acts as a **conservatism dial** on
the XGBReasoningAgent's BUY confidence threshold: raise the bar when the trend the model was
trained on is fading; leave it alone when the trend is intact.

**Non-goals.**
- **Does not restore the model's absent edge.** It only avoids buying into a fading trend once
  edge returns. It cannot unblock BUYs on its own.
- **Never loosens the WFE falsifier.** The delta is tighten-only. It cannot lower any threshold
  or override the WFE gate (`max(xgb_wfe, w3_wfe) < 0` still blocks).
- Does not change any other agent's sizing or gating. XGB path only.
- Does not replace `regime_detector` (which still feeds EnsembleAgent multipliers, etc.).

---

## 3. Component design

### 3.1 New pure module — `backend/data/regime_term_structure.py`

Modeled on `regime_detector.py` / `regime_leading.py`: **imports only stdlib + numpy** (no
imports from `agents/`, `main`, `config` singleton, or `database`) so it satisfies the
loose-coupling invariant and is unit-testable in isolation. Configuration values are passed in
as parameters (or read from a small local defaults block), not imported.

**Pure classifier (testable core):**

```
compute_term_structure(closes: list[float], *, cutoff: float, deltas: dict) -> TermStructureResult
```

- `closes`: proxy (QQQ) closing prices, most-recent-last. `< 91` prices → returns a
  `neutral`/`ranging_weak` result with `gate_delta = 0.0` (graceful degradation, same posture as
  "insufficient data" in `regime_detector`).
- Computes trailing momentum at **h ∈ {5, 10, 20, 60, 90}** days: `mom_h = closes[-1]/closes[-1-h] − 1`.
- Computes **20-day realized vol** (annualized) as in `regime_detector`.
- **Vol-normalizes each horizon to a z-score** so horizons *and* indices are comparable:
  `z_h = mom_h / (vol20d · sqrt(h / 252))`.
- Two composite legs:
  - `long_z  = mean(z_60, z_90)`   (established trend)
  - `short_z = mean(z_5, z_10, z_20)` (recent trend)

**State machine:**

| State | Condition | `gate_delta` (default) |
|---|---|---|
| `trending_up` | `long_z > cutoff` and `short_z >= 0` | **+0.00** |
| `topping`     | `long_z > cutoff` and `short_z < 0` | **+0.10** |
| `ranging_weak`| `long_z <= cutoff` (no established up-trend) | **+0.15** |

Default `cutoff = 0.5` (z units). `TermStructureResult` carries: `state: str`,
`gate_delta: float`, and a `detail` dict (`long_z`, `short_z`, per-horizon `mom_h`, `vol20d`) for
logging/introspection.

### 3.2 Stateful singleton (thin wrapper)

`TermStructureDetector` singleton (mirrors `regime_detector`):
- `.update(closes)` — stores latest proxy prices, runs `compute_term_structure`.
- `.get_gate_delta()` → float, `.get_state()` → str, `.summary()` → dict (for API/logging).
- Holds no business logic beyond caching last result; all classification lives in the pure fn.

---

## 4. Data wiring — the QQQ proxy series

The detector needs a maintained QQQ price history. Follow the precedent that added `^VIX3M`/`HYG`
for `regime_leading`: **add `QQQ` to the macro proxy fetch** so a rolling close history is kept in
the macro fast-cache. In the same refresh path where `regime_detector.update(spy_prices)` runs,
call `term_structure_detector.update(qqq_closes)`.

- Proxy symbol is a config knob (`TERM_STRUCTURE_PROXY = "QQQ"`) so it can be swapped for `^IXIC`
  or the exact dollar-vol basket later without code change.
- If QQQ data is unavailable on a cycle, `.update` is skipped and the last state persists;
  `compute_term_structure` with `< 91` prices returns delta 0 (fail-open, never blocks on missing
  data).

---

## 5. Gate integration (XGBReasoningAgent)

At the existing regime-confidence step in `xgb_reasoning_agent` (where the current
`+0.15 bear / +0.20 high_vol` adjustment to the BUY confidence threshold is applied):

```
ts_delta = term_structure_detector.get_gate_delta() if config.TERM_STRUCTURE_GATE_ENABLED else 0.0
effective_delta = max(existing_regime_delta, ts_delta)      # tighten-only, no double-count
buy_threshold  += effective_delta
```

- Combined via **`max()`**, not sum — never over-tighten by stacking two regime views.
- **Tighten-only:** `gate_delta >= 0` always; it can only raise `buy_threshold`.
- **WFE gate untouched:** the term-structure delta is applied to the confidence threshold only;
  the WFE falsifier (`_apply_wfe_gate`) runs independently and still blocks BUYs when
  `max(xgb_wfe, w3_wfe) < 0`.

---

## 6. Rollout — shadow-first (mirrors H15)

Ship **disabled by default** with shadow logging, exactly like the H15 vol-target sizing rollout:

- `TERM_STRUCTURE_GATE_ENABLED = 0` (default). While off, the state and would-be delta are still
  computed and logged each cycle as `[TERM_STRUCT] state=<...> long_z=<...> short_z=<...>
  delta=<...> (shadow)`, but `buy_threshold` is unchanged.
- Flip to `1` to activate (requires backend restart — config read at import; not during active
  trading/retrain, per operating guardrails).
- Because live XGB BUYs are currently gated off by WFE, shadow mode is the only honest way to
  observe the classifier now; it lets us confirm the state labels are sane before it gates
  anything.

### Config knobs (all in `config.py`, `.env`-overridable)

| Knob | Default | Meaning |
|---|---|---|
| `TERM_STRUCTURE_GATE_ENABLED` | `0` | Master on/off (shadow when 0). |
| `TERM_STRUCTURE_PROXY` | `QQQ` | Price series the term-structure is measured on. |
| `TERM_STRUCTURE_Z_CUTOFF` | `0.5` | `long_z` threshold separating trending from ranging. |
| `TERM_STRUCTURE_DELTA_TOPPING` | `0.10` | BUY-threshold add in `topping`. |
| `TERM_STRUCTURE_DELTA_WEAK` | `0.15` | BUY-threshold add in `ranging_weak`. |

---

## 7. Validation & falsifiability

- **Sanity (shadow, ~2 weeks):** the state distribution must match reality — it should label the
  current fading tape `topping`/`ranging_weak`, and it must **not** label a genuine uptrend (e.g.
  May 2026 on the proxy) as `topping`/`weak`. **Pre-registered falsifier:** if a back-test over the
  proxy's history labels clear uptrends as `topping`/`weak` more than rarely, the classifier is
  broken and the design is rejected — do not "fix" by loosening the cutoff post hoc.
- **Back-test (pure fn):** run `compute_term_structure` over multi-year QQQ history; confirm
  `gate_delta > 0` concentrates in draw-down / roll-over periods and is ≈0 during sustained
  up-trends.
- **Live effect** can only be measured once XGB WFE turns positive and BUYs flow again; until then
  the gate is dormant-by-construction and shadow logs are the evidence.

---

## 8. Testing plan (TDD, unittest)

New `backend/tests/test_regime_term_structure.py`:

1. Synthetic sustained up-trend series → `trending_up`, `gate_delta == 0`.
2. Synthetic long-up + recent-down series (the Jul-21 book shape) → `topping`, `delta == 0.10`.
3. Synthetic flat/declining series → `ranging_weak`, `delta == 0.15`.
4. z-normalization: doubling series vol halves each `z_h` (scale correctness).
5. `< 91` prices → `ranging_weak`/neutral, `delta == 0` (graceful degradation).
6. Singleton `.update` / `.get_gate_delta` round-trip; persists last state when fed empty.
7. Gate combination: `max(existing_regime_delta, ts_delta)` — ts never lowers the threshold, never
   stacks additively; disabled flag → ts_delta forced 0.
8. Config knobs honored (cutoff / deltas read from passed config, not hard-coded).

Run via `runtime\python\python.exe run_tests.py`; full suite green before commit; shell cleanup
after.

---

## 9. Risks & open items

- **Proxy ≠ exact book.** QQQ is a beta-≈1.3 stand-in, not the dollar-vol basket. Accepted for v1;
  `TERM_STRUCTURE_PROXY` leaves the door open to the exact basket later (Option 3 divergence is the
  named phase-two).
- **Threshold tuning.** `cutoff` / deltas are first-guess values; the shadow period informs any
  adjustment (adjust *before* enabling, not after seeing live PnL — avoid falsifier-loosening).
- **Interaction with `high_vol`.** `max()` combination means a `high_vol` reading (+0.20) already
  dominates the topping delta (+0.10); that's intended (high_vol is the more severe signal).
- **Does not help while edge is absent.** Set expectations: this is risk-control layering, not an
  edge source. It earns its keep only when the model is trading again.

---

## 10. Files touched (anticipated)

- **New:** `backend/data/regime_term_structure.py`, `backend/tests/test_regime_term_structure.py`
- **Edit:** `backend/config.py` (5 knobs), `backend/main.py` (QQQ fetch + `.update` call in the
  macro/regime refresh), `backend/agents/xgb_reasoning_agent.py` (read delta, `max()`-combine,
  shadow log), `.env.example` (document knobs)
- **Docs:** `CLAUDE.md` (Trading-policy-defaults + invariant note), `trading_app_thresholds`
  memory (knob table), `docs/model_improvement_ledger.md` (cross-reference)
