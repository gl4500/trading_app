# Re-selection Backtest Harness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a full-chassis daily backtest harness that re-runs HistoricalTrendsAgent's real `run_cycle` over historical bars, so entry-changing configs (starting with `HIST_SEASONAL_WEIGHT`) can be A/B'd on re-selected trades — closing ledger Iteration 16's realized-only blind spot.

**Architecture:** A new `backend/backtest/` package. `bars_provider.py` serves point-in-time daily bars from the offline parquet cache; `reselection.py` steps day-by-day building `market_context`/`prices` and awaiting the **real** `BaseAgent.run_cycle` (so entries + the live exit chassis are faithful). A minimal injectable-clock seam in `base_agent.py` feeds the as-of date. A CLI runs baseline-vs-variant.

**Tech Stack:** Python 3.12 (self-contained `runtime/python/python.exe`), pandas, `unittest` (pytest is NOT installed), SQLite (read-only), asyncio.

## Global Constraints

- Tests run **only** with `runtime/python/python.exe` via `unittest` — never pytest, never system Python. Command pattern (from `backend/`): `PYTHONPATH=../site-packages ../runtime/python/python.exe -m unittest tests.test_<mod> -v`.
- Tests: no live API calls, no real DB writes. The acceptance test may open `trading.db` **read-only** (`?mode=ro`) to read the live universe + live PnL target.
- **Invariant #10 preserved:** `backend/data/mc_backtester.py` and `backend/agents/xgb_decision.py` are NOT touched. The new `backend/backtest/` package MAY import agents/portfolio/config; nothing in `agents/` or `data/` may import `backend/backtest/`.
- **Default agent behavior must not change:** the injectable clock defaults to `datetime.now(timezone.utc)`; a regression test asserts this.
- Scope: **HistoricalTrendsAgent only**, **daily** close-to-close cadence, offline `backend/data/history/*.parquet` only.
- **Trust gate:** baseline config reproduces the live agent's realized PnL over 2026-03-30→2026-07-31 within **±15%** before any variant result is believed (Task 4 gates Task 5).
- Every commit passes the pre-commit security gate (secret scan + Bandit). Co-Authored-By line required.
- Work happens in worktree `C:\Users\gl450\trading_app-harness` on branch `feat/reselection-harness`.

---

### Task 1: Injectable clock seam in BaseAgent

**Files:**
- Modify: `backend/agents/base_agent.py` (add `_clock`/`_now`; swap two `datetime.now` call sites at lines ~461, ~471)
- Modify: `backend/agents/historical_trends_agent.py:383` (`datetime.now().date()` → `self._now().date()`)
- Test: `backend/tests/test_signals_and_drift.py` (append `TestInjectableClock`)

**Interfaces:**
- Produces: `BaseAgent._clock: Optional[Callable[[], datetime]]` (default `None`); `BaseAgent._now() -> datetime` (returns `self._clock()` if set, else `datetime.now(timezone.utc)`). The harness sets `agent._clock` before each cycle.

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_signals_and_drift.py`:

```python
class TestInjectableClock(unittest.TestCase):
    """The as-of clock seam the backtest harness drives. Default must be wall-clock."""

    def test_now_defaults_to_wallclock(self):
        from agents.historical_trends_agent import HistoricalTrendsAgent
        from datetime import datetime, timezone
        a = HistoricalTrendsAgent()
        self.assertIsNone(a._clock)
        delta = abs((a._now() - datetime.now(timezone.utc)).total_seconds())
        self.assertLess(delta, 2.0)

    def test_now_uses_injected_clock(self):
        from agents.historical_trends_agent import HistoricalTrendsAgent
        from datetime import datetime, timezone
        a = HistoricalTrendsAgent()
        fixed = datetime(2026, 5, 15, 21, 0, tzinfo=timezone.utc)
        a._clock = lambda: fixed
        self.assertEqual(a._now(), fixed)

    def test_seasonal_pillar_reads_injected_date(self):
        # Injecting a May date must make the seasonal reason say "May",
        # proving analyze() uses the seam and not the real calendar.
        import asyncio
        from agents.historical_trends_agent import HistoricalTrendsAgent
        from datetime import datetime, timezone
        import pandas as pd
        a = HistoricalTrendsAgent()
        a._clock = lambda: datetime(2026, 5, 15, 21, 0, tzinfo=timezone.utc)
        bars = pd.DataFrame({"close": [100.0 + i * 0.1 for i in range(40)],
                             "volume": [1000] * 40})
        ctx = {"AAA": {"price": 104.0, "long_term_bars": bars}}
        signals = asyncio.run(a.analyze(ctx))
        self.assertTrue(any("May seasonal bias" in (s.reasoning or "") for s in signals))
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && PYTHONPATH=../site-packages ../runtime/python/python.exe -m unittest tests.test_signals_and_drift.TestInjectableClock -v`
Expected: FAIL — `AttributeError: 'HistoricalTrendsAgent' object has no attribute '_clock'`.

- [ ] **Step 3: Implement the seam** in `backend/agents/base_agent.py`.

Add `Callable` to the typing import (line 12): `from typing import Deque, Dict, List, Optional, Any, Tuple, Callable`.

In `__init__` (after line 70, near `self._last_trail_stop_ts`):

```python
        # Backtest seam: when set, all decision-time "now" reads go through this.
        # Default None -> real wall clock, so live behavior is unchanged.
        self._clock: Optional[Callable[[], datetime]] = None
```

Add the method (anywhere in the class, e.g. just after `__init__`):

```python
    def _now(self) -> datetime:
        """Decision-time clock. Real wall-clock in production; the backtest
        harness injects an as-of time via ``self._clock``."""
        return self._clock() if self._clock is not None else datetime.now(timezone.utc)
```

Replace the two cooldown call sites:
- line ~461 `self._last_trail_stop_ts = datetime.now(timezone.utc)` → `self._last_trail_stop_ts = self._now()`
- line ~471 `elapsed = datetime.now(timezone.utc) - self._last_trail_stop_ts` → `elapsed = self._now() - self._last_trail_stop_ts`

In `backend/agents/historical_trends_agent.py`, `analyze` (line ~383): `today = datetime.now().date()` → `today = self._now().date()`.

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && PYTHONPATH=../site-packages ../runtime/python/python.exe -m unittest tests.test_signals_and_drift.TestInjectableClock -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Guard against regressions** — run the full base_agent test file:

Run: `cd backend && PYTHONPATH=../site-packages ../runtime/python/python.exe -m unittest tests.test_signals_and_drift -v`
Expected: PASS (no existing test broken by the seam).

- [ ] **Step 6: Commit**

```bash
git add backend/agents/base_agent.py backend/agents/historical_trends_agent.py backend/tests/test_signals_and_drift.py
git commit -m "feat(backtest): injectable clock seam in BaseAgent for as-of backtesting"
```

---

### Task 2: BarsProvider — point-in-time daily bars

**Files:**
- Create: `backend/backtest/__init__.py` (empty package marker)
- Create: `backend/backtest/bars_provider.py`
- Test: `backend/tests/test_bars_provider.py`

**Interfaces:**
- Consumes: parquet files at `backend/data/history/<SYMBOL>.parquet` with columns including `snapshot_ts` (unix seconds) and `price`, `volume`.
- Produces:
  - `BarsProvider(history_dir: Path, trailing_bars: int = 1260)`
  - `.bars_asof(symbol: str, as_of: date) -> Optional[pd.DataFrame]` — columns `close`, `volume`; ascending `DatetimeIndex`; only dates `<= as_of`; last `trailing_bars` rows; `None` if no parquet or 0 rows in range.
  - `.close_asof(symbol: str, as_of: date) -> Optional[float]` — last `close` at/before `as_of`, else `None`.
  - `.trading_days(start: date, end: date) -> list[date]` — sorted union of bar dates across all parquet symbols within `[start, end]`.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_bars_provider.py`:

```python
import unittest
import tempfile
from pathlib import Path
from datetime import date
import pandas as pd

from backtest.bars_provider import BarsProvider


def _write_parquet(dir_: Path, symbol: str, days, prices, volumes):
    ts = [pd.Timestamp(d).value // 10**9 for d in days]  # unix seconds
    pd.DataFrame({"snapshot_ts": ts, "price": prices, "volume": volumes}).to_parquet(
        dir_ / f"{symbol}.parquet")


class TestBarsProvider(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        days = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]
        _write_parquet(self.tmp, "AAA", days, [10.0, 11.0, 12.0, 13.0], [100, 100, 100, 100])
        _write_parquet(self.tmp, "BBB", ["2026-01-05", "2026-01-08"], [50.0, 55.0], [9, 9])
        self.bp = BarsProvider(self.tmp)

    def test_bars_asof_never_returns_future_rows(self):
        df = self.bp.bars_asof("AAA", date(2026, 1, 6))
        self.assertIsNotNone(df)
        self.assertEqual(list(df.columns), ["close", "volume"])
        self.assertLessEqual(df.index.max().date(), date(2026, 1, 6))
        self.assertEqual(len(df), 3)  # 01-02, 01-05, 01-06 only
        self.assertEqual(float(df["close"].iloc[-1]), 12.0)

    def test_close_asof_is_last_on_or_before(self):
        self.assertEqual(self.bp.close_asof("AAA", date(2026, 1, 6)), 12.0)
        self.assertEqual(self.bp.close_asof("AAA", date(2026, 1, 4)), 10.0)  # last <= date
        self.assertIsNone(self.bp.close_asof("AAA", date(2025, 12, 31)))

    def test_missing_symbol_returns_none(self):
        self.assertIsNone(self.bp.bars_asof("ZZZ", date(2026, 1, 6)))
        self.assertIsNone(self.bp.close_asof("ZZZ", date(2026, 1, 6)))

    def test_trading_days_is_sorted_union_in_range(self):
        days = self.bp.trading_days(date(2026, 1, 5), date(2026, 1, 7))
        self.assertEqual(days, [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)])
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && PYTHONPATH=../site-packages ../runtime/python/python.exe -m unittest tests.test_bars_provider -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backtest'`.

- [ ] **Step 3: Create the package + implementation.**

`backend/backtest/__init__.py`: empty file.

`backend/backtest/bars_provider.py`:

```python
"""Point-in-time daily bars for the re-selection backtest harness.

Reads the offline `data/history/*.parquet` snapshot cache and serves per-symbol
daily close/volume series sliced to an as-of date, with NO lookahead. The parquet
`price` column becomes daily `close` (last snapshot of the day); `volume` is that
day's last snapshot volume.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd


class BarsProvider:
    def __init__(self, history_dir: Path, trailing_bars: int = 1260):
        self._dir = Path(history_dir)
        self._trailing = trailing_bars
        self._cache: Dict[str, Optional[pd.DataFrame]] = {}

    def _daily(self, symbol: str) -> Optional[pd.DataFrame]:
        """Full daily close/volume series for a symbol (cached), ascending index."""
        if symbol not in self._cache:
            path = self._dir / f"{symbol}.parquet"
            if not path.exists():
                self._cache[symbol] = None
            else:
                raw = pd.read_parquet(path, columns=["snapshot_ts", "price", "volume"])
                raw = raw.dropna(subset=["price"])
                raw["dt"] = pd.to_datetime(raw["snapshot_ts"], unit="s")
                raw = raw.sort_values("dt")
                # Collapse to one row per calendar day: last snapshot wins.
                daily = raw.set_index("dt").resample("1D").last().dropna(subset=["price"])
                self._cache[symbol] = daily[["price", "volume"]].rename(columns={"price": "close"})
        return self._cache[symbol]

    def bars_asof(self, symbol: str, as_of: date) -> Optional[pd.DataFrame]:
        daily = self._daily(symbol)
        if daily is None:
            return None
        cutoff = pd.Timestamp(as_of) + pd.Timedelta(days=1)  # include all of as_of
        window = daily.loc[daily.index < cutoff]
        if window.empty:
            return None
        return window.iloc[-self._trailing:].copy()

    def close_asof(self, symbol: str, as_of: date) -> Optional[float]:
        window = self.bars_asof(symbol, as_of)
        if window is None or window.empty:
            return None
        return float(window["close"].iloc[-1])

    def trading_days(self, start: date, end: date) -> List[date]:
        days = set()
        for path in self._dir.glob("*.parquet"):
            symbol = path.stem
            if symbol.startswith("__"):        # skip __MACRO__ (invariant #8)
                continue
            daily = self._daily(symbol)
            if daily is None:
                continue
            for ts in daily.index:
                d = ts.date()
                if start <= d <= end:
                    days.add(d)
        return sorted(days)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && PYTHONPATH=../site-packages ../runtime/python/python.exe -m unittest tests.test_bars_provider -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/backtest/__init__.py backend/backtest/bars_provider.py backend/tests/test_bars_provider.py
git commit -m "feat(backtest): point-in-time BarsProvider from parquet cache"
```

---

### Task 3: The event-loop engine (`run_backtest`)

**Files:**
- Create: `backend/backtest/reselection.py`
- Test: `backend/tests/test_reselection.py`

**Interfaces:**
- Consumes: `BarsProvider` (Task 2); `BaseAgent` subclasses with the `_clock` seam (Task 1); the `config` singleton.
- Produces:
  - `@dataclass BacktestResult`: `realized_pnl: float`, `final_equity: float`, `equity_curve: list[tuple[date, float]]`, `trades: list[dict]`, `n_cycles: int`.
  - `async def run_backtest(agent_factory: Callable[[], BaseAgent], universe: list[str], start: date, end: date, bars: BarsProvider, config_overrides: Optional[dict] = None) -> BacktestResult`

- [ ] **Step 1: Write the failing test** — `backend/tests/test_reselection.py`. Uses a scripted stub agent to isolate the engine from HTA complexity, plus a hermeticity check.

```python
import unittest
import asyncio
from datetime import date, datetime, timezone
from typing import Dict, List

import pandas as pd

from agents.base_agent import BaseAgent, Signal
from backtest.reselection import run_backtest, BacktestResult
from config import config


class _FakeBars:
    """Rising price so a BUY on day 1 is in profit by the SELL on the last day."""
    def __init__(self, days, prices):
        self._days = days
        self._prices = dict(zip(days, prices))

    def trading_days(self, start, end):
        return [d for d in self._days if start <= d <= end]

    def close_asof(self, symbol, as_of):
        vals = [self._prices[d] for d in self._days if d <= as_of]
        return float(vals[-1]) if vals else None

    def bars_asof(self, symbol, as_of):
        rows = [(d, self._prices[d]) for d in self._days if d <= as_of]
        if not rows:
            return None
        idx = pd.to_datetime([d for d, _ in rows])
        return pd.DataFrame({"close": [p for _, p in rows], "volume": [1000] * len(rows)}, index=idx)


class _ScriptedAgent(BaseAgent):
    """BUY SYM on the first cycle, SELL it on the third. No pillars."""
    def __init__(self):
        super().__init__(name="ScriptedAgent", strategy_description="test")
        self._cycles = 0

    async def analyze(self, market_context: Dict) -> List[Signal]:
        self._cycles += 1
        if self._cycles == 1:
            return [Signal(action="BUY", symbol="SYM", confidence=0.5, shares=10,
                           reasoning="scripted buy")]
        if self._cycles == 3 and "SYM" in self.portfolio.positions:
            return [Signal(action="SELL", symbol="SYM", confidence=0.5,
                           shares=self.portfolio.positions["SYM"].shares, reasoning="scripted sell")]
        return [Signal(action="HOLD", symbol="SYM", confidence=0.0, shares=0, reasoning="hold")]


class TestRunBacktest(unittest.TestCase):
    def setUp(self):
        self.days = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
        self.bars = _FakeBars(self.days, [100.0, 110.0, 120.0])

    def test_engine_records_trades_and_realized_pnl(self):
        res = asyncio.run(run_backtest(
            _ScriptedAgent, universe=["SYM"],
            start=self.days[0], end=self.days[-1], bars=self.bars))
        self.assertIsInstance(res, BacktestResult)
        self.assertEqual(res.n_cycles, 3)
        actions = [t["action"] for t in res.trades]
        self.assertIn("BUY", actions)
        self.assertIn("SELL", actions)
        # bought 10 @ 100, sold 10 @ 120 -> +200 realized (Kelly may reduce shares;
        # assert sign + that realized equals (sell-buy)*executed_shares).
        buys = [t for t in res.trades if t["action"] == "BUY"]
        sold = [t for t in res.trades if t["action"] == "SELL"]
        expected = (sold[0]["price"] - buys[0]["price"]) * sold[0]["shares"]
        self.assertAlmostEqual(res.realized_pnl, expected, places=2)
        self.assertGreater(res.realized_pnl, 0.0)

    def test_config_overrides_are_restored(self):
        before = config.HIST_SEASONAL_WEIGHT
        asyncio.run(run_backtest(
            _ScriptedAgent, universe=["SYM"], start=self.days[0], end=self.days[-1],
            bars=self.bars, config_overrides={"HIST_SEASONAL_WEIGHT": 0.0}))
        self.assertEqual(config.HIST_SEASONAL_WEIGHT, before)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && PYTHONPATH=../site-packages ../runtime/python/python.exe -m unittest tests.test_reselection -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backtest.reselection'`.

- [ ] **Step 3: Implement the engine** — `backend/backtest/reselection.py`:

```python
"""Full-chassis daily re-selection backtest engine.

Drives the REAL BaseAgent.run_cycle once per trading day over point-in-time bars,
so both entry re-selection and the live exit chassis (trailing/hard stop, Kelly,
risk manager) are faithful. Runs on a single event loop (run_cycle holds an
asyncio.Lock, so a fresh loop per day would break). Isolates the only two side
effects: file-writing _update_picks (stubbed) and the decision clock (injected).
Never touches the database or the live .env.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from agents.base_agent import BaseAgent
from backtest.bars_provider import BarsProvider
from config import config


@dataclass
class BacktestResult:
    realized_pnl: float
    final_equity: float
    equity_curve: List[Tuple[date, float]] = field(default_factory=list)
    trades: List[dict] = field(default_factory=list)
    n_cycles: int = 0


@contextmanager
def _override_config(overrides: Dict[str, Any]):
    saved = {k: getattr(config, k) for k in overrides}
    try:
        for k, v in overrides.items():
            setattr(config, k, v)
        yield
    finally:
        for k, v in saved.items():
            setattr(config, k, v)


def _asof_clock(day: date) -> Callable[[], datetime]:
    dt = datetime(day.year, day.month, day.day, 21, 0, tzinfo=timezone.utc)  # ~after US close
    return lambda: dt


async def run_backtest(
    agent_factory: Callable[[], BaseAgent],
    universe: List[str],
    start: date,
    end: date,
    bars: BarsProvider,
    config_overrides: Optional[Dict[str, Any]] = None,
) -> BacktestResult:
    with _override_config(config_overrides or {}):
        agent = agent_factory()
        agent._is_active = True
        agent._update_picks = lambda signals: None  # isolate file I/O side effect

        trades: List[dict] = []
        equity_curve: List[Tuple[date, float]] = []

        for day in bars.trading_days(start, end):
            agent._clock = _asof_clock(day)

            held = list(agent.portfolio.positions.keys())
            prices: Dict[str, float] = {}
            market_context: Dict[str, dict] = {}
            for sym in set(universe) | set(held):
                close = bars.close_asof(sym, day)
                if close is None:
                    continue
                prices[sym] = close
                b = bars.bars_asof(sym, day)
                if b is not None:
                    market_context[sym] = {"price": close, "long_term_bars": b}

            if not market_context:
                continue

            n_before = len(agent.portfolio.trade_history)
            await agent.run_cycle(market_context, prices)
            for tr in agent.portfolio.trade_history[n_before:]:
                trades.append({
                    "date": day.isoformat(), "symbol": tr.symbol, "action": tr.action,
                    "shares": tr.shares, "price": tr.price,
                    "reasoning": tr.reasoning, "pnl": tr.pnl,
                })
            equity_curve.append((day, agent.portfolio.get_total_value(prices)))

        realized = sum(t["pnl"] for t in trades if t["action"] == "SELL")
        final_equity = equity_curve[-1][1] if equity_curve else agent.portfolio.starting_capital
        return BacktestResult(
            realized_pnl=realized, final_equity=final_equity,
            equity_curve=equity_curve, trades=trades, n_cycles=len(equity_curve),
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && PYTHONPATH=../site-packages ../runtime/python/python.exe -m unittest tests.test_reselection -v`
Expected: PASS (2 tests). If a test errors with a different-event-loop `RuntimeError`, that means `run_cycle`'s Lock crossed loops — confirm the test uses a single `asyncio.run(run_backtest(...))` (it does).

- [ ] **Step 5: Commit**

```bash
git add backend/backtest/reselection.py backend/tests/test_reselection.py
git commit -m "feat(backtest): full-chassis daily re-selection engine (run_backtest)"
```

---

### Task 4: Acceptance / trust gate — reproduce live PnL

**Files:**
- Test: `backend/tests/test_reselection_acceptance.py`

**Interfaces:**
- Consumes: `run_backtest` (Task 3), `BarsProvider` (Task 2), `HistoricalTrendsAgent`, real `backend/data/history/*.parquet`, real `backend/trading.db` (read-only).
- Produces: nothing new — this is the gate that must pass before Task 5.

- [ ] **Step 1: Write the acceptance test** — `backend/tests/test_reselection_acceptance.py`:

```python
import unittest
import asyncio
import sqlite3
from pathlib import Path
from datetime import date

from agents.historical_trends_agent import HistoricalTrendsAgent
from backtest.bars_provider import BarsProvider
from backtest.reselection import run_backtest

HISTORY = Path(__file__).resolve().parent.parent / "data" / "history"
DB = Path(__file__).resolve().parent.parent / "trading.db"


def _live_universe_and_pnl():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        syms = [r[0] for r in con.execute(
            "SELECT DISTINCT t.symbol FROM trades t JOIN agents a ON a.id=t.agent_id "
            "WHERE a.name='HistoricalTrendsAgent'")]
        pnl = con.execute(
            "SELECT COALESCE(SUM(t.pnl),0) FROM trades t JOIN agents a ON a.id=t.agent_id "
            "WHERE a.name='HistoricalTrendsAgent' AND t.action='SELL'").fetchone()[0]
        return syms, float(pnl)
    finally:
        con.close()


@unittest.skipUnless(HISTORY.exists() and DB.exists(), "requires local history cache + trading.db")
class TestReselectionAcceptance(unittest.TestCase):
    """Trust gate: baseline must reproduce the live agent's realized PnL within +/-15%."""

    def test_baseline_reproduces_live_pnl_within_15pct(self):
        universe, live_pnl = _live_universe_and_pnl()
        bars = BarsProvider(HISTORY)
        res = asyncio.run(run_backtest(
            HistoricalTrendsAgent, universe=universe,
            start=date(2026, 3, 30), end=date(2026, 7, 31), bars=bars,
            config_overrides={"HIST_SEASONAL_WEIGHT": 0.20,
                              "HIST_PREARM_STOP_PCT": 0.0,
                              "HIST_CONFIDENCE_CAP": 0.0}))
        rel = abs(res.realized_pnl - live_pnl) / abs(live_pnl)
        print(f"\n[ACCEPTANCE] live={live_pnl:,.0f}  backtest={res.realized_pnl:,.0f}  "
              f"rel_err={rel:.1%}  trades={len(res.trades)}")
        self.assertLess(rel, 0.15, f"backtest {res.realized_pnl:,.0f} vs live {live_pnl:,.0f}")
```

- [ ] **Step 2: Run the acceptance test**

Run: `cd backend && PYTHONPATH=../site-packages ../runtime/python/python.exe -m unittest tests.test_reselection_acceptance -v`
Expected outcomes:
- **PASS** → the harness is trustworthy; proceed to Task 5.
- **FAIL (rel_err too high)** → DO NOT proceed. This is the find-list-fix trigger. Diagnose in this order, most-likely first: (a) `trailing_bars` window — try widening/narrowing `BarsProvider(HISTORY, trailing_bars=...)` toward the live Stooq lookback; (b) fill convention — confirm close-to-close; (c) universe/date bounds. Record which knob closed the gap. Only a genuine, explained data-fidelity adjustment is allowed — never loosen the ±15% gate to force a pass (falsifier discipline).

- [ ] **Step 3: Commit** (commit the passing test, plus any `bars_provider.py` fidelity fix the diagnosis required)

```bash
git add backend/tests/test_reselection_acceptance.py backend/backtest/bars_provider.py
git commit -m "test(backtest): live-PnL reproduction trust gate (+/-15%)"
```

---

### Task 5: CLI + the seasonal A/B run

**Files:**
- Create: `scripts/reselection_backtest.py`
- Test: `backend/tests/test_reselection_cli.py`
- Modify: `CLAUDE.md` (add a one-line pointer under a "Backtesting" note); `docs/model_improvement_ledger.md` (Iteration 17 entry — written from the A/B output, after the run)

**Interfaces:**
- Consumes: `run_backtest`, `BarsProvider`, `HistoricalTrendsAgent`.
- Produces: `scripts/logs/reselection_<timestamp>.md` + `.jsonl`; a `main(argv)` entry importable for testing.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_reselection_cli.py` (drives the CLI over a tiny temp parquet dir so it needs no live data):

```python
import unittest
import tempfile
import sys
from pathlib import Path
import pandas as pd


def _write(dir_, sym, days, prices):
    ts = [pd.Timestamp(d).value // 10**9 for d in days]
    pd.DataFrame({"snapshot_ts": ts, "price": prices, "volume": [1000] * len(days)}).to_parquet(
        dir_ / f"{sym}.parquet")


class TestReselectionCLI(unittest.TestCase):
    def test_cli_writes_report_for_two_variants(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
        import reselection_backtest as cli
        tmp = Path(tempfile.mkdtemp())
        hist = tmp / "history"; hist.mkdir()
        logs = tmp / "logs"; logs.mkdir()
        days = [f"2026-04-{d:02d}" for d in range(1, 29)]
        _write(hist, "AAA", days, [100 + i for i in range(len(days))])
        rc = cli.main([
            "--history", str(hist), "--logs", str(logs),
            "--universe", "AAA", "--start", "2026-04-01", "--end", "2026-04-28",
            "--variant", "baseline=HIST_SEASONAL_WEIGHT=0.20",
            "--variant", "no_seasonal=HIST_SEASONAL_WEIGHT=0.0",
        ])
        self.assertEqual(rc, 0)
        reports = list(logs.glob("reselection_*.md"))
        self.assertEqual(len(reports), 1)
        text = reports[0].read_text()
        self.assertIn("baseline", text)
        self.assertIn("no_seasonal", text)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && PYTHONPATH=../site-packages ../runtime/python/python.exe -m unittest tests.test_reselection_cli -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'reselection_backtest'`.

- [ ] **Step 3: Implement the CLI** — `scripts/reselection_backtest.py`:

```python
"""CLI for the re-selection backtest harness (ledger Iteration 17).

Runs one or more config variants of a rule agent over historical bars and writes
a comparison report. Does not modify production state.

Example:
    PYTHONPATH='site-packages;backend' runtime/python/python.exe scripts/reselection_backtest.py \\
      --universe live --start 2026-03-30 --end 2026-07-31 \\
      --variant "baseline=HIST_SEASONAL_WEIGHT=0.20" \\
      --variant "no_seasonal=HIST_SEASONAL_WEIGHT=0.0"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from agents.historical_trends_agent import HistoricalTrendsAgent
from backtest.bars_provider import BarsProvider
from backtest.reselection import run_backtest, BacktestResult

_ROOT = Path(__file__).resolve().parent.parent
_AGENTS = {"HistoricalTrendsAgent": HistoricalTrendsAgent}


def _parse_variant(spec: str):
    name, _, rest = spec.partition("=")
    overrides: Dict[str, float] = {}
    for pair in rest.split(","):
        k, _, v = pair.partition("=")
        overrides[k.strip()] = float(v)
    return name.strip(), overrides


def _live_universe(db: Path, agent_name: str) -> List[str]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT t.symbol FROM trades t JOIN agents a ON a.id=t.agent_id "
            "WHERE a.name=?", (agent_name,))]
    finally:
        con.close()


def _max_drawdown(curve) -> float:
    peak = float("-inf"); mdd = 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return mdd


def _iso(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--agent", default="HistoricalTrendsAgent", choices=list(_AGENTS))
    p.add_argument("--history", default=str(_ROOT / "backend" / "data" / "history"))
    p.add_argument("--logs", default=str(_ROOT / "scripts" / "logs"))
    p.add_argument("--db", default=str(_ROOT / "backend" / "trading.db"))
    p.add_argument("--universe", required=True, help='"live" or a comma-separated symbol list')
    p.add_argument("--start", required=True, type=_iso)
    p.add_argument("--end", required=True, type=_iso)
    p.add_argument("--variant", action="append", required=True, help='"name=KEY=VAL,KEY=VAL"')
    p.add_argument("--trailing-bars", type=int, default=1260)
    args = p.parse_args(argv)

    universe = (_live_universe(Path(args.db), args.agent)
                if args.universe == "live" else
                [s.strip() for s in args.universe.split(",") if s.strip()])
    bars = BarsProvider(Path(args.history), trailing_bars=args.trailing_bars)
    factory = _AGENTS[args.agent]

    results: Dict[str, BacktestResult] = {}
    for spec in args.variant:
        name, overrides = _parse_variant(spec)
        results[name] = asyncio.run(run_backtest(
            factory, universe=universe, start=args.start, end=args.end,
            bars=bars, config_overrides=overrides))

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logs = Path(args.logs); logs.mkdir(parents=True, exist_ok=True)
    md = logs / f"reselection_{ts}.md"
    jl = logs / f"reselection_{ts}.jsonl"

    lines = [f"# Re-selection backtest {ts}",
             f"agent={args.agent} universe={len(universe)} syms  {args.start}->{args.end}", "",
             "| variant | realized PnL | final equity | trades | max DD |",
             "|---|---|---|---|---|"]
    for name, r in results.items():
        lines.append(f"| {name} | {r.realized_pnl:,.0f} | {r.final_equity:,.0f} | "
                     f"{len(r.trades)} | {_max_drawdown(r.equity_curve):.1%} |")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with jl.open("w", encoding="utf-8") as f:
        for name, r in results.items():
            for t in r.trades:
                f.write(json.dumps({"variant": name, **t}) + "\n")

    print(f"wrote {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && PYTHONPATH=../site-packages ../runtime/python/python.exe -m unittest tests.test_reselection_cli -v`
Expected: PASS.

- [ ] **Step 5: Run the real seasonal A/B** (only after Task 4's gate is green):

Run: `PYTHONPATH='site-packages;backend' runtime/python/python.exe scripts/reselection_backtest.py --universe live --start 2026-03-30 --end 2026-07-31 --variant "baseline=HIST_SEASONAL_WEIGHT=0.20" --variant "no_seasonal=HIST_SEASONAL_WEIGHT=0.0"`
Expected: writes `scripts/logs/reselection_<ts>.md` with a baseline vs no_seasonal PnL comparison — the signed delta Iteration 16 could not measure.

- [ ] **Step 6: Document + ledger.** Add a "Backtesting" pointer line to `CLAUDE.md` (next to the mc_backtester note) referencing `scripts/reselection_backtest.py` and this spec. Append **Iteration 17** to `docs/model_improvement_ledger.md` recording the seasonal A/B verdict (SUPPORTED if `no_seasonal` beats baseline materially and robustly; REJECTED otherwise — pre-register the same falsifier discipline). Update the `trading_app_model_improvement_ledger` memory in the same step (sync rule).

- [ ] **Step 7: Commit**

```bash
git add scripts/reselection_backtest.py backend/tests/test_reselection_cli.py CLAUDE.md docs/model_improvement_ledger.md
git commit -m "feat(backtest): re-selection CLI + Iteration 17 seasonal A/B"
```

---

## Self-Review

**Spec coverage:** §4 event loop → Task 3; §5.1 BarsProvider → Task 2; §5.2 engine → Task 3; §5.3 clock → Task 1; §5.4 CLI → Task 5; §7 tests → Tasks 1–5; §8 trust gate → Task 4; §11 sequence → Tasks 1→5 in order. All covered.

**Placeholder scan:** every code step has complete, runnable code; every run step has an exact command + expected result. No TBDs.

**Type consistency:** `BarsProvider.bars_asof/close_asof/trading_days` signatures identical across Tasks 2–5; `run_backtest(agent_factory, universe, start, end, bars, config_overrides)` and `BacktestResult(realized_pnl, final_equity, equity_curve, trades, n_cycles)` identical across Tasks 3–5; `_clock`/`_now` from Task 1 used by Task 3's engine. Consistent.
