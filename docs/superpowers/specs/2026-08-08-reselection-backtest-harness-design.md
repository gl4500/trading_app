# Re-selection Backtest Harness — Design Spec

**Date:** 2026-08-08
**Status:** Approved design, pre-implementation
**Author:** R&D (ledger continuation of Iteration 16)

## 1. Motivation

Ledger **Iteration 16** validated the three HistoricalTrendsAgent knobs shipped in PR #93. Two of
them (`HIST_PREARM_STOP_PCT`, `HIST_CONFIDENCE_CAP`) were settled decisively by read-only replay. The
third — `HIST_SEASONAL_WEIGHT=0.0` (drop the seasonal pillar) — could only be answered **directionally**,
because zeroing the pillar changes *which trades the agent would open*, and realized trade history cannot
show entries that never happened. Every entry-changing idea hits the same wall.

This harness removes that wall: it re-runs the agent's **real** signal generation over history so the
*re-selected* trade set (including entries that didn't happen live) can be evaluated end-to-end.

## 2. Goals / Non-goals

**Goals**
- Re-run a rule agent's actual `analyze()` + the full live exit chassis over historical bars, point-in-time.
- Support A/B comparison of two configs (e.g. `HIST_SEASONAL_WEIGHT` 0.20 vs 0.0) → a signed net-PnL delta.
- Be **trustworthy**: reproduce the live agent's realized PnL over a known window within tolerance before
  any variant result is believed.

**Non-goals (YAGNI)**
- Not a multi-agent or portfolio-level simulator — one agent, its own book (matches how each live agent
  runs its own `Portfolio`).
- Not intraday — daily close-to-close cadence.
- Not a live-data fetcher — consumes the offline `backend/data/history/*.parquet` cache only.
- Other rule agents (Momentum, MeanReversion, …) are **designed-for but not built** in this iteration.

## 3. Design driver (from Iteration 16)

100% of HistoricalTrendsAgent's PnL is made in the **exit layer** (trailing stop / hard stop), not the
entries. Therefore the harness must reproduce the exit chassis faithfully — a reimplemented exit model
would reintroduce exactly the kind of modeling gap this tool exists to avoid. Decision: **drive the real
`BaseAgent.run_cycle`**, not a reimplementation.

## 4. Architecture — full-chassis daily event loop

For each trading day `T` in the backtest range, for the agent under test:

1. **Build point-in-time inputs.** For each universe symbol, `market_context[symbol] = {"price":
   close_T, "long_term_bars": bars_asof(symbol, T)}` where `bars_asof` returns only rows with timestamp
   `≤ T`. `prices` includes every universe symbol **and** every currently-held symbol (so exits can fire
   on names that left the entry universe).
2. **Set the injected clock** to `T` (see §6).
3. `await agent.run_cycle(market_context, prices)` — the real cycle runs: `reset_daily_tracking` →
   `check_daily_loss` → `analyze()` (entries) → bayes exits → trailing-stop exits → execute BUY/SELL
   (Kelly + `RiskManager` gates) → hard-stop exits → ledger-drift assertion. The agent's **in-memory
   `Portfolio` mutates**; no database is touched (`_execute_signal` calls `portfolio.execute_buy/sell`,
   and DB persistence lives in `main.py`'s loop, which the harness does not run).
4. **Record** the day's executed trades and mark-to-market equity (`portfolio.get_total_value(prices)`).

At the end, read realized PnL, equity curve, and the trade log off `agent.portfolio`. Running the loop
twice with different `config_overrides` (baseline vs variant) yields the signed net delta.

### Fill convention & no-lookahead
Close-to-close: decisions on day `T` use bars **through T's close** and fill at **T's close**. Because
`bars_asof` hard-filters `snapshot_ts ≤ T`, the channel / momentum / volume pillars can only see past
data; the seasonal pillar reads the injected date `T`. This is the single most important correctness
property and gets a dedicated test (§7).

## 5. Components

A **new `backend/backtest/` package**, kept separate from `backend/data/mc_backtester.py` so invariant
#10 (mc_backtester must **not** import agents) is not muddied by a neighbour that intentionally does.

### 5.1 `backend/backtest/bars_provider.py`
Reads the parquet cache, resamples to a daily `close`/`volume` series per symbol, serves point-in-time
slices. No agent knowledge.
- `class BarsProvider(history_dir: Path)`
- `bars_asof(symbol: str, as_of: date) -> pd.DataFrame | None` — columns `close`, `volume`, ascending
  date index, rows with date `≤ as_of` only; `None` if the symbol has no parquet or `< min_bars` rows.
- `close_asof(symbol: str, as_of: date) -> float | None` — the day's close (last row of `bars_asof`).
- `trading_days(start: date, end: date) -> list[date]` — union of dates present across symbols
  (avoids inventing bars on non-trading days).
- Resampling rule: parquet `price` → daily `close` = **last** snapshot price of the day; `volume` =
  last snapshot volume of the day. The `price` column is renamed to `close` because the agent reads
  `df["close"]`.

### 5.2 `backend/backtest/reselection.py`
The event-loop engine.
- `@dataclass BacktestResult`: `realized_pnl: float`, `final_equity: float`, `equity_curve:
  list[tuple[date, float]]`, `trades: list[dict]` (date, symbol, action, shares, price, reasoning,
  pnl), `n_cycles: int`.
- `def run_backtest(agent_factory: Callable[[], BaseAgent], universe: list[str], start: date, end:
  date, bars: BarsProvider, config_overrides: dict[str, Any] | None = None) -> BacktestResult`
  - `agent_factory` returns a fresh agent with a fresh `Portfolio(STARTING_CAPITAL)`.
  - `config_overrides` are applied to the `config` singleton for the duration of the run and restored
    on exit (context-managed), so a run is hermetic and the live `.env` is never mutated (mirrors the
    mc_backtester CLI's env save/restore).
  - Redirects `_update_picks`'s target to a temp path (or stubs it) so no live JSON is written.
- Imports agents / portfolio / config — permitted; this module is **not** `mc_backtester`.

### 5.3 `backend/agents/base_agent.py` — injectable clock (production change)
- Add `self._clock: Callable[[], datetime] | None = None` in `__init__` (default `None`).
- Add `def _now(self) -> datetime: return self._clock() if self._clock else datetime.now(timezone.utc)`.
- Replace the `datetime.now(timezone.utc)` call sites used for trail-cooldown (`_last_trail_stop_ts`
  set + `_in_trail_cooldown`) with `self._now()`.
- `HistoricalTrendsAgent.analyze` replaces `datetime.now().date()` with `self._now().date()`.
- **Default behaviour is unchanged** (`_clock is None` → `datetime.now`), covered by a regression test.
  The harness sets `agent._clock = lambda: <as_of datetime>` before each `run_cycle`.
- Scope of the change is deliberately minimal: only the time source moves behind a seam; no logic
  changes. Other agents keep working unchanged (they inherit `_now` but need not call it).

### 5.4 `scripts/reselection_backtest.py` — CLI
- Flags: `--agent HistoricalTrendsAgent`, `--start`, `--end`, `--universe live|<comma-list>`,
  `--variant "name=KEY=VAL,KEY=VAL"` (repeatable), `--min-bars` (default 30, matches the agent).
- `--universe live` = the distinct symbols the agent actually traded, read read-only from `trading.db`.
- Writes `scripts/logs/reselection_<timestamp>.md` (headline table: variant → realized PnL, final
  equity, n trades, max drawdown) and `…jsonl` (per-trade rows). Does not modify production state.

## 6. Time injection — chosen approach

Selected: the **injectable-clock refactor** (§5.3) over harness-side monkeypatching. Rationale: the
seasonal date and cooldown timing are read via `datetime.now()` deep inside agent code; patching every
call site from the harness is brittle and one missed site silently corrupts results. A single `_now()`
seam is explicit, testable, and matches the codebase's pure-function ethos. Live callers pass nothing →
identical behaviour.

## 7. Testing

| Test | Kind | Asserts |
|---|---|---|
| `test_base_agent._now` default | unit | `_clock is None` → within ~1s of real `datetime.now`; injected clock returned verbatim |
| `bars_asof` no-lookahead | unit | for a fixture symbol, no returned row has date `> as_of`; `close_asof` = last ≤ as_of |
| engine on synthetic data | unit | 2 symbols, hand-built rising/falling series → exact expected BUY/SELL trades + final cash |
| config-override hermeticity | unit | `config` restored to prior values after `run_backtest` (even on exception) |
| **acceptance / trust gate** | integration | baseline (`HIST_SEASONAL_WEIGHT=0.20`, `HIST_PREARM_STOP_PCT=0.0`, `HIST_CONFIDENCE_CAP=0.0`) over 2026-03-30→2026-07-31 on the live universe reproduces realized PnL within **±15%** of the live +$15,590.55 |

Framework: `unittest` + `run_tests.py` (pytest not installed). No live API calls, no real DB writes
(acceptance test opens `trading.db` **read-only**, only to read the universe + the live PnL target).

## 8. Acceptance gate detail (the trust gate)

The reproduction test is the **first** deliverable and gates everything downstream. If baseline PnL lands
outside ±15%, the harness is not yet trustworthy and the discrepancy must be diagnosed (likely the
daily-close bars source vs the live intraday Stooq bars, or the daily-cadence cooldown gap — see §9)
before any variant delta is reported. Only once the gate passes do we run the
`HIST_SEASONAL_WEIGHT=0`-vs-baseline A/B and log the verdict to the model-improvement ledger (Iteration
17), completing what Iteration 16 left directional.

## 9. Known fidelity caveats (documented, not hidden)

- **Daily cadence cannot reproduce the sub-day 4h trail cooldown** (`TRAIL_COOLDOWN_HOURS=4.0`) — at
  one-day spacing the cooldown always elapses, so it never binds in-backtest. Live it blocked several
  intraday cycles. Effect is on re-entry timing, not on the seasonal question directly.
- **Parquet daily-resampled close may differ slightly from the live Stooq daily bars** the agent saw.
  The reproduction gate (§8) is exactly what surfaces whether this matters.
- **Universe drift:** the live agent's tradable universe came from the scanner and varied over time; the
  backtest uses a fixed universe (the symbols actually traded). Entries on names outside that fixed set
  cannot appear — a mild conservatism on the re-selection side, acceptable for a first cut.

## 10. Risks & mitigations

- *Hidden external side effect in `run_cycle`* → audited: only `_update_picks` (file, redirected) and
  in-memory `Portfolio`; no DB. Mitigation: config-override hermeticity test + temp picks path.
- *Lookahead via an off-by-one in `bars_asof`* → dedicated no-lookahead test.
- *`run_cycle` is async* → the engine drives it with `asyncio.run`/an event loop per cycle; no shared
  loop state between cycles.
- *`RiskManager`/Kelly depend on realized history that starts empty* → acceptable and faithful: the live
  agent also began with no history; Kelly ramps as the backtest accrues trades, same as live.

## 11. Deliverable sequence (for the plan)

1. Injectable clock + regression test (production seam first, nothing depends on it breaking).
2. `BarsProvider` + no-lookahead test.
3. `run_backtest` engine + synthetic-data test + hermeticity test.
4. Acceptance/trust-gate integration test — **must pass before step 5.**
5. CLI + the seasonal A/B run → ledger Iteration 17.
