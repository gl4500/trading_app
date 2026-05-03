"""
Sector classification module — Sprint 2-A.

Looks up the GICS sector for an equity symbol via yfinance, caching results to
disk so subsequent training runs are O(1) per symbol.

Public surface:
    get_sector(symbol)              -> str
    get_sectors(symbols, force=...) -> dict[str, str]
    SECTORS_CACHE_PATH              (module-level path, patchable in tests)
    SECTOR_TO_ID                    (stable str -> int mapping for channel encoding)

Cache format: a JSON object at SECTORS_CACHE_PATH keyed by symbol, e.g.
    {"AAPL": "Technology", "JPM": "Financial Services", ...}

Failed lookups (network error, missing 'sector' key, malformed response) all
return the string "Unknown" — which has the canonical id 0 in SECTOR_TO_ID.

This is the prerequisite for Sprint 3 (sector-relative momentum). It deliberately
does NOT register itself with ALL_CHANNEL_COLUMNS, signal_history, or cnn_model —
those wirings are Sprint 3's job.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Dict, List

import yfinance

logger = logging.getLogger(__name__)

# ── Cache path ────────────────────────────────────────────────────────────────
# Lives next to other data caches (scan_cache.json, agent_picks.json).
SECTORS_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "sectors.json",
)

# ── Stable sector → integer mapping ───────────────────────────────────────────
# yfinance returns these 11 GICS-style sector strings. We sort them
# alphabetically and reserve id 0 for "Unknown" so the encoding is deterministic
# and downstream channel layers can rely on a fixed embedding size of 12.
_GICS_SECTORS = (
    "Basic Materials",
    "Communication Services",
    "Consumer Cyclical",
    "Consumer Defensive",
    "Energy",
    "Financial Services",
    "Healthcare",
    "Industrials",
    "Real Estate",
    "Technology",
    "Utilities",
)

SECTOR_TO_ID: Dict[str, int] = {"Unknown": 0}
for _idx, _sector in enumerate(sorted(_GICS_SECTORS), start=1):
    SECTOR_TO_ID[_sector] = _idx

UNKNOWN_SECTOR = "Unknown"


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _load_cache() -> Dict[str, str]:
    """Load the sectors cache from disk; return {} if missing/corrupt."""
    if not os.path.exists(SECTORS_CACHE_PATH):
        return {}
    try:
        with open(SECTORS_CACHE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
        logger.warning("sectors.json: unexpected format %r — ignoring", type(data))
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("sectors.json: failed to load (%s) — starting fresh", exc)
        return {}


def _save_cache(cache: Dict[str, str]) -> None:
    """Persist the sectors cache to disk (best-effort, never raises to caller)."""
    try:
        os.makedirs(os.path.dirname(SECTORS_CACHE_PATH), exist_ok=True)
        with open(SECTORS_CACHE_PATH, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, indent=2, sort_keys=True)
    except OSError as exc:
        logger.warning("sectors.json: failed to persist (%s)", exc)


# ── yfinance fetch ────────────────────────────────────────────────────────────

def _fetch_sector_from_yfinance(symbol: str) -> str:
    """Fetch the sector for a symbol from yfinance. Returns 'Unknown' on any
    failure (network, missing key, malformed response)."""
    try:
        ticker = yfinance.Ticker(symbol)
        info = ticker.info
        if not isinstance(info, dict):
            return UNKNOWN_SECTOR
        sector = info.get("sector")
        if not sector or not isinstance(sector, str):
            return UNKNOWN_SECTOR
        return sector
    except Exception as exc:  # noqa: BLE001 — yfinance can raise many things
        logger.debug("sector_lookup: yfinance fetch failed for %s: %s", symbol, exc)
        return UNKNOWN_SECTOR


# ── Public API ────────────────────────────────────────────────────────────────

def get_sector(symbol: str) -> str:
    """Return the GICS sector for ``symbol``.

    Reads from the on-disk cache when available; otherwise fetches from yfinance
    and caches the result. Returns ``"Unknown"`` on any failure.
    """
    cache = _load_cache()
    if symbol in cache:
        return cache[symbol]

    sector = _fetch_sector_from_yfinance(symbol)
    cache[symbol] = sector
    _save_cache(cache)
    return sector


def get_sectors(
    symbols: List[str],
    force_refresh: bool = False,
) -> Dict[str, str]:
    """Bulk sector lookup — used by training pipelines.

    Args:
        symbols: list of ticker symbols.
        force_refresh: if True, bypass the cache and re-fetch every symbol.

    Returns:
        ``{symbol: sector}`` for every symbol in ``symbols``.
    """
    cache = _load_cache()
    result: Dict[str, str] = {}
    dirty = False

    for symbol in symbols:
        if not force_refresh and symbol in cache:
            result[symbol] = cache[symbol]
            continue
        sector = _fetch_sector_from_yfinance(symbol)
        cache[symbol] = sector
        result[symbol] = sector
        dirty = True

    if dirty:
        _save_cache(cache)
    return result
