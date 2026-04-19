"""
Historical signal history backfill service.

Fetches daily OHLCV bars for each watchlist symbol and seeds the Parquet
signal-history files with labelled training rows.  This gives the CNN model
hundreds of (rv_context, return_1d) training pairs without waiting days for
live trading cycles to accumulate enough data.

What gets filled for each historical bar
-----------------------------------------
  price          close price on that day
  return_1d      (close[t+1] - close[t]) / close[t]   — known from full history
  return_5d      (close[t+5] - close[t]) / close[t]   — known from full history
  rv_20d         rolling 20-bar annualised realised vol (√252 basis)
  rv_60d         rolling 60-bar annualised realised vol
  rv_5d          rolling 5-bar annualised realised vol (short-term regime)
  source scores  all set to 0.0 (neutral) — historical news/analyst data
                 is not reliably available; 0.0 is the unbiased prior
  agent_consensus / agent_agreement  NaN (not available for past dates)
  composite_score  0.0 (no live signal available)

Data source priority
---------------------
  1. Alpaca (primary) — full free-tier history ≥ 5 years
  2. Stooq (fallback) — if Alpaca returns empty DataFrame

Idempotency
-----------
  Existing rows are deduped by snapshot_ts (rounded to the day).
  Re-running the backfill with the same date range adds 0 rows.
  Running with a longer range adds only the new days.
"""
import asyncio
import logging
import os
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Resolve history dir relative to this file — mirrors signal_history.py
_HISTORY_DIR = os.path.join(os.path.dirname(__file__), "history")

# Import clients lazily so the module can be imported without a live API key
try:
    from trading.alpaca_client import alpaca_client
except Exception:
    alpaca_client = None  # type: ignore

try:
    from data.stooq_client import stooq_client
except Exception:
    stooq_client = None  # type: ignore

from data.signal_history import _DTYPE_MAP, _get_lock


def _symbol_path(symbol: str) -> str:
    return os.path.join(_HISTORY_DIR, f"{symbol.upper()}.parquet")


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame({col: pd.Series(dtype=dt) for col, dt in _DTYPE_MAP.items()})


def _load(symbol: str) -> pd.DataFrame:
    path = _symbol_path(symbol)
    if not os.path.exists(path):
        return _empty_df()
    try:
        return pd.read_parquet(path)
    except Exception as exc:
        logger.warning(f"backfill: could not read {path}: {exc}")
        return _empty_df()


def _save(symbol: str, df: pd.DataFrame) -> None:
    os.makedirs(_HISTORY_DIR, exist_ok=True)
    df.to_parquet(_symbol_path(symbol), compression="zstd", index=False)


# ── RV helpers ────────────────────────────────────────────────────────────────

def _rolling_rv(closes: np.ndarray, window: int) -> np.ndarray:
    """
    Compute annualised rolling realised volatility (√252 basis).

    Parameters
    ----------
    closes : 1-D float array of close prices (chronological)
    window : look-back window in bars

    Returns
    -------
    rv : same length as closes, NaN for rows with < window prior bars
    """
    n      = len(closes)
    log_r  = np.full(n, np.nan)
    log_r[1:] = np.log(closes[1:] / closes[:-1])   # log returns

    rv = np.full(n, np.nan)
    for i in range(window, n):
        slice_ = log_r[i - window + 1 : i + 1]      # window log-returns ending at i
        if not np.isnan(slice_).any():
            rv[i] = float(np.std(slice_, ddof=1) * np.sqrt(252))
    return rv


# ── core backfill logic ───────────────────────────────────────────────────────

def _bars_to_backfill_rows(
    symbol: str,
    bars: pd.DataFrame,
) -> pd.DataFrame:
    """
    Convert a daily OHLCV DataFrame into a DataFrame ready to append to the
    Parquet signal-history file.

    Parameters
    ----------
    symbol : ticker string
    bars   : DataFrame with columns [timestamp, open, high, low, close, volume]
             sorted chronologically (oldest first)

    Returns
    -------
    DataFrame matching _DTYPE_MAP columns, excluding rows where we cannot
    compute return_1d (i.e. the final bar).
    """
    bars = bars.copy().sort_values("timestamp").reset_index(drop=True)
    closes = bars["close"].values.astype(float)
    n      = len(closes)

    if n < 3:
        return pd.DataFrame(columns=list(_DTYPE_MAP.keys()))

    # ── forward returns ───────────────────────────────────────────────────
    ret_1d = np.full(n, np.nan)
    ret_5d = np.full(n, np.nan)
    for i in range(n - 1):
        ret_1d[i] = (closes[i + 1] - closes[i]) / closes[i]
    for i in range(n - 5):
        ret_5d[i] = (closes[i + 5] - closes[i]) / closes[i]

    # ── realised volatility ───────────────────────────────────────────────
    rv_20 = _rolling_rv(closes, 20)
    rv_60 = _rolling_rv(closes, 60)

    # ── snapshot timestamps — use market-close time (approx 21:00 UTC / 4 pm ET)
    def _to_ts(ts) -> float:
        if isinstance(ts, (int, float)):
            return float(ts)
        try:
            return float(pd.Timestamp(ts).timestamp())
        except Exception:
            return float(time.time())

    snapshot_ts = np.array([_to_ts(t) for t in bars["timestamp"].values])

    rows = {
        "symbol":          symbol,
        "snapshot_ts":     snapshot_ts,
        "price":           closes,
        "return_1d":       ret_1d,
        "return_5d":       ret_5d,
        "rv_20d":          rv_20,
        "rv_60d":          rv_60,
        # Source scores — 0.0 (neutral prior; historical signals unavailable)
        "analyst_score":   0.0,
        "earnings_score":  0.0,
        "alpaca_score":    0.0,
        "yahoo_score":     0.0,
        "congress_score":  0.0,
        "iv_rv_score":     np.nan,  # can't compute without historical options data
        "composite_score": 0.0,
        # Agent channels — NaN (agents weren't running on these past dates)
        "agent_consensus":   np.nan,
        "agent_agreement":   np.nan,
        "top_agent_correct": np.nan,
    }
    df = pd.DataFrame(rows)

    # Drop the last row — no return_1d (no next bar available)
    df = df.iloc[:-1].copy()

    # Cast to canonical dtypes
    for col, dtype in _DTYPE_MAP.items():
        if col in df.columns:
            df[col] = df[col].astype(dtype)

    return df.reset_index(drop=True)


async def _fetch_bars(
    symbol: str,
    days: int,
) -> pd.DataFrame:
    """
    Fetch daily bars for symbol going back `days` days.
    Tries Alpaca first, falls back to Stooq.
    Returns an empty DataFrame on complete failure.
    """
    limit = days + 70   # extra buffer for RV warm-up (60 bars needed for rv_60d)

    # ── Alpaca ────────────────────────────────────────────────────────────
    if alpaca_client is not None:
        try:
            bars = await alpaca_client.get_bars(symbol, timeframe="1Day", limit=limit)
            if bars is not None and not bars.empty:
                logger.debug(f"backfill: Alpaca returned {len(bars)} bars for {symbol}")
                return bars
        except Exception as exc:
            logger.warning(f"backfill: Alpaca failed for {symbol}: {exc}")

    # ── Stooq fallback ────────────────────────────────────────────────────
    if stooq_client is not None:
        try:
            bars = await stooq_client.get_bars(symbol, days=limit)
            if bars is not None and not bars.empty:
                logger.debug(f"backfill: Stooq returned {len(bars)} bars for {symbol}")
                return bars
        except Exception as exc:
            logger.warning(f"backfill: Stooq failed for {symbol}: {exc}")

    logger.warning(f"backfill: no bars available for {symbol}")
    return pd.DataFrame()


async def _backfill_symbol(
    symbol: str,
    days: int,
) -> int:
    """
    Backfill one symbol.  Returns number of rows added.
    """
    bars = await _fetch_bars(symbol, days)
    if bars.empty:
        return 0

    # Trim to requested window (plus RV buffer is already inside _fetch_bars)
    cutoff_ts = time.time() - days * 86_400
    if "timestamp" in bars.columns:
        try:
            ts_series = pd.to_datetime(bars["timestamp"], utc=True)
            cutoff    = pd.Timestamp.utcfromtimestamp(cutoff_ts).tz_localize("UTC")
            bars      = bars[ts_series >= cutoff].copy()
        except Exception:
            pass   # keep all bars if timestamp parsing fails

    new_rows = _bars_to_backfill_rows(symbol, bars)
    if new_rows.empty:
        return 0

    async with _get_lock(symbol):
        existing = _load(symbol)

        if not existing.empty and "snapshot_ts" in existing.columns:
            # Dedup: round both existing and new ts to the nearest day (86 400 s)
            # to treat same-day entries as duplicates regardless of intraday jitter
            existing_days = set(
                (existing["snapshot_ts"] // 86_400).astype(int).tolist()
            )
            new_day_keys  = (new_rows["snapshot_ts"] // 86_400).astype(int)
            new_rows      = new_rows[~new_day_keys.isin(existing_days)].copy()

        if new_rows.empty:
            return 0

        combined = pd.concat([existing, new_rows], ignore_index=True)
        combined = combined.sort_values("snapshot_ts").reset_index(drop=True)
        _save(symbol, combined)
        logger.info(f"backfill: {symbol} — added {len(new_rows)} rows "
                    f"(total {len(combined)})")

    return len(new_rows)


# ── public API ────────────────────────────────────────────────────────────────

async def backfill_signal_history(
    symbols: List[str],
    days: int = 365,
) -> Dict[str, int]:
    """
    Seed signal-history Parquet files with historical bar data.

    Parameters
    ----------
    symbols : list of ticker strings (e.g. config.WATCHLIST)
    days    : how many calendar days of history to backfill

    Returns
    -------
    {symbol: rows_added}  — 0 for symbols with no data or already up-to-date.
    """
    os.makedirs(_HISTORY_DIR, exist_ok=True)
    results: Dict[str, int] = {}

    for symbol in symbols:
        try:
            added = await _backfill_symbol(symbol, days)
            results[symbol] = added
        except Exception as exc:
            logger.error(f"backfill: unexpected error for {symbol}: {exc}")
            results[symbol] = 0

    total = sum(results.values())
    logger.info(
        f"backfill complete — {total} rows added across {len(symbols)} symbols "
        f"({days}d window)"
    )
    return results


async def get_sample_counts() -> Dict[str, int]:
    """Return {symbol: labelled_row_count} for all symbols with history files."""
    from data.signal_history import signal_history
    counts = {}
    for sym in signal_history.symbols_with_data():
        counts[sym] = signal_history.sample_count(sym)
    return counts
