# MC Strategy Backtester — Design Spec

**Date:** 2026-05-16
**Author:** brainstorm session (gl4500 + Claude)
**Status:** Draft, pending user review

---

## 1. Overview

Add a Monte Carlo strategy backtester to `trading_app` so we can compare
candidate **8-channel XGB filter variants** against each other under realistic,
varied market conditions before deploying any change to production.

First concrete use case (chosen 2026-05-16): test the current production
8-channel filter against alternative channel sets (e.g., the "swap-both"
variant noted in `trading_app_architecture.md`, or candidates surfaced by a
future forward-selection run). Output: a per-variant percentile distribution
of Sharpe / max-drawdown / final-return, across 1,000 bootstrapped alternate
market histories.

The backtester is **offline-only** (a CLI script + library module). It does
not run inside the live FastAPI process and does not change live trading
behaviour. Trains models once per variant, simulates K alternate paths, runs
the same paths through every variant for paired comparison, aggregates.

## 2. Goals and non-goals

**Goals**
- Compare ≥ 2 candidate XGB feature filters on a distribution of plausible
  market outcomes, not a single historical point estimate.
- Loose coupling: backtester module consumes only `signal_model.predict()`
  and a new `cnn_decision.decide_buy()` public surface — never imports
  `CNNReasoningAgent`, `OllamaAgent`, `main`, or any I/O module.
- Paired-sample comparison: every variant sees the same K bootstrapped paths,
  so differences in outcome are attributable to the model.
- Pure-function decision logic: the BUY chain (gates + sizing) extracted from
  `CNNReasoningAgent` into pure helpers, used by both production and backtest.

**Non-goals (this iteration)**
- Full multi-agent ensemble replay — only the CNN-style BUY decision chain.
- LLM-in-the-loop simulation — Ollama is not called.
- Live integration into the trading loop — purely an offline CLI tool.
- Online retraining per simulated path — train once per variant on full
  history, then simulate.
- Replay of news, earnings catalysts, or sentiment paths — these channels are
  bootstrapped jointly with returns as part of the row, not regenerated.

## 3. Architecture and module layout

```
backend/
├── agents/
│   ├── cnn_decision.py          ← NEW: pure BUY decision helpers
│   ├── cnn_reasoning_agent.py   ← REFACTOR: calls cnn_decision
│   └── base_agent.py            ← (unchanged; provides SELL helpers via inheritance)
├── data/
│   ├── mc_backtester.py         ← NEW: simulator + replay + aggregator (library)
│   ├── signal_model.py          ← (unchanged; consumed via public predict())
│   └── signal_history.py        ← (unchanged; provides historical data)
└── tests/
    ├── test_cnn_decision.py     ← NEW
    └── test_mc_backtester.py    ← NEW

scripts/
└── mc_backtest_filters.py       ← NEW: CLI — orchestrates a variant comparison run
```

**Dependency direction (one-way):**

```
scripts/mc_backtest_filters.py
   │
   ▼
backend/data/mc_backtester.py  ──►  cnn_decision.py
   │                                signal_model.py
   ▼                                signal_history.py
backend/agents/base_agent.py          (for SELL helpers via _BacktestAgent subclass)
```

`cnn_reasoning_agent.py` ALSO imports `cnn_decision.py` (single source of
truth for BUY logic) but neither knows about the other.

## 4. `cnn_decision.py` — pure BUY decision helpers

Extracted from the inline gate-and-size chain currently in
`CNNReasoningAgent.analyze()`. Pure functions of inputs — no I/O, no LLM,
no DB.

### Types

```python
from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class BuyContext:
    """Everything needed to make one CNN BUY/HOLD decision."""
    symbol: str
    # Model output
    cnn_pred_return: float
    cnn_pred_direction: Literal["up", "down", "neutral"]
    cnn_confidence: float                  # 0..1
    # Market and portfolio state
    regime: Literal["bull", "neutral", "bear", "high_vol"]
    portfolio_unpnl_frac: Optional[float]  # uPnL / total_value; None if no positions
    n_corroborators: int                   # OTHER agents agreeing (0 in backtest)
    in_trail_cooldown: bool
    current_price: float
    cash_available: float
    portfolio_value: float
    kelly_fraction: float                  # caller computes via Portfolio


@dataclass(frozen=True)
class BuyDecision:
    action: Literal["BUY", "HOLD"]
    shares: int                            # 0 when HOLD
    sized_confidence: float                # after lone-wolf shrink
    reason: str                            # gate name or sizing summary
```

### The function

`config` is the app-wide `backend/config.py::Config` singleton (already a
namespace of constants like `MAX_POSITION_SIZE`, `LONEWOLF_MULTIPLIER`,
`CNN_PAUSE_UPNL_DRAWDOWN_PCT`). Passed in for testability — no global import
inside the pure helper.

```python
def decide_buy(ctx: BuyContext, config) -> BuyDecision:
    """Full BUY decision chain. Gates evaluated in this order:

      1. direction == "up"                            else HOLD("not bullish")
      2. cnn_confidence >= _MIN_CNN_CONF              else HOLD("low conf")
      3. cnn_confidence >= 0.50 +
           regime_detector.get_confidence_gate(regime) else HOLD("regime gate")
      4. portfolio_unpnl_frac is None or
           portfolio_unpnl_frac > CNN_PAUSE_UPNL_DRAWDOWN_PCT
                                                       else HOLD("uPnL DD")
      5. NOT in_trail_cooldown                         else HOLD("trail cool-down")

    Sizing (when all gates pass):
      - base = quarter-Kelly fraction (passed in via ctx.kelly_fraction)
      - if n_corroborators < LONEWOLF_MIN_CORROBORATORS:
            base *= LONEWOLF_MULTIPLIER
      - size_pct = clamp(base, 0.02, MAX_POSITION_SIZE)
      - shares = int(size_pct * portfolio_value / current_price)
      - if shares < 1: HOLD("under-funded")
    """
```

### Refactor scope on `CNNReasoningAgent`

After refactor, `analyze()` becomes a thin orchestrator:
1. Pull model prediction
2. Build `BuyContext` from agent state + market context
3. `decision = decide_buy(ctx, config)`
4. If `decision.action == "BUY"`, emit a `Signal`
5. Persist learning / picks / DB writes (unchanged)

LLM prompting, Ollama call, and reasoning chain stay in the agent (those
are I/O-bound and instance-bound; not part of the pure decision).

## 5. Path simulator — `StationaryBlockBootstrap`

### Algorithm (Politis & Romano 1994)

```
1. day_idx = randint(0, n_historical_days - 1)        # uniform start
2. block_len = numpy.random.geometric(p=1/L)          # L = expected block size
3. take rows[day_idx : day_idx + block_len]           # whole block, all symbols + channels
4. wrap around at end (circular) so every block is full-length
5. append to path; if len(path) < target, goto 1
```

### Key choices

- **Whole rows bootstrapped jointly** (returns + all 38 channels) — the
  simulated path is internally consistent across channels.
- **Date-aligned blocks** — all 222 symbols' rows on the sampled dates move
  as a unit. Preserves cross-symbol correlation. Per-symbol independent
  bootstrap would underestimate portfolio risk.
- **Stationary** (Politis-Romano) means block lengths are random
  (~Geometric), so the path is itself a stationary process — no fixed seam
  pattern artefact.
- **Default `expected_block_size = 10`** (≈ 2 weeks) — short enough to mix
  regimes, long enough to preserve within-block serial correlation /
  vol-clustering.
- **Lazy iterator** for K paths — keeps memory O(one path), not O(K).

### Public API

```python
@dataclass
class BootstrapConfig:
    expected_block_size: int = 10
    n_paths: int = 1000
    path_length_days: int = 252
    seed: int = 42


class StationaryBlockBootstrap:
    def __init__(self, history: pd.DataFrame, cfg: BootstrapConfig):
        """history: long-format (date, symbol)-indexed frame with all channels."""

    def sample_path(self) -> pd.DataFrame:
        """One bootstrapped path. Same long format as input."""

    def simulate(self) -> Iterator[pd.DataFrame]:
        """Yield all K paths lazily."""
```

## 6. Replay loop and aggregation

### `replay_one_path`

```python
def replay_one_path(
    path: pd.DataFrame,           # (date × symbol) returns + channels
    model: SignalXGBoost,         # already trained on full history
    variant_name: str,
    sim_idx: int,
    starting_capital: float,
    config: Config,
) -> PathOutcome:
    """Day-by-day strategy replay on one bootstrapped path.

    Per-day order (matches BaseAgent.run_cycle in production):
      1. portfolio.record_value(prices)  — peak/uPnL bookkeeping
      2. SELL pass: bayes_exits + trailing_stops + hard_stops
      3. BUY pass: for each symbol, predict() → decide_buy() → maybe execute
      4. Append portfolio total_value to daily_values

    Returns PathOutcome(sharpe, max_drawdown, final_return, n_trades, ...).
    """
```

**Regime detector lifecycle**: a fresh `RegimeDetector` is instantiated per
path. The replay loop feeds it the simulated SPY return series day by day
(same `update(spy_close)` API as production). `regime_detector.get_regime()`
provides the `regime` value passed into each `BuyContext`. Per-path
instantiation prevents state leakage across simulated histories.

**Price derivation**: simulator yields returns (and other channels). Prices
on day 0 are seeded at $100 per symbol (arbitrary base; only ratios matter
for Sharpe/DD). Each subsequent day compounds: `price[t] = price[t-1] *
(1 + return[t])`.

### `_BacktestAgent`

Minimal `BaseAgent` subclass that uses `BacktestPortfolio`, no-ops file I/O
(`_load_picks`, `_save_picks`), and provides a stub `analyze()`. Exists ONLY
so we can call its inherited `_check_bayes_exits` / `_check_trailing_stops`
/ `_check_hard_stops` / `_in_trail_cooldown` against the backtest portfolio.

### `BacktestPortfolio`

In-memory Portfolio mirroring the public surface needed by the SELL
helpers and the BUY context. Specifically:

- Inherits / mirrors from `trading.portfolio.Portfolio`:
  `cash`, `positions`, `trade_history`, `kelly_fraction()`,
  `total_value(prices)`, `execute_buy()`, `execute_sell()`,
  `record_value(prices)`, `_position_peak_unrealized` (so trail-stop fires
  correctly), `unrealized_pnl_pct(prices)`.
- Adds: `unpnl_frac(prices) -> Optional[float]` — returns total uPnL /
  total_value, or `None` when no positions held. Lifts the existing
  computation from `CNNReasoningAgent._unrealized_pnl_pct` so it lives on
  the portfolio (its natural home). Production agent should be updated
  in the same PR to call `portfolio.unpnl_frac()` instead of its own
  helper.

NO database, NO file I/O.

The `_in_trail_cooldown` method already lives on `BaseAgent` (added in
yesterday's PR #41) — `_BacktestAgent` inherits it untouched.

### Aggregation

```python
def run_variant_comparison(
    variants: list[FilterVariant],
    historical: pd.DataFrame,
    cfg: BootstrapConfig,
    config: Config,
) -> VariantComparisonReport:
    """For each bootstrapped path, run ALL variants on that SAME path
    (paired-sample comparison). Returns the report.
    """
    sampler = StationaryBlockBootstrap(historical, cfg)
    all_outcomes: list[PathOutcome] = []

    for sim_idx, path in enumerate(sampler.simulate()):
        for variant in variants:
            all_outcomes.append(
                replay_one_path(path, variant.model, variant.name,
                                sim_idx, starting_capital, config)
            )
    return summarise(all_outcomes)
```

### Report format

Markdown table (per-variant p5 / p50 / p95 for each metric) plus a JSONL
log of every `PathOutcome`. Written to `scripts/logs/mc_backtest_<ts>.md`
and `scripts/logs/mc_backtest_<ts>.jsonl`.

## 7. Testing strategy

TDD-first per `feedback_tdd_workflow.md`. Each module gets a dedicated test
file under `backend/tests/`.

### `test_cnn_decision.py`

Pure-function tests. Table-driven where useful.

- Each gate independently:
  - `test_holds_when_direction_not_up`
  - `test_holds_when_cnn_confidence_below_floor`
  - `test_holds_when_regime_gate_blocks_in_bear`
  - `test_holds_when_portfolio_uPnL_in_drawdown`
  - `test_holds_when_in_trail_cooldown`
- Sizing chain:
  - `test_kelly_passed_through_when_corroborators_meet_threshold`
  - `test_lonewolf_multiplier_applied_below_threshold`
  - `test_size_clamped_to_max_position_size`
  - `test_holds_when_computed_shares_below_one`
- Edge cases:
  - `test_portfolio_unpnl_frac_none_passes_drawdown_gate`
  - `test_max_position_clamp_when_kelly_huge`

### `test_mc_backtester.py`

- `TestStationaryBlockBootstrap`
  - `test_path_length_matches_config`
  - `test_block_lengths_distributed_geometric`
  - `test_cross_symbol_correlation_preserved_within_blocks`
  - `test_seed_reproducibility`
  - `test_wraparound_handles_end_of_history`
- `TestReplay`
  - `test_replay_executes_buys_when_decide_buy_returns_buy`
  - `test_replay_respects_sell_helpers`
  - `test_replay_records_daily_values_for_sharpe`
  - `test_replay_outcome_matches_known_synthetic_path`
- `TestAggregation`
  - `test_paired_comparison_same_path_for_all_variants`
  - `test_percentile_math_correct_for_known_distribution`
  - `test_jsonl_output_round_trip`

### Integration smoke

One end-to-end test using a synthetic 2-symbol, 100-day toy dataset and 5
bootstrap paths, asserting:
- All paths run to completion without exceptions
- Output report has the expected schema
- Reproducible with a fixed seed

## 8. Implementation plan (high-level)

To be expanded by `superpowers:writing-plans` into a step-by-step plan.
Coarse ordering:

1. **Refactor `CNNReasoningAgent`** — extract BUY decision into
   `cnn_decision.py`. RED tests first (`test_cnn_decision.py`), then GREEN
   by extracting. Production agent's behaviour unchanged. Ship as its own
   PR before any backtester code.
2. **Path simulator** — implement `StationaryBlockBootstrap` with full unit
   tests. Standalone, no integration.
3. **Backtest portfolio + stripped agent** — `BacktestPortfolio` mirroring
   the `Portfolio` surface needed by SELL helpers; `_BacktestAgent` subclass
   wiring.
4. **Replay loop** — `replay_one_path` + `PathOutcome`. Tests using
   synthetic toy paths.
5. **Aggregation + report** — `run_variant_comparison`, percentile math,
   Markdown + JSONL writers.
6. **CLI script** — `scripts/mc_backtest_filters.py` — argparse, training a
   model per variant, loading historical data, running the comparison,
   writing the report.
7. **Documentation** — README section in `docs/` covering usage, example
   output, performance notes.

Each step ships as its own PR (per the project's recent PR pattern —
PRs #37 through #42 from today's session).

## 9. Open questions and future work

- **Channel forward-selection in the loop:** out of scope here, but the
  same backtester can power a future "search for best filter" loop.
- **Multi-agent ensemble replay:** the per-day BUY pass currently only
  uses `cnn_decision`. To eventually replay full ensemble voting, we'd
  need to lift each agent's decision into a pure helper too.
- **Regime detector calibration on simulated paths:** the detector
  classifies bull/neutral/bear/high_vol from SPY 20d momentum + realised
  vol. Bootstrapped paths preserve historical distribution, so behaviour
  *should* match — needs a sanity test (`test_regime_detector_on_bootstrap`)
  that the per-regime fraction in 1000 simulated paths roughly matches the
  per-regime fraction in the real 10y history.
- **Performance:** 3 variants × 1000 paths × 252 days × 222 symbols is
  ~170M model predictions per run. Need to time the smoke test and decide
  whether to add multiprocessing or shrink default K.
- **Correlated bootstrap** — if certain symbols' channels include
  forward-looking indicators (earnings_score, news), do they break the
  assumption that the channel "matches" the alternate returns? Worth
  validating in the smoke test.

## 10. Loose-coupling guarantees (revisited)

Enforced by the dependency rules in Section 3. To make these provable in
CI later (out of scope today):

- A linter rule that fails if `backend/data/mc_backtester.py` imports
  anything from `backend/agents/cnn_reasoning_agent.py`,
  `backend/agents/ollama_agent.py`, `backend/agents/ensemble_agent.py`,
  `backend/main.py`, or `backend/database.py`.
- A linter rule that fails if `backend/agents/cnn_decision.py` imports
  anything outside `dataclasses`, `typing`, and `config`.

For now, enforced by code review and the spec.
