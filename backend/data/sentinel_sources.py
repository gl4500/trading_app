"""
Additional news sources for the overnight sentinel.

Sources:
  1. RSS feeds  — Yahoo Finance (per-symbol), CNBC, Reuters via httpx + stdlib XML
  2. SEC EDGAR  — Recent 8-K filings (material event disclosures, free Atom feed)
  3. Yahoo Finance news — yfinance Ticker.news (richer per-symbol coverage)
  4. Finnhub    — Company news + general market news (requires FINNHUB_API_KEY)
  5. Unusual Whales — Congressional trades + options flow alerts
                     (requires UNUSUAL_WHALES_API_KEY)

All functions return List[Dict] using the same catalyst schema as the sentinel:
  {headline, summary, source, date, symbol, score, category, sectors,
   reason, detected_at}

Each item's score/category/sectors is populated by running it through
policy_monitor.score_headline() so scoring stays consistent.
"""
import asyncio
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import httpx

from config import config

# All httpx / network errors we treat as silent retryable failures
_NET_ERRORS = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.RemoteProtocolError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.PoolTimeout,
    ConnectionResetError,
    ConnectionAbortedError,
    OSError,
)

logger = logging.getLogger(__name__)

# ── RSS feed definitions ──────────────────────────────────────────────────────

_RSS_FEEDS = [
    ("CNBC Markets",   "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("CNBC Finance",   "https://www.cnbc.com/id/10000664/device/rss/rss.html"),
    ("Reuters Biz",    "https://feeds.reuters.com/reuters/businessNews"),
    ("Reuters Money",  "https://feeds.reuters.com/reuters/companyNews"),
]

_YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={sym}&region=US&lang=en-US"
_EDGAR_8K  = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcurrent&type=8-K&dateb=&owner=include&count=40&output=atom"
)
_UNUSUAL_WHALES_CONGRESS = "https://api.unusualwhales.com/api/congress/recent-trades"
_UNUSUAL_WHALES_FLOW     = "https://api.unusualwhales.com/api/option-contract/flow-alerts"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _score(headline: str, summary: str = "") -> Dict:
    """Run through policy_monitor scorer for consistent scoring."""
    try:
        from data.policy_monitor import score_headline
        return score_headline(headline, summary)
    except Exception:
        return {"score": 1, "category": "catalyst", "sectors": [], "reason": ""}


def _make_catalyst(headline: str, summary: str, source: str, date: str,
                   symbol: str = "") -> Optional[Dict]:
    """Score a headline and return a catalyst dict if score >= 1."""
    result = _score(headline, summary)
    if result["score"] < 1:
        return None
    return {
        "headline":    headline[:200],
        "summary":     summary[:300],
        "source":      source,
        "date":        date,
        "symbol":      symbol,
        "score":       result["score"],
        "category":    result["category"] or "catalyst",
        "sectors":     result["sectors"],
        "reason":      result["reason"],
        "detected_at": _now_iso(),
    }


def _parse_rss(xml_text: str, source_name: str) -> List[Dict]:
    """Parse RSS/Atom XML and return list of catalyst dicts."""
    items = []
    try:
        root = ET.fromstring(xml_text)
        # Handle both RSS <item> and Atom <entry>
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall(".//item") or root.findall(".//atom:entry", ns)
        for entry in entries:
            def _t(tag: str, _entry=entry) -> str:
                node = _entry.find(tag)
                if node is None:
                    node = _entry.find(f"atom:{tag}", ns)
                return (node.text or "").strip() if node is not None else ""

            headline = _t("title")
            summary  = _t("description") or _t("summary") or _t("content")
            date     = _t("pubDate") or _t("atom:published") or _t("updated") or ""
            if not headline:
                continue
            cat = _make_catalyst(headline, summary, source_name, date)
            if cat:
                items.append(cat)
    except Exception as e:
        logger.debug(f"RSS parse error ({source_name}): {e}")
    return items


# ── Source 1: General RSS feeds ───────────────────────────────────────────────

async def fetch_rss_feeds() -> List[Dict]:
    """Fetch CNBC and Reuters RSS feeds."""
    results: List[Dict] = []
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        for name, url in _RSS_FEEDS:
            try:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code == 200:
                    items = _parse_rss(resp.text, name)
                    results.extend(items)
                    logger.debug(f"RSS {name}: {len(items)} catalysts")
            except _NET_ERRORS as e:
                logger.debug(f"RSS fetch failed ({name}): {type(e).__name__}")
            except Exception as e:
                logger.debug(f"RSS fetch error ({name}): {e}")
    return results


# ── Source 2: Yahoo Finance RSS per symbol ────────────────────────────────────

async def fetch_yahoo_rss(symbols: List[str]) -> List[Dict]:
    """Fetch Yahoo Finance RSS headline feed for each symbol."""
    results: List[Dict] = []
    sem = asyncio.Semaphore(6)

    async def _fetch(sym: str):
        async with sem:
            try:
                url = _YAHOO_RSS.format(sym=sym)
                async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                    resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                    if resp.status_code == 200:
                        items = _parse_rss(resp.text, f"Yahoo/{sym}")
                        for item in items:
                            item["symbol"] = sym
                        return items
            except _NET_ERRORS as e:
                logger.debug(f"Yahoo RSS {sym}: {type(e).__name__}")
            except Exception as e:
                logger.debug(f"Yahoo RSS {sym}: {e}")
            return []

    batch = await asyncio.gather(*[_fetch(s) for s in symbols], return_exceptions=True)
    for r in batch:
        if isinstance(r, list):
            results.extend(r)
    return results


# ── Source 3: Yahoo Finance news via yfinance ─────────────────────────────────

async def fetch_yfinance_news(symbols: List[str]) -> List[Dict]:
    """Use yfinance Ticker.news for richer per-symbol headline coverage."""
    results: List[Dict] = []
    sem = asyncio.Semaphore(4)

    def _sync_fetch(sym: str) -> List[Dict]:
        try:
            import yfinance as yf
            ticker = yf.Ticker(sym)
            raw = ticker.news or []
            out = []
            for art in raw[:8]:
                headline = art.get("title", "")
                summary  = art.get("summary", "") or ""
                source   = art.get("publisher", "Yahoo Finance")
                ts       = art.get("providerPublishTime", 0)
                date     = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""
                cat = _make_catalyst(headline, summary, source, date, sym)
                if cat:
                    out.append(cat)
            return out
        except Exception as e:
            logger.debug(f"yfinance news {sym}: {e}")
            return []

    async def _fetch(sym: str):
        async with sem:
            return await asyncio.to_thread(_sync_fetch, sym)

    batch = await asyncio.gather(*[_fetch(s) for s in symbols], return_exceptions=True)
    for r in batch:
        if isinstance(r, list):
            results.extend(r)
    return results


# ── Source 4: SEC EDGAR 8-K filings ──────────────────────────────────────────

async def fetch_edgar_8k(symbols: List[str]) -> List[Dict]:
    """
    Fetch the latest 8-K filings from SEC EDGAR (free public Atom feed).
    8-K = material corporate event — always score 3 (significant disclosure).
    """
    results: List[Dict] = []
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                _EDGAR_8K,
                headers={"User-Agent": "TradingApp contact@example.com"},
            )
            if resp.status_code != 200:
                return []

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(resp.text)
        entries = root.findall("atom:entry", ns)

        # Build a lookup of ticker → company name substring for matching
        sym_upper = [s.upper() for s in symbols]

        for entry in entries[:60]:
            def _t(tag: str) -> str:
                node = entry.find(f"atom:{tag}", ns)
                return (node.text or "").strip() if node is not None else ""

            title   = _t("title")     # e.g. "Apple Inc. (0000320193) (8-K)"
            updated = _t("updated")
            company = title.split("(")[0].strip() if "(" in title else title

            # Only include if company name looks related to a watched symbol
            # (rough heuristic — company names don't always match tickers)
            relevant_sym = ""
            for sym in sym_upper:
                if sym in title.upper():
                    relevant_sym = sym
                    break

            headline = f"SEC 8-K Filing: {company} — material event disclosure"
            cat = _make_catalyst(headline, f"Form 8-K filing: {title}", "SEC EDGAR", updated, relevant_sym)
            if cat:
                cat["score"] = max(cat["score"], 3)   # 8-K is always significant
                cat["category"] = cat["category"] or "regulatory"
                results.append(cat)

        logger.debug(f"EDGAR 8-K: {len(results)} relevant filings")
    except _NET_ERRORS as e:
        logger.debug(f"EDGAR fetch failed: {type(e).__name__}")
    except Exception as e:
        logger.warning(f"EDGAR fetch failed: {e}")
    return results


# ── Source 5: Finnhub news ────────────────────────────────────────────────────

async def fetch_finnhub_news(symbols: List[str]) -> List[Dict]:
    """
    Fetch company news from Finnhub (requires FINNHUB_API_KEY in .env).
    Falls back silently if no key is configured.
    """
    if not config.FINNHUB_API_KEY:
        return []

    results: List[Dict] = []
    sem = asyncio.Semaphore(4)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    date_from = cutoff.strftime("%Y-%m-%d")
    date_to   = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _sync_fetch(sym: str) -> List[Dict]:
        try:
            import finnhub
            client = finnhub.Client(api_key=config.FINNHUB_API_KEY)
            news = client.company_news(sym, _from=date_from, to=date_to)
            out = []
            for art in (news or [])[:8]:
                headline = art.get("headline", "")
                summary  = art.get("summary", "") or ""
                source   = art.get("source", "Finnhub")
                ts       = art.get("datetime", 0)
                date     = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""
                cat = _make_catalyst(headline, summary, source, date, sym)
                if cat:
                    out.append(cat)
            return out
        except Exception as e:
            logger.debug(f"Finnhub news {sym}: {e}")
            return []

    async def _fetch(sym: str):
        async with sem:
            return await asyncio.to_thread(_sync_fetch, sym)

    batch = await asyncio.gather(*[_fetch(s) for s in symbols], return_exceptions=True)
    for r in batch:
        if isinstance(r, list):
            results.extend(r)
    return results


# ── Source 6: Unusual Whales ──────────────────────────────────────────────────

async def fetch_unusual_whales(symbols: List[str]) -> List[Dict]:
    """
    Fetch congressional trades and options flow alerts from Unusual Whales.
    Requires UNUSUAL_WHALES_API_KEY in .env — skipped silently if missing.

    Congressional trades:  members of Congress buying/selling stocks
    Flow alerts:           unusually large options activity (smart money signals)
    """
    if not config.UNUSUAL_WHALES_API_KEY:
        return []

    headers = {
        "Authorization": f"Bearer {config.UNUSUAL_WHALES_API_KEY}",
        "Accept": "application/json",
        "User-Agent": "TradingApp/1.0",
    }
    results: List[Dict] = []
    sym_set = {s.upper() for s in symbols}

    async with httpx.AsyncClient(timeout=15, headers=headers) as client:

        # ── Congressional trades ──────────────────────────────────────────
        try:
            resp = await client.get(_UNUSUAL_WHALES_CONGRESS, params={"limit": 50})
            if resp.status_code == 200:
                data = resp.json()
                trades = data if isinstance(data, list) else data.get("data", [])
                for t in trades:
                    ticker = (t.get("ticker") or t.get("symbol") or "").upper()
                    if ticker not in sym_set:
                        continue
                    member   = t.get("representative") or t.get("name") or "Congress member"
                    chamber  = t.get("chamber") or ""
                    action   = (t.get("transaction_date") or t.get("type") or "trade").upper()
                    amount   = t.get("amount") or t.get("value") or ""
                    filed    = t.get("filed_date") or t.get("disclosure_date") or ""
                    headline = f"Congressional Trade: {member} ({chamber}) — {ticker} {action}"
                    summary  = f"Disclosed trade of {ticker} worth {amount}. Filed: {filed}"
                    cat = _make_catalyst(headline, summary, "Unusual Whales / Congress", filed, ticker)
                    if cat:
                        cat["score"] = max(cat["score"], 2)
                        cat["category"] = "policy"
                        results.append(cat)
            logger.debug(f"Unusual Whales congress: {len([r for r in results if r.get('source','').startswith('Unusual')])} items")
        except Exception as e:
            logger.debug(f"Unusual Whales congress fetch failed: {e}")

        # ── Options flow alerts ───────────────────────────────────────────
        try:
            resp = await client.get(_UNUSUAL_WHALES_FLOW, params={"limit": 30})
            if resp.status_code == 200:
                data = resp.json()
                flows = data if isinstance(data, list) else data.get("data", [])
                for f in flows:
                    ticker = (f.get("ticker") or f.get("symbol") or "").upper()
                    if ticker not in sym_set:
                        continue
                    side      = (f.get("side") or "").upper()          # CALL / PUT
                    premium   = f.get("premium") or f.get("total_premium") or ""
                    sentiment = "bullish" if side == "CALL" else "bearish" if side == "PUT" else "unusual"
                    expiry    = f.get("expiry") or f.get("expiration_date") or ""
                    headline  = f"Unusual Options Flow: {ticker} {side} — {sentiment} {premium}"
                    summary   = f"Large {side} order on {ticker}, expiry {expiry}, premium {premium}"
                    cat = _make_catalyst(headline, summary, "Unusual Whales / Flow", "", ticker)
                    if cat:
                        cat["score"] = max(cat["score"], 2)
                        cat["category"] = "catalyst"
                        results.append(cat)
        except Exception as e:
            logger.debug(f"Unusual Whales flow fetch failed: {e}")

    return results


# ── Source 7: Massive.com — options flow + news ───────────────────────────────

async def fetch_massive_signals(symbols: List[str]) -> List[Dict]:
    """
    Fetch options flow alerts and news from Massive.com.
    Skipped silently if MASSIVE_API_KEY is not set.
    """
    from data.massive_client import massive_client
    if not massive_client._is_available():
        return []

    results: List[Dict] = []
    try:
        flow_items, news_map = await asyncio.gather(
            massive_client.get_options_flow(symbols, limit=50),
            massive_client.get_news_multi(symbols, limit=5),
            return_exceptions=True,
        )

        # Options flow → already catalyst-compatible dicts
        if isinstance(flow_items, list):
            results.extend(flow_items)
            logger.debug(f"Massive options flow: {len(flow_items)} signals")

        # News → convert to catalyst format
        if isinstance(news_map, dict):
            for sym, articles in news_map.items():
                for a in articles:
                    headline = a.get("headline", "")
                    summary  = a.get("summary", "")
                    if not headline:
                        continue
                    cat = _make_catalyst(headline, summary, "Massive News", a.get("published_at", ""), sym)
                    if cat:
                        results.append(cat)
            logger.debug(f"Massive news: {len(results) - len(flow_items if isinstance(flow_items, list) else [])} catalysts")

    except Exception as e:
        logger.debug(f"Massive signals fetch: {e}")

    return results


# ── Aggregate entry point ─────────────────────────────────────────────────────

async def fetch_all_sources(symbols: List[str]) -> List[Dict]:
    """
    Run all additional sentinel sources concurrently and return
    a deduplicated, score-sorted list of catalysts.
    """
    tasks = [
        fetch_rss_feeds(),
        fetch_yahoo_rss(symbols),
        fetch_yfinance_news(symbols),
        fetch_edgar_8k(symbols),
        fetch_finnhub_news(symbols),
        fetch_unusual_whales(symbols),
        fetch_massive_signals(symbols),
    ]

    batches = await asyncio.gather(*tasks, return_exceptions=True)

    all_items: List[Dict] = []
    seen_headlines: set = set()

    for batch in batches:
        if isinstance(batch, list):
            for item in batch:
                h = item.get("headline", "")
                if h and h not in seen_headlines:
                    seen_headlines.add(h)
                    all_items.append(item)
        elif isinstance(batch, Exception):
            logger.debug(f"Sentinel source error: {batch}")

    all_items.sort(key=lambda x: x.get("score", 0), reverse=True)
    logger.info(
        f"SentinelSources: {len(all_items)} unique catalysts from "
        f"{sum(1 for b in batches if isinstance(b, list) and b)} active sources"
    )
    return all_items
