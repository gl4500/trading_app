"""Feature catalog — single source of truth for every model channel.

Per docs/feature_engineering_pipeline.md Stage 3:
    "Maintain a registry — a single source of truth listing every feature,
     its dependencies, its computation function, and metadata."

Adding a new feature = one CATALOG entry + one helper in signal_history
(or a derived stage in compute_features). Removing one = remove the entry,
and the cross-file consistency test will fail loudly until any other
references are also dropped.

cnn_model.ALL_CHANNEL_COLUMNS is derived from this list at module import,
so the catalog is the canonical order — what's here, in this order, is
what build_training_windows / get_recent_window / SignalXGBoost see.

Categories (used for grouping in build_training_windows feat_cols):
    SOURCE   — exogenous score channels (analyst, news, options-derived)
    AGENT    — derived from other agents' decisions
    RV       — realized volatility (computed at write-time)
    RETURN   — lagged log returns (computed at read-time by
               _compute_return_features). Names are CURRENTLY misleading:
               r_120 is 120 hourly snapshots ≈ 20 trading days, NOT 120 days.
               Sprint 0 will add daily-resampled siblings and rename
               existing entries with an _h suffix.
    MACRO    — joined as-of from __MACRO__.parquet
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Channel:
    name: str           # column name in df (must match signal_history's persistence)
    category: str       # SOURCE | AGENT | RV | RETURN | MACRO
    inputs: List[str]   # raw data sources feeding this channel
    computation: str    # where it's computed (function or pipeline stage)
    horizon: str        # what time scale the channel operates on
    added: str          # ISO date the channel landed in production
    notes: str          # provenance, gotchas, current status


CATALOG: List[Channel] = [
    # ── SOURCE (5) ────────────────────────────────────────────────────────
    Channel(
        "analyst_score", "SOURCE",
        ["yfinance.recommendations"],
        "signal_aggregator.score_analyst",
        "snapshot", "2026-03-15",
        "Recommendation key strongBuy/buy/hold/etc weighted to [-1, +1]. In production XGB filter.",
    ),
    Channel(
        "earnings_score", "SOURCE",
        ["yfinance.earnings_history"],
        "signal_aggregator.score_earnings_surprise",
        "snapshot", "2026-03-15",
        "Earnings surprise %. CNN/XGB consumer takes |abs| in _apply_cnn_feature_transforms (Task #22). In production XGB filter.",
    ),
    Channel(
        "alpaca_score", "SOURCE",
        ["alpaca news API"],
        "news_service + keyword scoring",
        "snapshot", "2026-03-15",
        "News-sentiment composite, [-1, +1]. In production XGB filter.",
    ),
    Channel(
        "yahoo_score", "SOURCE",
        ["yfinance news"],
        "finbert_scorer",
        "snapshot", "2026-04-22",
        "FinBERT applied to Yahoo headlines (Task #21). NOT in production XGB filter (forward-selection dropped it).",
    ),
    Channel(
        "iv_rv_score", "SOURCE",
        ["yfinance options"],
        "signal_aggregator.iv_rv_spread",
        "snapshot", "2026-04-15",
        "ATM IV minus rv_20d, scored to [-1, +1]. In production XGB filter.",
    ),

    # ── AGENT (2) ─────────────────────────────────────────────────────────
    Channel(
        "agent_consensus", "AGENT",
        ["agent_signals"],
        "signal_history.record_agent_signals",
        "snapshot", "2026-04-10",
        "Performance-weighted vote of all agents [-1, +1]. NOT in production XGB filter.",
    ),
    Channel(
        "agent_agreement", "AGENT",
        ["agent_signals"],
        "signal_history.record_agent_signals",
        "snapshot", "2026-04-10",
        "Fraction of agents that agree [0, 1]. NOT in production XGB filter.",
    ),

    # ── RV (2) ────────────────────────────────────────────────────────────
    Channel(
        "rv_20d", "RV",
        ["price"],
        "_rolling_rv (20-day window)",
        "20-day rolling", "2026-04-12",
        "20-day annualized realized vol. NOT in production XGB filter.",
    ),
    Channel(
        "rv_60d", "RV",
        ["price"],
        "_rolling_rv (60-day window)",
        "60-day rolling", "2026-04-12",
        "60-day annualized realized vol. NOT in production XGB filter.",
    ),

    # ── RETURN (5) ────────────────────────────────────────────────────────
    # Tier 1 from docs/equity_feature_engineering_audit.md (2026-05-02).
    # CAVEAT: names suggest days but these are hourly-snapshot row-shifts.
    # Sprint 0 will add daily-resampled siblings (r_*d) and rename these
    # to r_*h once the rename branch lands.
    Channel(
        "r_1", "RETURN",
        ["price"],
        "_compute_return_features (groupby symbol, shift 1)",
        "1 snapshot ≈ 1 hour", "2026-05-02",
        "Misleading name. NOT in production XGB filter.",
    ),
    Channel(
        "r_5", "RETURN",
        ["price"],
        "_compute_return_features (shift 5)",
        "5 snapshots ≈ 1 trading day", "2026-05-02",
        "Misleading name. NOT in production XGB filter.",
    ),
    Channel(
        "r_20", "RETURN",
        ["price"],
        "_compute_return_features (shift 20)",
        "20 snapshots ≈ 4 trading days", "2026-05-02",
        "Misleading name. NOT in production XGB filter.",
    ),
    Channel(
        "r_60", "RETURN",
        ["price"],
        "_compute_return_features (shift 60)",
        "60 snapshots ≈ 10 trading days", "2026-05-02",
        "Misleading name. NOT in production XGB filter.",
    ),
    Channel(
        "r_120", "RETURN",
        ["price"],
        "_compute_return_features (shift 120)",
        "120 snapshots ≈ 20 trading days", "2026-05-02",
        "Misleading name (≈ 1 month, not 6 months). IN production XGB filter — strongest single momentum signal in the live model.",
    ),

    # ── MACRO (5) ─────────────────────────────────────────────────────────
    # Joined as-of from __MACRO__.parquet by signal_history._attach_macro_features.
    # _back suffix marks Task #24's trailing-window fix (was forward-leaking).
    Channel(
        "macro_vix_norm", "MACRO",
        ["VIX index"],
        "macro_history.compute_features (VIX/30, clipped [0, 3])",
        "snapshot (current VIX)", "2026-04-21",
        "VIX/30 normalized. IN production XGB filter.",
    ),
    Channel(
        "macro_gld_5d_back", "MACRO",
        ["GLD daily close"],
        "macro_history._ret_nd_trailing (5-day TRAILING)",
        "5-day trailing", "2026-04-24",
        "GLD 5d trailing return. NOT in production XGB filter.",
    ),
    Channel(
        "macro_tlt_5d_back", "MACRO",
        ["TLT daily close"],
        "macro_history._ret_nd_trailing (5-day TRAILING)",
        "5-day trailing", "2026-04-24",
        "TLT 5d trailing return. NOT in production XGB filter.",
    ),
    Channel(
        "macro_spy_5d_back", "MACRO",
        ["SPY daily close"],
        "macro_history._ret_nd_trailing (5-day TRAILING)",
        "5-day trailing", "2026-04-24",
        "SPY 5d trailing return. IN production XGB filter — proxies market-direction signal.",
    ),
    Channel(
        "macro_breadth_back", "MACRO",
        ["IWM, SPY daily closes"],
        "macro_history._breadth_score_back (5-day trailing IWM-SPY spread)",
        "5-day trailing", "2026-04-24",
        "(IWM - SPY) trailing 5d, clipped [-1, 1]. IN production XGB filter.",
    ),

    # ── RETURN_DAILY (6) ──────────────────────────────────────────────────
    # Sprint 0 (2026-05-03): true daily-resampled lagged returns. Where the
    # RETURN block above operates on hourly snapshots (r_120 ≈ 20 trading
    # days), these operate on daily-resampled prices (r_120d = exactly 120
    # trading days = ~6 months back). Computed at read-time via per-symbol
    # df.resample('1D').last() then groupby.shift, then forward-filled to
    # the original hourly cadence.
    #
    # Placed AFTER MACRO so existing channel indices 0-18 are preserved —
    # the production XGB feature_filter [0,1,2,4,13,14,17,18] keeps
    # pointing at the same channels. New channels are pool-only until a
    # forward-selection re-run promotes them.
    Channel(
        "r_1d", "RETURN_DAILY",
        ["price"],
        "_compute_daily_return_features (daily-resampled, shift 1d)",
        "1 trading day", "2026-05-03",
        "True daily 1-day return. Distinct from r_5 (hourly) which is ~1 trading day on the hourly grid but uses last snapshot's price not session close.",
    ),
    Channel(
        "r_5d", "RETURN_DAILY",
        ["price"],
        "_compute_daily_return_features (shift 5d)",
        "5 trading days", "2026-05-03",
        "True 1-week return.",
    ),
    Channel(
        "r_20d", "RETURN_DAILY",
        ["price"],
        "_compute_daily_return_features (shift 20d)",
        "20 trading days", "2026-05-03",
        "True 1-month return.",
    ),
    Channel(
        "r_60d", "RETURN_DAILY",
        ["price"],
        "_compute_daily_return_features (shift 60d)",
        "60 trading days", "2026-05-03",
        "True 3-month return.",
    ),
    Channel(
        "r_120d", "RETURN_DAILY",
        ["price"],
        "_compute_daily_return_features (shift 120d)",
        "120 trading days", "2026-05-03",
        "True 6-month return — the lookback the equity audit doc actually means by 'momentum'.",
    ),
    Channel(
        "r_252d", "RETURN_DAILY",
        ["price"],
        "_compute_daily_return_features (shift 252d)",
        "252 trading days", "2026-05-03",
        "True 12-month return. Required for r_252d - r_21d 12-1 momentum (Sprint 2-B). Most rows will be NaN until ~12 months of history accumulates per symbol.",
    ),

    # ── MOMENTUM (1) ──────────────────────────────────────────────────────
    # Sprint 2-B (2026-05-08): the classic Jegadeesh-Titman 12-1 momentum
    # factor — cumulative log-return from t-12mo to t-1mo, skipping the
    # most recent month to avoid short-term reversal contamination. Pure
    # subtraction of two RETURN_DAILY channels: r_252d - r_20d (we use 20
    # trading days as the "1-month skip" since that's what the catalog
    # exposes; ≈ 1 month).
    #
    # Placed AFTER RETURN_DAILY so the production XGB feature_filter
    # [0,1,2,4,13,14,17,18] (all indices ≤ 18) keeps pointing at the same
    # channels. Pool-only until Task #74 re-runs forward selection.
    Channel(
        "mom_12_1", "MOMENTUM",
        ["r_252d", "r_20d"],
        "_compute_momentum_features (r_252d - r_20d)",
        "12 months minus last month", "2026-05-08",
        "12-1 momentum: r_252d - r_20d in log-return space = log(P[t-20]/P[t-252]). NaN until both inputs are populated (~12 months of per-symbol history).",
    ),

    # ── SECTOR_RELATIVE (1) ──────────────────────────────────────────────
    # Sprint 3 (2026-05-08): cross-sectional sector-relative 1-month return.
    # For each row (symbol, ts) → r_20d_sector_rel = symbol's r_20d minus
    # the symbol-equal-weight mean of r_20d across ALL symbols in the same
    # GICS sector on the same UTC trading day. Captures relative-strength
    # information that single-symbol channels structurally cannot — e.g.
    # the entire Energy sector up 5% on an oil day looks like a non-event
    # in r_20d_sector_rel but a clear factor exposure in r_20d.
    #
    # Symbol-equal-weight: dedupe to one r_20d per (symbol, trading_day)
    # before averaging, so a symbol with more hourly snapshots doesn't
    # dominate the sector mean.
    #
    # Placed AFTER MOMENTUM so existing channel indices [0-25] are
    # preserved — production XGB feature_filter [0,1,2,4,13,14,17,18]
    # remains valid. r_20d_sector_rel lands at index 26.
    Channel(
        "r_20d_sector_rel", "SECTOR_RELATIVE",
        ["r_20d", "GICS sector mapping (yfinance-cached)"],
        "_compute_sector_relative_features (r_20d - sector-day mean of r_20d)",
        "20 trading days, cross-sectional", "2026-05-08",
        "Sector-relative 1-month return. r_20d minus same-sector same-day equal-weighted mean. Sprint 0's r_20d - cross-section. NaN when r_20d is NaN; 0 when symbol is the only valid sample in its sector that day.",
    ),
]


# ── Convenience accessors ─────────────────────────────────────────────────

def channel_names() -> List[str]:
    """Ordered list of all channel column names — drop-in replacement for
    cnn_model.ALL_CHANNEL_COLUMNS."""
    return [c.name for c in CATALOG]


def channels_by_category(category: str) -> List[Channel]:
    """Return all channels in a given category (SOURCE/AGENT/RV/RETURN/MACRO)."""
    return [c for c in CATALOG if c.category == category]


def find(name: str) -> Channel:
    """Look up a channel by name. Raises KeyError if not found."""
    for c in CATALOG:
        if c.name == name:
            return c
    raise KeyError(f"channel '{name}' not in catalog. Known: {channel_names()}")


# ── Production XGB filter (single-source-of-truth for the 8-channel set) ──
# Used by data/xgboost_model.py:_parse_feature_filter when XGB_FEATURE_FILTER
# env is empty AND a future change wants to default to the production set.
# Currently the env is the source of truth; this constant is for documentation
# and for tests to assert the production set is a subset of CATALOG.
PRODUCTION_XGB_FILTER: List[str] = [
    "analyst_score", "earnings_score", "alpaca_score", "iv_rv_score",
    "r_120",
    "macro_vix_norm", "macro_spy_5d_back", "macro_breadth_back",
]
