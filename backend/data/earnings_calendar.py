"""Earnings calendar lookup — yfinance-cached next/last earnings dates.

Pre-/post-earnings windows have very different return distributions
(post-earnings-announcement drift, increased pre-earnings volatility).
This module exposes:

    get_earnings_dates(symbol) -> EarningsDates
    days_to_next_earnings(symbol, ref_ts)   -> Optional[float]
    days_since_last_earnings(symbol, ref_ts) -> Optional[float]

Mirrors data.sector_lookup's pattern (Sprint 2-A): yfinance fetch, JSON
disk cache, soft fallback for missing/failed lookups.

Channel-wiring into build_training_windows is deferred to a follow-up
sprint — this module just makes the data available.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

EARNINGS_CACHE_PATH = os.path.join(
    os.path.dirname(__file__), "earnings_calendar.json"
)

# Cache TTL — earnings dates only change when a new earnings event fires
# (~quarterly). Refresh once per day to keep the cache reasonably fresh
# without hammering yfinance.
_CACHE_TTL_SECS = 24 * 60 * 60   # 24 hours


@dataclass(frozen=True)
class EarningsDates:
    """ISO-8601 date strings (YYYY-MM-DD) — None when unknown."""
    next_earnings: Optional[str]
    last_earnings: Optional[str]
    fetched_ts: float   # epoch seconds when this entry was last updated


def _load_cache() -> Dict[str, dict]:
    if not os.path.exists(EARNINGS_CACHE_PATH):
        return {}
    try:
        with open(EARNINGS_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"earnings_calendar: cache read failed ({e}); starting fresh")
        return {}


def _save_cache(cache: Dict[str, dict]) -> None:
    tmp = EARNINGS_CACHE_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, sort_keys=True)
        os.replace(tmp, EARNINGS_CACHE_PATH)
    except OSError as e:
        logger.warning(f"earnings_calendar: cache write failed ({e})")


def _fetch_from_yfinance(symbol: str) -> Tuple[Optional[str], Optional[str]]:
    """Pull next + last earnings dates from yfinance. Returns (next, last)
    as ISO date strings, or (None, None) on any failure."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        # next earnings — Ticker.calendar returns a dict with 'Earnings Date'
        # as a list of one or two datetimes (range or single date).
        calendar = ticker.calendar
        next_dt = None
        if isinstance(calendar, dict):
            ed = calendar.get("Earnings Date")
            if isinstance(ed, (list, tuple)) and ed:
                next_dt = ed[0]
            elif ed is not None:
                next_dt = ed
        next_iso = next_dt.isoformat()[:10] if next_dt else None

        # last earnings — Ticker.earnings_history is a DataFrame indexed by
        # date with at least the most recent quarter. Take the most recent
        # date <= today.
        last_iso = None
        try:
            hist = ticker.earnings_history
            if hist is not None and len(hist) > 0:
                # index is datetime-like; take the largest <= today
                today_dt = datetime.now(timezone.utc).date()
                past_idx = [d for d in hist.index if d.date() <= today_dt]
                if past_idx:
                    last_iso = max(past_idx).isoformat()[:10]
        except Exception:
            pass

        return next_iso, last_iso
    except Exception as e:
        logger.warning(f"earnings_calendar: yfinance fetch failed for {symbol}: {e}")
        return None, None


def get_earnings_dates(symbol: str, force_refresh: bool = False) -> EarningsDates:
    """Return cached earnings dates for symbol, refreshing from yfinance
    if absent or older than _CACHE_TTL_SECS.

    Always returns an EarningsDates (never raises) — fields are None when
    yfinance had no data or the call failed.
    """
    cache = _load_cache()
    now = time.time()
    entry = cache.get(symbol)

    if not force_refresh and entry is not None:
        ts = entry.get("fetched_ts", 0.0)
        if now - ts < _CACHE_TTL_SECS:
            return EarningsDates(
                next_earnings=entry.get("next_earnings"),
                last_earnings=entry.get("last_earnings"),
                fetched_ts=ts,
            )

    next_iso, last_iso = _fetch_from_yfinance(symbol)
    cache[symbol] = {
        "next_earnings": next_iso,
        "last_earnings": last_iso,
        "fetched_ts":    now,
    }
    _save_cache(cache)
    return EarningsDates(next_earnings=next_iso, last_earnings=last_iso, fetched_ts=now)


def get_earnings_dates_bulk(
    symbols: List[str], force_refresh: bool = False,
) -> Dict[str, EarningsDates]:
    """Bulk lookup. Returns one entry per requested symbol."""
    return {sym: get_earnings_dates(sym, force_refresh=force_refresh) for sym in symbols}


# ── Days-from-snapshot helpers ────────────────────────────────────────────

def _iso_to_ts(iso_str: Optional[str]) -> Optional[float]:
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str).replace(tzinfo=timezone.utc).timestamp()
    except (ValueError, TypeError):
        return None


def days_to_next_earnings(symbol: str, ref_ts: float) -> Optional[float]:
    """Days from `ref_ts` until next earnings event. Negative if next is
    in the past (cache stale). None when no upcoming earnings known."""
    ed = get_earnings_dates(symbol)
    target = _iso_to_ts(ed.next_earnings)
    if target is None:
        return None
    return (target - ref_ts) / 86_400.0


def days_since_last_earnings(symbol: str, ref_ts: float) -> Optional[float]:
    """Days since last earnings event at `ref_ts`. None when unknown.
    Negative if last is somehow in the future (shouldn't happen)."""
    ed = get_earnings_dates(symbol)
    source = _iso_to_ts(ed.last_earnings)
    if source is None:
        return None
    return (ref_ts - source) / 86_400.0
