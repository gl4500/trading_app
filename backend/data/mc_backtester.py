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
            # Note: block.loc[block_dates] returns rows in source-date order;
            # we re-key to synthetic_dates while preserving (date, symbol) shape
            block = block.reset_index()
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


# ─────────────────────────────────────────────────────────────────────────────
# Backtest portfolio + stripped agent (in-memory, no DB, no file I/O)
# ─────────────────────────────────────────────────────────────────────────────

from typing import Dict  # noqa: E402

from trading.portfolio import Portfolio  # noqa: E402
from agents.base_agent import BaseAgent  # noqa: E402


class BacktestPortfolio(Portfolio):
    """In-memory Portfolio for backtesting.

    Inherits the full Portfolio public surface (cash, positions,
    trade_history, kelly_fraction, execute_buy, execute_sell,
    record_value, unpnl_frac, _position_peak_unrealized, etc.) — no override
    needed for any of those. The 'no DB/file I/O' guarantee comes from the
    fact that Portfolio itself doesn't do DB writes — those happen in
    BaseAgent and database.py, neither of which we touch here.

    Adds a thin `total_value(prices)` alias for `get_total_value(prices)`
    so the replay loop and tests can use the shorter name.
    """

    def __init__(self, starting_capital: float = 100000.0):
        super().__init__(starting_capital=starting_capital)

    def total_value(self, prices: Dict[str, float]) -> float:
        """Alias for Portfolio.get_total_value — shorter name used by replay loop."""
        return self.get_total_value(prices)


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
                 portfolio_override: Optional["BacktestPortfolio"] = None):
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


# ─────────────────────────────────────────────────────────────────────────────
# Replay loop
# ─────────────────────────────────────────────────────────────────────────────

import math  # noqa: E402
from typing import Any  # noqa: E402

from config import config as _DEFAULT_CONFIG  # noqa: E402
from data.regime_detector import RegimeDetector  # noqa: E402
from agents.cnn_decision import BuyContext, decide_buy  # noqa: E402


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


def _annualised_sharpe(daily_values: List[float]) -> float:
    """Annualised Sharpe of the daily-value series. 0.0 if undefined."""
    if len(daily_values) < 2:
        return 0.0
    returns = np.diff(np.asarray(daily_values, dtype=np.float64)) / np.asarray(daily_values[:-1])
    if returns.std() == 0:
        return 0.0
    return float(returns.mean() / returns.std() * math.sqrt(252))


def _max_drawdown(daily_values: List[float]) -> float:
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
    daily_values: List[float] = []

    # Fresh regime detector per path — no state leakage across simulations.
    # RegimeDetector.update() REPLACES its internal price list, so we must
    # accumulate SPY prices across days and feed the cumulative list each
    # cycle — otherwise the detector never sees the 21+ prices it needs to
    # classify a non-neutral regime, silently disabling the regime gate.
    regime_detector = RegimeDetector()
    spy_history: List[float] = []

    # T (CNN window length) — kept in sync with data.cnn_model.WINDOW_SIZE.
    # Hard-coded here to avoid pulling cnn_model into the backtester's import
    # graph (cnn_decision contract: pure helpers, no model imports).
    T = 10

    # Vocabulary translation: SignalXGBoost.predict returns "bull|bear|neutral",
    # but decide_buy's Gate 1 contract is Literal["up","down","neutral"].
    # Production CNNReasoningAgent dodges this by hard-coding "up" (Ollama has
    # already approved BUY by then). The backtester has no Ollama, so we
    # translate at the consumer boundary and keep decide_buy semantically pure.
    # The map also passes through "up"/"down"/"neutral" unchanged so test
    # fixtures (_FakeModel) using either vocabulary work correctly.
    _DIRECTION_MAP = {
        "bull": "up", "bear": "down", "neutral": "neutral",
        "up": "up", "down": "down",
    }

    dates = sorted(path.index.get_level_values(0).unique())
    for day_idx, date in enumerate(dates):
        day_rows = path.xs(date, level=0)
        prices = day_rows["price"].to_dict()

        # Feed cumulative SPY prices to regime detector (update() replaces
        # the internal list each call — see comment above).
        if "SPY" in prices:
            spy_history.append(prices["SPY"])
            regime_detector.update(spy_history)
        regime = regime_detector.get_regime()[0] if day_idx > 20 else "neutral"

        portfolio.record_value(prices)

        # ── SELL pass ─────────────────────────────────────────────────────
        sell_signals = (await agent._check_bayes_exits(prices)) + \
                       (await agent._check_trailing_stops(prices)) + \
                       (await agent._check_hard_stops(prices))
        for sig in sell_signals:
            portfolio.execute_sell(sig.symbol, sig.shares, prices[sig.symbol], sig.reasoning)

        # ── BUY pass ──────────────────────────────────────────────────────
        # Build a proper (C, T) window per symbol from the last T days of the
        # path. SignalXGBoost.predict shape-guards on `x.shape[0] != n_channels`
        # — a 1D row vector silently returns (0.0, "neutral", 0.0), blocking
        # every BUY. We slice path.xs(symbol, level=1) over the last T dates
        # and transpose so axis-0 is channels (matches build_training_windows).
        end_idx = day_idx + 1
        start_idx = max(0, end_idx - T)
        hist_dates = dates[start_idx:end_idx]
        if len(hist_dates) < T:
            # Not enough history yet — skip BUY pass on this day for all symbols.
            # Production behaviour: get_recent_window returns None < 3 snapshots;
            # we use the stricter T-snapshot floor to match build_training_windows.
            daily_values.append(portfolio.get_total_value(prices))
            continue

        for symbol in day_rows.index:
            price = float(prices.get(symbol, 0.0))
            if price <= 0:
                continue
            # Extract this symbol's rows over the last T dates → (T rows × channels)
            try:
                sym_history = path.xs(symbol, level=1).loc[hist_dates]
            except KeyError:
                # Symbol missing on one of the historical dates — skip this BUY.
                continue
            if len(sym_history) < T:
                continue
            # Transpose to (C, T) — matches cnn_model.build_training_windows output.
            window = sym_history.values.T
            pred_ret, raw_direction, conf = model.predict(window)
            direction_for_gate = _DIRECTION_MAP.get(
                str(raw_direction).lower(), "neutral",
            )
            ctx = BuyContext(
                symbol=symbol,
                cnn_pred_return=float(pred_ret),
                cnn_pred_direction=direction_for_gate,
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


# ─────────────────────────────────────────────────────────────────────────────
# Aggregation + report writers
# ─────────────────────────────────────────────────────────────────────────────

import json  # noqa: E402
from dataclasses import asdict  # noqa: E402


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
