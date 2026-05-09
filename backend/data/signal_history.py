"""
Parquet-backed store for composite signal snapshots and their future price outcomes.

Each symbol gets its own compressed Parquet file under data/history/.
Snapshots are recorded on every market data cycle; outcomes (1D / 5D returns)
are filled in lazily once the target time has elapsed.

This data drives the CNN weight learner in data/cnn_model.py.
"""
import asyncio
import logging
import os
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── paths ─────────────────────────────────────────────────────────────────────

_HISTORY_DIR    = os.path.join(os.path.dirname(__file__), "history")
_MACRO_FILENAME = "__MACRO__.parquet"

# As-of join tolerance for the macro merge: 4 days covers long weekends + holidays.
_MACRO_AS_OF_TOLERANCE_SECS = 4 * 86_400

# Mapping from __MACRO__.parquet columns → CNN macro channel names.
# Defined locally (not imported from cnn_model) to keep signal_history independent
# of the CNN module — cnn_model already imports from this file.
_MACRO_COLUMN_MAP: Dict[str, str] = {
    "vix_norm":           "macro_vix_norm",
    # Task #24: 5d columns are now TRAILING (was forward) — `_back` suffix
    # documents the lookahead-leak fix and forces re-backfill.
    "gld_5d_back":        "macro_gld_5d_back",
    "tlt_5d_back":        "macro_tlt_5d_back",
    "spy_5d_back":        "macro_spy_5d_back",
    "breadth_score_back": "macro_breadth_back",
    # 2026-05-09 (#84): DJIA via DIA ETF, appended at end so existing
    # MACRO indices [14-18] are preserved for the production XGB filter.
    "dji_5d_back":        "macro_dji_5d_back",
}

# Source score column names (order must match cnn_model.SOURCE_NAMES)
# Task #20: congress_score dropped from CNN training inputs (3% coverage,
# corr -0.001). The column is still persisted by record_snapshot — see
# _DTYPE_MAP — and shown to the LLM for catalyst-style context.
SOURCE_COLUMNS = [
    "analyst_score",
    "earnings_score",
    "alpaca_score",
    "yahoo_score",
    "iv_rv_score",     # IV minus RV_20d spread, scored to [-1, +1]
]

_DTYPE_MAP = {
    "symbol":            "object",
    "snapshot_ts":       "float64",
    "analyst_score":     "float64",
    "earnings_score":    "float64",
    "alpaca_score":      "float64",
    "yahoo_score":       "float64",
    "congress_score":    "float64",
    "iv_rv_score":       "float64",  # IV/RV spread score [-1, +1]; NaN when options unavailable
    "composite_score":   "float64",
    "price":             "float64",
    "return_1d":         "float64",
    "return_5d":         "float64",
    "return_10d":        "float64",
    # Agent consensus columns — filled after agents run each cycle
    "agent_consensus":   "float64",  # -1.0 to +1.0 performance-weighted vote
    "agent_agreement":   "float64",  # 0.0 to 1.0 fraction of agents that agree
    "top_agent_correct": "float64",  # NaN until 24h later; 1.0 = top agent was right
    # Realized volatility channels (annualized, 252-day basis)
    "rv_20d":            "float64",  # 20-day rolling realized vol
    "rv_60d":            "float64",  # 60-day rolling realized vol
    # 2026-05-09 (#85): per-bar trading volume. Populated by
    # _bars_to_backfill_rows during historical backfill (from Alpaca OHLCV);
    # live record_snapshot writes NaN unless caller passes a value. Used by
    # hist_volume_pattern channel (option C) — graceful 0 when NaN.
    "volume":            "float64",
}

# Agent feature columns used as extra CNN input channels
AGENT_COLUMNS = ["agent_consensus", "agent_agreement"]

# Realized volatility columns — CNN channels 8 & 9
RV_COLUMNS = ["rv_20d", "rv_60d"]

# Lagged log-return columns — augmented at read time by _compute_return_features
# from the per-symbol `price` column. Order matters: must match
# cnn_model.RETURN_CHANNEL_NAMES.
RETURN_COLUMNS = ["r_1", "r_5", "r_20", "r_60", "r_120"]

# Sprint 0 (2026-05-03): daily-resampled lagged returns. Where RETURN_COLUMNS
# above operates on the raw hourly snapshot grid (r_120 ≈ 20 trading days),
# DAILY_RETURN_COLUMNS operates on per-symbol daily-resampled prices
# (r_120d = exactly 120 trading days). Computed at read time by
# _compute_daily_return_features and forward-filled back to the original
# hourly cadence so each snapshot in a day shares that day's return value.
DAILY_RETURN_COLUMNS = ["r_1d", "r_5d", "r_20d", "r_60d", "r_120d", "r_252d"]

# MOMENTUM_COLUMNS holds derived momentum factors computed from RETURN_DAILY
# channels at read-time (Sprint 2-B 2026-05-08). Currently mom_12_1 only —
# the classic Jegadeesh-Titman 12-1 factor, computed as r_252d - r_20d.
MOMENTUM_COLUMNS = ["mom_12_1"]

# SECTOR_RELATIVE_COLUMNS holds cross-sectional features computed by
# joining a sector lookup and grouping over (sector, trading_day) at
# read-time (Sprint 3 2026-05-08). Currently r_20d_sector_rel only —
# the symbol's r_20d minus the symbol-equal-weight mean of r_20d across
# all symbols in the same GICS sector on the same UTC trading day.
SECTOR_RELATIVE_COLUMNS = ["r_20d_sector_rel"]

# SPY_CORRELATION_COLUMNS holds inter-asset comovement features computed
# by joining each symbol's daily returns against SPY's daily returns and
# rolling over a window (Sprint 4 2026-05-08). Currently corr_spy_20d
# only — Pearson correlation of the last 20 paired daily r_1d values.
SPY_CORRELATION_COLUMNS = ["corr_spy_20d"]

# HISTORICAL_COLUMNS imports HistoricalTrendsAgent's 4 sub-scores into
# XGB as features (2026-05-09, option C). Same math as
# agents/historical_trends_agent.py, computed at read-time over the
# per-symbol price series. XGB can then learn its own non-linear
# weights for each — sidesteps HT's hand-tuned 20/30/40/10 weighting
# and lets the model fit how each signal interacts with the existing 8
# production-filter channels.
#
# The four sub-scores:
#   hist_seasonal             — month-of-year + quarter-position bias
#   hist_channel_position     — price position within 60-day high-low range
#   hist_momentum_alignment   — multi-period (5d/10d/20d/40d) ROC + alignment bonus
#   hist_volume_pattern       — up-day vs down-day volume ratio (capped ±0.15)
#
# Volume channel gracefully degrades to 0 when `volume` column is absent
# from the parquet (current state on most rows — see Task #85 for backfill).
HISTORICAL_COLUMNS = [
    "hist_seasonal",
    "hist_channel_position",
    "hist_momentum_alignment",
    "hist_volume_pattern",
]


# HistoricalTrends seasonal table — copy of MONTHLY_SEASONAL_BIAS from
# agents/historical_trends_agent.py. Duplicated rather than imported so
# the read-time pipeline doesn't pull in a circular agent dependency
# and so the catalog stays self-contained.
_HIST_MONTH_BIAS = {
    1: +0.40, 2: +0.10, 3: +0.10, 4: +0.20, 5: -0.20, 6: -0.15,
    7: +0.05, 8: -0.15, 9: -0.30, 10: +0.10, 11: +0.35, 12: +0.40,
}


def _hist_quarter_bias(month: int, day: int) -> float:
    """Same logic as historical_trends_agent._quarter_position_bias."""
    month_in_quarter = ((month - 1) % 3) + 1
    if month_in_quarter == 3 and day >= 15:
        return +0.15   # last ~6 weeks of quarter — window dressing
    elif month_in_quarter == 1 and day <= 15:
        return +0.10   # first two weeks of new quarter — fresh positioning
    return 0.0


def _compute_historical_features(df: pd.DataFrame) -> pd.DataFrame:
    """2026-05-09 (option C): import HistoricalTrendsAgent's four sub-scores
    as XGB feature channels. Math mirrors
    agents/historical_trends_agent.py exactly so XGB sees the SAME signal
    HT votes on, but as features it can combine non-linearly with its
    other 8 production-filter channels.

    Returns a fresh frame; caller's df is unchanged. Robustness: missing
    `price` column → return df untouched. Missing `volume` column →
    hist_volume_pattern = 0 (graceful degrade until Task #85 backfills).

    Per-row computation: each row gets sub-scores computed over the
    price series UP TO (and including) that row — so the values are
    lookahead-free and represent what HT would have voted at that
    snapshot.
    """
    if df.empty:
        return df
    if "price" not in df.columns or "snapshot_ts" not in df.columns:
        return df

    out = df.copy()
    n = len(out)

    # Allocate output arrays
    seasonal_arr = np.zeros(n, dtype=np.float64)
    channel_arr  = np.zeros(n, dtype=np.float64)
    momentum_arr = np.zeros(n, dtype=np.float64)
    volume_arr   = np.zeros(n, dtype=np.float64)

    has_volume = "volume" in out.columns
    price_series = out["price"].astype(float).values
    ts_series    = out["snapshot_ts"].astype(float).values
    if has_volume:
        vol_series = out["volume"].astype(float).values

    # Per-row scoring. Computes lookback-only signals for row i using
    # the slice [0:i+1] of the price/volume series. Since the snapshot
    # cadence is hourly, we use 60 hourly bars as the "channel window"
    # (≈ 12 trading days at 5 sessions/week × 5 hours each — enough
    # history for the channel signal to stabilise).
    CHANNEL_WIN  = 60     # rows used for high/low channel
    MOMENTUM_PS  = (5, 10, 20, 40)
    MOMENTUM_WS  = (0.15, 0.20, 0.30, 0.35)
    SMA_WIN      = 20
    SMA_LOOKBACK = 10

    import datetime as _dt
    for i in range(n):
        # ── seasonal (date-derived; pure calendar) ────────────────────
        ts = ts_series[i]
        d = _dt.datetime.utcfromtimestamp(ts).date()
        seasonal_arr[i] = _HIST_MONTH_BIAS.get(d.month, 0.0) + _hist_quarter_bias(d.month, d.day)
        # Clip to [-1, +1] to match HT's score range.
        if seasonal_arr[i] >  1.0: seasonal_arr[i] =  1.0
        if seasonal_arr[i] < -1.0: seasonal_arr[i] = -1.0

        # ── channel position ──────────────────────────────────────────
        # Use up to CHANNEL_WIN most-recent rows ending at i.
        win_lo = max(0, i - CHANNEL_WIN + 1)
        win_prices = price_series[win_lo : i + 1]
        if len(win_prices) >= 2:
            p_lo, p_hi = float(np.min(win_prices)), float(np.max(win_prices))
            cur = float(price_series[i])
            chan_range = p_hi - p_lo
            if chan_range > 0:
                position = (cur - p_lo) / chan_range
                raw = (0.5 - position) * 2.0
                # SMA-20 slope adjustment, normalised by price.
                if i >= SMA_WIN + SMA_LOOKBACK and SMA_WIN > 0:
                    sma_now  = float(np.mean(price_series[i - SMA_WIN + 1 : i + 1]))
                    sma_back = float(np.mean(
                        price_series[i - SMA_WIN - SMA_LOOKBACK + 1 : i - SMA_LOOKBACK + 1]
                    ))
                    sma_slope = (sma_now - sma_back) / sma_back if sma_back > 0 else 0.0
                else:
                    sma_slope = 0.0
                adjusted = raw + sma_slope * 5.0
                channel_arr[i] = max(-1.0, min(1.0, adjusted))

        # ── multi-period momentum + alignment bonus ───────────────────
        readings = []
        for period, weight in zip(MOMENTUM_PS, MOMENTUM_WS):
            if i >= period:
                back = float(price_series[i - period])
                if back > 0:
                    roc = (float(price_series[i]) - back) / back
                    readings.append((roc, weight))
        if readings:
            total_w = sum(w for _, w in readings)
            weighted_roc = sum(r * w for r, w in readings) / total_w
            score = weighted_roc * 5.0
            positive = sum(1 for r, _ in readings if r > 0)
            alignment = positive / len(readings)
            if alignment > 0.75:
                score = min(1.0, score + 0.20)
            elif alignment < 0.25:
                score = max(-1.0, score - 0.20)
            momentum_arr[i] = max(-1.0, min(1.0, score))

        # ── volume pattern (graceful degrade if column absent) ────────
        if has_volume and i >= 10:
            recent_prices = price_series[i - 10 + 1 : i + 1]
            recent_vols   = vol_series[i - 10 + 1 : i + 1]
            if len(recent_prices) >= 2:
                rets = np.diff(recent_prices) / recent_prices[:-1]
                vols_aligned = recent_vols[1:]
                up_mask = rets > 0
                dn_mask = rets < 0
                up_vol = float(vols_aligned[up_mask].mean()) if up_mask.any() else 0.0
                dn_vol = float(vols_aligned[dn_mask].mean()) if dn_mask.any() else 0.0
                denom = up_vol + dn_vol
                if denom > 0:
                    vol_ratio = (up_vol - dn_vol) / denom   # in [-1, +1]
                    volume_arr[i] = max(-0.15, min(0.15, vol_ratio * 0.15))

    out["hist_seasonal"]           = seasonal_arr
    out["hist_channel_position"]   = channel_arr
    out["hist_momentum_alignment"] = momentum_arr
    out["hist_volume_pattern"]     = volume_arr
    return out

# Rolling cap: keep at most 90 days × ~12 snapshots/hour = ~26 000 rows/symbol
MAX_ROWS = 90 * 24 * 12

# One asyncio Lock per symbol — prevents concurrent reads/writes to the same file
_LOCKS: Dict[str, asyncio.Lock] = {}


def _get_lock(symbol: str) -> asyncio.Lock:
    if symbol not in _LOCKS:
        _LOCKS[symbol] = asyncio.Lock()
    return _LOCKS[symbol]


def _symbol_path(symbol: str) -> str:
    return os.path.join(_HISTORY_DIR, f"{symbol.upper()}.parquet")


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame({col: pd.Series(dtype=dt) for col, dt in _DTYPE_MAP.items()})


def _apply_cnn_feature_transforms(df: pd.DataFrame) -> pd.DataFrame:
    """Per-feature transforms applied to a snapshot df before it feeds the CNN.

    Currently:
      - earnings_score → |earnings_score|  (Task #22). The signed value's
        correlation with 1d forward return is -0.029 (noise — direction is
        dominated by post-event mean reversion), but |earnings_score|
        correlates +0.143 with realized volatility, the strongest single-
        feature predictor in the system. We feed magnitude to the CNN and
        keep the signed value on disk for LLM beat/miss context.

    Operates on a copy — the caller's df keeps its signed values.
    """
    if "earnings_score" in df.columns:
        df = df.copy()
        # Real concatenated training dfs may carry object dtype with Python None
        # values (legacy parquets pre-_DTYPE_MAP enforcement). pd.to_numeric
        # coerces safely — non-numeric / None become NaN, and downstream
        # zero-filling in get_recent_window / build_training_windows handles
        # the resulting NaN.
        df["earnings_score"] = pd.to_numeric(
            df["earnings_score"], errors="coerce"
        ).abs()
    return df


def _compute_return_features(df: pd.DataFrame) -> pd.DataFrame:
    """Augment df with per-symbol multi-horizon lagged log returns.

    Adds columns RETURN_COLUMNS = ['r_1', 'r_5', 'r_20', 'r_60', 'r_120'].
    Each row's r_N is `log(price / price.shift(N))` within the symbol's
    own chronological history. Zero-or-negative prices produce NaN/inf,
    which the downstream `np.nan_to_num` zero-fills in build_training_windows.

    Returns a copy — caller's df is unchanged.
    """
    if "price" not in df.columns or "symbol" not in df.columns:
        return df
    out = df.copy()
    for n in (1, 5, 20, 60, 120):
        col = f"r_{n}"
        out[col] = (
            out.groupby("symbol", sort=False)["price"]
               .transform(lambda s: np.log(s / s.shift(n)))
        )
    return out


def _compute_daily_return_features(df: pd.DataFrame) -> pd.DataFrame:
    """Augment df with TRUE daily-resampled lagged log returns.

    Different from _compute_return_features: that one shifts on the raw
    hourly snapshot grid, so r_120 is "120 hourly snapshots ago" ≈ 20
    trading days. This one resamples per-symbol prices to one row per
    trading day (via the snapshot_ts → calendar-date bucket, taking each
    day's last price), computes log-returns over n calendar days, then
    forward-fills back to every hourly row in that day.

    Adds columns DAILY_RETURN_COLUMNS = ['r_1d', 'r_5d', 'r_20d', 'r_60d',
    'r_120d', 'r_252d'].

    Lookahead-safe: for any row at time t, we only consume same-symbol
    rows with snapshot_ts <= t (the daily series is built from past prices
    only; the .shift(n) is a backward shift). Verified by the lookahead
    regression test (tests/test_lookahead.py).

    Returns a copy — caller's df is unchanged.
    """
    if "price" not in df.columns or "symbol" not in df.columns or "snapshot_ts" not in df.columns:
        return df
    out = df.copy()
    for col in DAILY_RETURN_COLUMNS:
        out[col] = np.nan
    if out.empty:
        return out

    # Bucket each row to its calendar date (UTC). Trading-day approximation —
    # weekend timestamps will get their own date but produce no return signal
    # since weekends don't have new prices recorded.
    dates = pd.to_datetime(out["snapshot_ts"], unit="s", utc=True).dt.date
    out["_date"] = dates

    for sym, grp in out.groupby("symbol", sort=False):
        # One row per calendar date for this symbol — last price of the day
        # (the grp is already in chronological order from upstream sort_values).
        daily_last = grp.groupby("_date")["price"].last()
        for n_days, col in zip((1, 5, 20, 60, 120, 252), DAILY_RETURN_COLUMNS):
            daily_returns = np.log(daily_last / daily_last.shift(n_days))
            # Map back to every hourly row in `grp` by its date.
            mapped = grp["_date"].map(daily_returns).values
            out.loc[grp.index, col] = mapped

    return out.drop(columns=["_date"])


def _load(symbol: str) -> pd.DataFrame:
    path = _symbol_path(symbol)
    if not os.path.exists(path):
        return _empty_df()
    try:
        return pd.read_parquet(path)
    except Exception as exc:
        logger.warning(f"signal_history: could not read {path}: {exc}")
        return _empty_df()


def _save(symbol: str, df: pd.DataFrame) -> None:
    os.makedirs(_HISTORY_DIR, exist_ok=True)
    if len(df) > MAX_ROWS:
        df = df.tail(MAX_ROWS).reset_index(drop=True)
    df.to_parquet(_symbol_path(symbol), compression="zstd", index=False)


# ── macro join ───────────────────────────────────────────────────────────────

def _macro_file_path() -> str:
    return os.path.join(_HISTORY_DIR, _MACRO_FILENAME)


def _compute_momentum_features(df: pd.DataFrame) -> pd.DataFrame:
    """Sprint 2-B (2026-05-08): derived momentum factors from RETURN_DAILY.

    Adds MOMENTUM_COLUMNS = ['mom_12_1'] computed as r_252d - r_20d
    (the Jegadeesh-Titman 12-1 momentum factor, expressed in log-return
    space).

    Pure subtraction of two existing channels — no new data dependency,
    automatically lookahead-free since both inputs are lookahead-free
    (verified by tests/test_lookahead.py).

    Returns a fresh frame; caller's df is unchanged. If either input
    column is missing (df from before Sprint 0), return df untouched.
    """
    if df.empty:
        return df
    if "r_252d" not in df.columns or "r_20d" not in df.columns:
        return df
    out = df.copy()
    out["mom_12_1"] = out["r_252d"] - out["r_20d"]
    return out


# Lazy import of get_sectors so this module stays importable even if
# data.sector_lookup has its own import-time side-effects (it touches the
# filesystem at import). Tests patch `data.signal_history.get_sectors`.
from data.sector_lookup import get_sectors   # noqa: E402


def _compute_sector_relative_features(df: pd.DataFrame) -> pd.DataFrame:
    """Sprint 3 (2026-05-08): cross-sectional sector-relative 1-month return.

    Adds SECTOR_RELATIVE_COLUMNS = ['r_20d_sector_rel'] = r_20d minus the
    symbol-equal-weight mean of r_20d across all symbols in the SAME GICS
    sector on the SAME UTC trading day.

    Why: r_20d alone tells you "this symbol returned X% over the last
    month". Sector-relative tells you "this symbol returned X% MORE/LESS
    than its sector peers" — the relative-strength signal that an entire
    sector pumping (oil day → all Energy up 5%) cannot mask.

    Symbol-equal-weight: we dedupe to one r_20d per (symbol, trading_day)
    before averaging so a symbol with more hourly snapshots doesn't
    dominate the sector mean. Without this, a symbol with 7 snapshots
    would be weighted 7x vs a symbol with 1 snapshot in the same sector.

    Lookahead-safe: the sector mean for day D uses only r_20d values
    AT day D — no forward leak. r_20d itself is daily-resampled and
    backward-shifted; the mean over a snapshot is therefore as-of D
    too. Verified by tests/test_lookahead.py.

    Robustness: if r_20d/symbol/snapshot_ts columns are absent, return
    df untouched (pre-Sprint-0 data). If get_sectors() raises (yfinance
    down, network glitch), return df untouched — must not crash the
    pipeline; loss of one channel is preferable to losing all of them.
    """
    if df.empty:
        return df
    needed = {"r_20d", "symbol", "snapshot_ts"}
    if not needed.issubset(df.columns):
        return df

    symbols = sorted(df["symbol"].dropna().unique().tolist())
    if not symbols:
        return df
    try:
        sectors = get_sectors(symbols)
    except Exception as exc:
        logger.debug("signal_history: get_sectors() failed (%s) — skipping sector-relative features", exc)
        return df

    out = df.copy()
    out["_sector"] = out["symbol"].map(sectors)
    # Bucket each row by UTC trading day. Using pandas datetime64 over
    # epoch seconds — timezone-aware to keep day boundaries unambiguous.
    out["_td"] = pd.to_datetime(out["snapshot_ts"], unit="s", utc=True).dt.date

    # Dedupe to one r_20d value per (symbol, trading_day) before averaging.
    # All hourly rows for a (symbol, day) share r_20d (Sprint 0
    # forward-fills daily values), so first() is sufficient.
    per_sym_day = (
        out[["symbol", "_sector", "_td", "r_20d"]]
        .drop_duplicates(subset=["symbol", "_td"])
    )
    sector_day_mean = (
        per_sym_day.groupby(["_sector", "_td"], dropna=False)["r_20d"]
        .mean()  # NaN-skipping by default
        .rename("_sector_day_mean")
        .reset_index()
    )
    out = out.merge(sector_day_mean, on=["_sector", "_td"], how="left")
    out["r_20d_sector_rel"] = out["r_20d"] - out["_sector_day_mean"]
    out = out.drop(columns=["_sector", "_td", "_sector_day_mean"])
    return out


def _compute_spy_correlation_features(
    df: pd.DataFrame,
    window: int = 20,
    spy_symbol: str = "SPY",
) -> pd.DataFrame:
    """Sprint 4 (2026-05-08): rolling correlation between each symbol's
    daily returns and SPY's daily returns.

    Adds SPY_CORRELATION_COLUMNS = ['corr_spy_20d']. For each
    (symbol, trading_day) row, computes Pearson correlation over the last
    `window` paired daily r_1d values (symbol vs SPY). Forward-filled to
    every hourly snapshot in that day.

    Why: r_1d alone tells you "this symbol returned X% today". The rolling
    correlation tells you "and it tracks the broad market THIS closely
    over the last month". A symbol with low |corr| has been decoupling
    from SPY — structurally different exposure than a symbol that closely
    tracks the market. Captures inter-asset comovement information that
    no single-symbol channel can.

    Lookahead-safe: rolling window uses only PAST r_1d values (closed on
    the right). r_1d itself is daily-resampled and backward-shifted from
    Sprint 0. Verified by tests/test_lookahead.py.

    Robustness:
    - Missing r_1d / symbol / snapshot_ts → return df untouched.
    - SPY itself absent from df → can't compute correlations → return
      untouched. We must not fabricate.
    - First (window-1) days per symbol → NaN (need full window of
      observations).
    """
    if df.empty:
        return df
    needed = {"r_1d", "symbol", "snapshot_ts"}
    if not needed.issubset(df.columns):
        return df

    # Always materialize the column for shape-consistency between the
    # train and serve paths. When SPY is absent (single-symbol slice
    # during testing or sparse universe), the column stays all-NaN and
    # downstream zero-fills it — but the column EXISTS so
    # build_training_windows' has_spy_corr check stays True and the
    # tensor shape matches get_recent_window.
    if spy_symbol not in df["symbol"].values:
        out = df.copy()
        out["corr_spy_20d"] = np.nan
        return out

    out = df.copy()
    out["_td"] = pd.to_datetime(out["snapshot_ts"], unit="s", utc=True).dt.date

    # SPY's daily series — one r_1d per trading day.
    spy_daily = (
        out[out["symbol"] == spy_symbol]
        .drop_duplicates(subset=["_td"])[["_td", "r_1d"]]
        .rename(columns={"r_1d": "_spy_r1d"})
    )

    # Per-(symbol, trading_day) daily series. r_1d is daily-resampled
    # (Sprint 0), so all hourly rows share the same value — drop_duplicates
    # gives us one row per (symbol, day).
    per_sym_daily = (
        out.drop_duplicates(subset=["symbol", "_td"])[["symbol", "_td", "r_1d"]]
        .merge(spy_daily, on="_td", how="left")
        .sort_values(["symbol", "_td"])
        .reset_index(drop=True)
    )

    # Rolling Pearson correlation per symbol. min_periods=window so we
    # don't emit values from short windows (which would be high-variance
    # garbage).
    #
    # Implementation note: we iterate groups explicitly rather than using
    # groupby.apply(...) because newer pandas returns a DataFrame instead
    # of a Series when there's only one group, breaking
    # `per_sym_daily["corr_spy_20d"] = result`. Single-group is the live
    # auto-backfill path where get_sample_counts() walks symbols one at a
    # time — get_training_data("SPY") feeds a SPY-only df here.
    per_sym_daily["corr_spy_20d"] = np.nan
    for _sym, group_idx in per_sym_daily.groupby("symbol").groups.items():
        g = per_sym_daily.loc[group_idx]
        corr = g["r_1d"].rolling(window, min_periods=window).corr(g["_spy_r1d"])
        per_sym_daily.loc[group_idx, "corr_spy_20d"] = corr.values

    # Forward-fill the daily value back to every hourly row in that day
    # via merge on (symbol, trading_day).
    out = out.merge(
        per_sym_daily[["symbol", "_td", "corr_spy_20d"]],
        on=["symbol", "_td"],
        how="left",
    )
    out = out.drop(columns=["_td"])
    return out


def _load_macro_features() -> Optional[pd.DataFrame]:
    """Return a date-sorted DataFrame of macro CNN features, or None when unavailable.

    Columns: date_ts plus the 5 macro_* CNN channel names (renamed from
    __MACRO__.parquet's vix_norm/gld_5d/tlt_5d/spy_5d/breadth_score).
    """
    path = _macro_file_path()
    if not os.path.exists(path):
        return None
    try:
        macro = pd.read_parquet(path)
    except Exception as exc:
        logger.warning("signal_history: could not read macro file %s: %s", path, exc)
        return None
    if macro.empty or "date_ts" not in macro.columns:
        return None

    src_cols = [c for c in _MACRO_COLUMN_MAP if c in macro.columns]
    if not src_cols:
        return None

    keep = macro[["date_ts"] + src_cols].rename(columns=_MACRO_COLUMN_MAP)
    keep = keep.dropna(subset=["date_ts"]).copy()
    keep["date_ts"] = keep["date_ts"].astype("float64")
    return keep.sort_values("date_ts").reset_index(drop=True)


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Canonical feature pipeline. Single entry point used by BOTH the
    training path (get_training_data) and the serving path (get_recent_window).

    Per docs/feature_engineering_pipeline.md Stage 6:
        "If your training pipeline and your trading bot ever call different
         code to compute the 'same' feature, you have a bug waiting to happen."

    Applies in fixed order:
        1. _apply_cnn_feature_transforms — per-row column transforms
           (currently: abs(earnings_score)).
        2. _compute_return_features      — per-symbol lagged log returns
           (r_1, r_5, r_20, r_60, r_120).
        3. _attach_macro_features        — as-of-backward join from
           __MACRO__.parquet (macro_vix_norm, macro_*_5d_back, macro_breadth_back).

    Each step returns a fresh df; the caller's df is unchanged.

    Lookahead-safe: every step uses only data with snapshot_ts <= row's ts.
    Verified by tests/test_lookahead.py.
    """
    if df.empty:
        return df
    out = _apply_cnn_feature_transforms(df)
    out = _compute_return_features(out)
    out = _attach_macro_features(out)
    # Sprint 0: daily-resampled returns appended last so existing channel
    # indices [0-18] (incl. macro) remain at the same positions for any
    # in-flight model with index-based feature_filter.
    out = _compute_daily_return_features(out)
    # Sprint 2-B: derived momentum factors (mom_12_1) — depends on
    # daily-return columns being present, so runs AFTER the daily helper.
    # Appended at the end so feature_filter indices remain stable.
    out = _compute_momentum_features(out)
    # Sprint 3: cross-sectional sector-relative features (r_20d_sector_rel)
    # — depends on r_20d, joined with sector lookup. Runs AFTER daily
    # returns so r_20d is populated. Appended last so existing channel
    # indices remain stable.
    out = _compute_sector_relative_features(out)
    # Sprint 4: rolling SPY correlation (corr_spy_20d) — depends on r_1d,
    # joined against SPY's r_1d in same df. Runs AFTER daily returns so
    # r_1d is populated for every symbol incl SPY. Appended last so
    # existing channel indices remain stable.
    out = _compute_spy_correlation_features(out)
    # 2026-05-09 (option C): import HistoricalTrendsAgent's 4 sub-scores
    # as XGB feature channels. Only depends on price (+ optional volume),
    # so order vs upstream helpers doesn't matter — append last for
    # index stability.
    out = _compute_historical_features(out)
    return out


def _attach_macro_features(df: pd.DataFrame) -> pd.DataFrame:
    """As-of-backward-join macro features onto per-symbol training rows.

    Each snapshot at time T picks up the macro row with the largest date_ts ≤ T,
    within _MACRO_AS_OF_TOLERANCE_SECS. Rows outside the tolerance get 0.0 for all
    macro columns (matches macro_history.get_features_for_date semantics).
    Returns df unchanged when the macro file is missing or empty.
    """
    if df.empty or "snapshot_ts" not in df.columns:
        return df
    macro = _load_macro_features()
    if macro is None or macro.empty:
        return df

    target_cols = list(_MACRO_COLUMN_MAP.values())
    left = df.copy()
    left["snapshot_ts"] = left["snapshot_ts"].astype("float64")
    left = left.sort_values("snapshot_ts").reset_index(drop=True)

    merged = pd.merge_asof(
        left,
        macro,
        left_on="snapshot_ts",
        right_on="date_ts",
        direction="backward",
        tolerance=float(_MACRO_AS_OF_TOLERANCE_SECS),
    )
    merged = merged.drop(columns=["date_ts"], errors="ignore")
    for col in target_cols:
        if col in merged.columns:
            merged[col] = merged[col].fillna(0.0)
    return merged


# ── public store ──────────────────────────────────────────────────────────────

class SignalHistoryStore:
    """Records per-symbol signal snapshots and fills in forward-return outcomes."""

    async def record_snapshot(
        self,
        symbol: str,
        scores: Dict[str, Optional[float]],
        composite_score: float,
        price: float,
        rv_20d: Optional[float] = None,
        rv_60d: Optional[float] = None,
        volume: Optional[float] = None,
    ) -> None:
        """
        Append one row to the symbol's Parquet file.

        scores keys must match the source names used in signal_aggregator:
          analyst_consensus, earnings_surprise, alpaca_news, yahoo_news,
          congressional_trades, iv_rv_spread

        rv_20d / rv_60d: annualized realized volatility (252-day basis) computed
          from the symbol's recent daily close prices.  Pass None when bars are
          unavailable (will be stored as NaN and zero-filled in get_recent_window).
        """
        row = {
            "symbol":          symbol,
            "snapshot_ts":     time.time(),
            "analyst_score":   scores.get("analyst_consensus"),
            "earnings_score":  scores.get("earnings_surprise"),
            "alpaca_score":    scores.get("alpaca_news"),
            "yahoo_score":     scores.get("yahoo_news"),
            "congress_score":  scores.get("congressional_trades"),
            "iv_rv_score":     scores.get("iv_rv_spread"),
            "composite_score": composite_score,
            "price":           price,
            "return_1d":       np.nan,
            "return_5d":       np.nan,
            "return_10d":      np.nan,
            "rv_20d":          rv_20d,
            "rv_60d":          rv_60d,
            "volume":          volume,
        }
        async with _get_lock(symbol):
            df = _load(symbol)
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            _save(symbol, df)

    async def update_outcomes(self, symbol: str, current_price: float) -> int:
        """
        Fill in return_1d / return_5d / return_10d for any snapshots whose
        outcome window has now elapsed. Returns the number of rows updated.

        Uses wall-clock time: 1 day = 86 400 s. For true trading-day accuracy
        you would filter weekends, but the approximation is fine for the
        training signal — the model trains on what's persisted.
        """
        ONE_DAY   = 86_400
        FIVE_DAYS = 5 * ONE_DAY
        TEN_DAYS  = 10 * ONE_DAY
        now       = time.time()
        updated   = 0

        async with _get_lock(symbol):
            df = _load(symbol)
            if df.empty:
                return 0
            # Old parquets predate return_10d — add it as NaN so the mask works.
            if "return_10d" not in df.columns:
                df["return_10d"] = np.nan

            age = now - df["snapshot_ts"]

            mask_1d  = df["return_1d"].isna()  & (age >= ONE_DAY)
            mask_5d  = df["return_5d"].isna()  & (age >= FIVE_DAYS)
            mask_10d = df["return_10d"].isna() & (age >= TEN_DAYS)

            for idx in df.index[mask_1d]:
                snap_price = df.at[idx, "price"]
                if snap_price and snap_price > 0:
                    df.at[idx, "return_1d"] = (current_price - snap_price) / snap_price
                    updated += 1

            for idx in df.index[mask_5d]:
                snap_price = df.at[idx, "price"]
                if snap_price and snap_price > 0:
                    df.at[idx, "return_5d"] = (current_price - snap_price) / snap_price
                    updated += 1

            for idx in df.index[mask_10d]:
                snap_price = df.at[idx, "price"]
                if snap_price and snap_price > 0:
                    df.at[idx, "return_10d"] = (current_price - snap_price) / snap_price
                    updated += 1

            if updated:
                _save(symbol, df)

        return updated

    def get_training_data(self, symbol: Optional[str] = None) -> pd.DataFrame:
        """
        Return all rows that have a known 1D outcome.
        Pass symbol=None to aggregate across every stored symbol.

        Macro features (5 CNN channels) are joined as-of date from
        __MACRO__.parquet when present; absent macro file → no macro columns
        added (CNN degrades to 10ch).
        """
        if symbol:
            df = _load(symbol)
            if "return_1d" not in df.columns:
                return _empty_df()
            ready = df.dropna(subset=["return_1d"]).reset_index(drop=True)
            return compute_features(ready)

        parts: List[pd.DataFrame] = []
        if os.path.isdir(_HISTORY_DIR):
            for fname in os.listdir(_HISTORY_DIR):
                if fname.endswith(".parquet"):
                    sym = fname[:-8]
                    if sym.startswith("__"):
                        continue   # skip __MACRO__ and any other meta files
                    df  = _load(sym)
                    if "return_1d" not in df.columns:
                        continue
                    ready = df.dropna(subset=["return_1d"])
                    if not ready.empty:
                        parts.append(ready)

        if not parts:
            return _empty_df()
        combined = pd.concat(parts, ignore_index=True)
        return compute_features(combined)

    async def record_agent_signals(
        self,
        symbol: str,
        agent_consensus: float,
        agent_agreement: float,
        max_age_secs: float = 100_000.0,
    ) -> bool:
        """
        Update the most recent snapshot for symbol with agent signal data.

        Looks back at most max_age_secs (default ≈28 hours) to find the row to update.
        The default covers the observed once-per-trading-day snapshot cadence plus a
        weekend buffer; the prior 120 s default rejected every call in production
        because snapshots arrive far less frequently than agent runs (median gap ~1 day).

        Returns True if a qualifying row was found and updated.
        Called from main.py after all agents have run each cycle.
        """
        async with _get_lock(symbol):
            df = _load(symbol)
            if df.empty:
                return False

            now    = time.time()
            recent = df.index[df["snapshot_ts"] >= now - max_age_secs]
            if len(recent) == 0:
                return False

            last_idx = recent[-1]

            # Ensure new columns exist (backward-compat with old Parquet files)
            for col in ("agent_consensus", "agent_agreement", "top_agent_correct"):
                if col not in df.columns:
                    df[col] = np.nan

            df.at[last_idx, "agent_consensus"] = float(agent_consensus)
            df.at[last_idx, "agent_agreement"] = float(agent_agreement)
            _save(symbol, df)

        return True

    async def update_top_agent_correct(self, symbol: str, current_price: float) -> int:
        """
        Fill top_agent_correct for snapshots whose 1-day outcome is now known.

        top_agent_correct = 1.0 if the agent_consensus direction matched the
        actual 1D price return sign, else 0.0.

        Returns the number of rows updated.
        """
        ONE_DAY = 86_400
        now     = time.time()
        updated = 0

        async with _get_lock(symbol):
            df = _load(symbol)
            if df.empty or "agent_consensus" not in df.columns:
                return 0

            age = now - df["snapshot_ts"]
            mask = (
                df["top_agent_correct"].isna()
                & (age >= ONE_DAY)
                & df["agent_consensus"].notna()
            )

            for idx in df.index[mask]:
                snap_price = df.at[idx, "price"]
                if not snap_price or snap_price <= 0:
                    continue
                actual_return = (current_price - snap_price) / snap_price
                consensus     = df.at[idx, "agent_consensus"]
                # Correct if consensus direction matches actual return direction
                correct = (
                    1.0 if (consensus > 0 and actual_return > 0)
                         or (consensus < 0 and actual_return < 0)
                    else 0.0
                )
                df.at[idx, "top_agent_correct"] = correct
                updated += 1

            if updated:
                _save(symbol, df)

        return updated

    def get_recent_window(self, symbol: str, T: int = 10) -> Optional[np.ndarray]:
        """
        Return the most recent T snapshots as a (25, T) float array:
        5 source + 2 agent + 2 rv + 5 (hourly) returns + 5 macro
                + 6 (daily-resampled) returns.

        Channel order matches cnn_model.ALL_CHANNEL_COLUMNS (derived from
        feature_catalog.CATALOG). Daily-return block is appended last so
        existing channel indices [0-18] are preserved — the production
        XGB feature_filter (saved as integer indices) remains valid
        across this Sprint 0 expansion.

        Old Parquet files without a column return zeros for that channel.
        Returns None if fewer than 3 snapshots exist (insufficient context).
        """
        df = _load(symbol)
        if len(df) < 3:
            return None

        # Single entry point — same pipeline as get_training_data (Stage 6
        # of docs/feature_engineering_pipeline.md). compute_features applies
        # apply_cnn_feature_transforms -> compute_return_features ->
        # attach_macro_features in canonical order on the full per-symbol
        # history (lagged returns require it), and we tail() the result.
        df = compute_features(df)
        recent = df.tail(T)

        # Compose channel arrays in the canonical layout
        # (SOURCE 5 + AGENT 2 + RV 2 + RETURNS 5 + MACRO 5 = 19).
        # Zero-fill when a column is absent (old Parquet files / no macro file).
        def _column_block(cols):
            parts = []
            for col in cols:
                if col in recent.columns:
                    parts.append(recent[col].values.astype(float).reshape(-1, 1))
                else:
                    parts.append(np.zeros((len(recent), 1)))
            return np.hstack(parts)

        source_data        = _column_block(SOURCE_COLUMNS)
        agent_data         = _column_block(AGENT_COLUMNS)
        rv_data            = _column_block(RV_COLUMNS)
        return_data        = _column_block(RETURN_COLUMNS)
        macro_data         = _column_block(list(_MACRO_COLUMN_MAP.values()))
        daily_return_data  = _column_block(DAILY_RETURN_COLUMNS)
        momentum_data      = _column_block(MOMENTUM_COLUMNS)
        sector_relative_data = _column_block(SECTOR_RELATIVE_COLUMNS)
        spy_corr_data        = _column_block(SPY_CORRELATION_COLUMNS)
        historical_data      = _column_block(HISTORICAL_COLUMNS)

        combined = np.hstack([
            source_data, agent_data, rv_data, return_data, macro_data,
            daily_return_data, momentum_data, sector_relative_data,
            spy_corr_data, historical_data,
        ])  # (≤T, 33)

        if len(combined) < T:
            pad      = np.zeros((T - len(combined), combined.shape[1]))
            combined = np.vstack([pad, combined])

        combined = np.nan_to_num(combined, nan=0.0)
        return combined.T   # (33, T) post-#85-historical-channels

    def symbols_with_data(self) -> List[str]:
        """List all symbols that have at least one snapshot on disk."""
        if not os.path.isdir(_HISTORY_DIR):
            return []
        return [
            f[:-8] for f in os.listdir(_HISTORY_DIR)
            if f.endswith(".parquet") and not f.startswith("__")
        ]

    def sample_count(self, symbol: Optional[str] = None) -> int:
        """Total rows with a known 1D outcome (across one or all symbols)."""
        return len(self.get_training_data(symbol))


# Module-level singleton
signal_history = SignalHistoryStore()
