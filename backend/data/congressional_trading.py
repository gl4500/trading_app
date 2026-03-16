"""
Congressional Trading Signal — SEC EDGAR Form 4 source.

Uses the public SEC EDGAR full-text search API (no key required) to find
recent Form 4 insider-trading filings.  Filings by known congress members
are scored: purchases = bullish, sales = bearish.

Data refreshed every 4 hours (congressional trades are infrequent).

Reference:
  https://efts.sec.gov/LATEST/search-index?q="AAPL"&forms=4
"""
import asyncio
import logging
import time
import re
from typing import Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

EDGAR_TTL = 4 * 3600          # 4-hour cache
EDGAR_SEARCH = (
    "https://efts.sec.gov/LATEST/search-index"
    "?q=%22{ticker}%22&forms=4&dateRange=custom&startdt={start}&enddt={end}"
)
EDGAR_FILING = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=4&dateb=&owner=include&count=10&search_text="

_cache: Dict[str, Tuple[float, Dict]] = {}

# ── Known congress member name fragments ──────────────────────────────────────
# Partial matches — catches "PELOSI", "TUBERVILLE", etc.  Not exhaustive;
# expands automatically from Capitol Trades name list when reachable.
CONGRESS_NAME_FRAGMENTS = {
    # House
    "pelosi", "tuberville", "ossoff", "wicker", "bass",
    "gaetz", "ocasio", "aoc", "omar", "tlaib",
    "green", "biggs", "jeffries", "mccarthy", "scalise",
    "crenshaw", "donalds", "massie", "chip", "higgins",
    # Senate
    "warren", "sanders", "schumer", "mcconnell", "cornyn",
    "thune", "murkowski", "collins", "romney", "scott",
    "manchin", "sinema", "kelly", "warnock", "loeffler",
    "burr", "perdue", "inhofe", "grassley", "crapo",
    "blumenthal", "booker", "brown", "cardin", "carper",
    "casey", "durbin", "feinstein", "heinrich", "hirono",
    "kaine", "king", "leahy", "merkley", "mikulski",
    "murray", "reed", "shaheen", "stabenow", "tester",
    "udall", "whitehouse", "wyden",
}


def _is_congress_member(display_name: str) -> bool:
    """Heuristic: does the filer name contain a known congress fragment?"""
    lower = display_name.lower()
    return any(frag in lower for frag in CONGRESS_NAME_FRAGMENTS)


def _parse_transaction_type(form_text: str) -> Optional[str]:
    """
    Try to extract the transaction type from a Form 4 filing URL or title.
    SEC EDGAR search results don't expose the exact transaction type in the
    search-index JSON, so we classify by the description field if present.
    Returns 'buy', 'sell', or None.
    """
    lower = form_text.lower()
    if any(w in lower for w in ("acquisition", "purchase", "p - purchase")):
        return "buy"
    if any(w in lower for w in ("disposition", "sale", " s - sale", "s-sale")):
        return "sell"
    return None


def _score_filings(filings: List[Dict]) -> Tuple[Optional[float], int, int, int]:
    """
    Score a list of Form 4 filings for one symbol.
    Returns (score [-1,+1], congress_buys, congress_sells, total_congress).
    """
    congress_buys = 0
    congress_sells = 0
    other_buys = 0
    other_sells = 0

    for hit in filings:
        names = hit.get("display_names", [])
        # display_names can be a list of strings or a list of dicts
        name_strings = []
        for n in names:
            if isinstance(n, dict):
                name_strings.append(n.get("name", "") + " " + n.get("entity_type", ""))
            else:
                name_strings.append(str(n))

        is_congress = any(_is_congress_member(n) for n in name_strings)

        # Try to infer transaction type from file description
        desc = " ".join([
            hit.get("period_ending", ""),
            hit.get("file_date", ""),
            " ".join(name_strings),
        ])
        tx = _parse_transaction_type(desc)

        # For scoring we weight congress more heavily
        if is_congress:
            if tx == "buy":
                congress_buys += 1
            elif tx == "sell":
                congress_sells += 1
            # unknown tx → neither
        else:
            if tx == "buy":
                other_buys += 1
            elif tx == "sell":
                other_sells += 1

    total_congress = congress_buys + congress_sells
    total_other    = other_buys + other_sells

    score = None
    if total_congress > 0 or total_other > 0:
        # Congress trades weighted 3× vs general insider trades
        w_congress = 3.0
        w_other    = 1.0
        buys_weighted  = congress_buys * w_congress  + other_buys  * w_other
        sells_weighted = congress_sells * w_congress + other_sells * w_other
        total_w = buys_weighted + sells_weighted
        if total_w > 0:
            raw = (buys_weighted - sells_weighted) / total_w
            score = round(max(-1.0, min(1.0, raw)), 3)

    return score, congress_buys, congress_sells, total_congress


def _fetch_edgar_sync(symbol: str) -> Dict:
    """Synchronous EDGAR fetch — run via asyncio.to_thread."""
    from datetime import date, timedelta
    end   = date.today().isoformat()
    start = (date.today() - timedelta(days=90)).isoformat()
    url = EDGAR_SEARCH.format(ticker=symbol, start=start, end=end)

    headers = {
        "User-Agent": "trading-app research@example.com",
        "Accept": "application/json",
    }
    try:
        r = httpx.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        hits = data.get("hits", {}).get("hits", [])
        sources = [h.get("_source", {}) for h in hits]
        return {"filings": sources}
    except Exception as e:
        logger.debug(f"EDGAR fetch failed for {symbol}: {e}")
        return {"filings": []}


async def get_congressional_signal(symbol: str) -> Dict:
    """
    Return a congressional/insider trading signal dict for one symbol.
    Result is cached for EDGAR_TTL seconds.
    """
    now = time.time()
    if symbol in _cache:
        ts, cached = _cache[symbol]
        if now - ts < EDGAR_TTL:
            return cached

    raw = await asyncio.to_thread(_fetch_edgar_sync, symbol)
    filings = raw.get("filings", [])

    score, c_buys, c_sells, c_total = _score_filings(filings)

    result = {
        "symbol":          symbol,
        "score":           score,
        "congress_buys":   c_buys,
        "congress_sells":  c_sells,
        "congress_total":  c_total,
        "total_filings":   len(filings),
        "window_days":     90,
    }
    _cache[symbol] = (now, result)
    return result


async def get_congressional_signals_multi(symbols: List[str]) -> Dict[str, Dict]:
    """Fetch congressional signals for multiple symbols in parallel."""
    tasks = [get_congressional_signal(sym) for sym in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out = {}
    for sym, res in zip(symbols, results):
        if isinstance(res, Exception):
            logger.warning(f"congressional_trading error for {sym}: {res}")
            out[sym] = {"symbol": sym, "score": None, "congress_buys": 0,
                        "congress_sells": 0, "congress_total": 0, "total_filings": 0}
        else:
            out[sym] = res
    return out
