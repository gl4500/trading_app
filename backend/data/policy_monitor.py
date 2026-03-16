"""
Policy Monitor: Scans news headlines for congressional legislation and executive
orders that have measurable sector/market impact.

Used by the after-hours news sentinel to identify policy-driven catalysts that
should trigger a fresh scanner run before the next market open.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ─── Keyword scoring tables ────────────────────────────────────────────────────

# General policy trigger words — any headline containing these gets base points
_POLICY_TRIGGERS = [
    ("executive order", 3),
    ("executive action", 2),
    ("presidential directive", 2),
    ("signed into law", 3),
    ("passed the senate", 2),
    ("passed the house", 2),
    ("signed by president", 3),
    ("veto", 2),
    ("sanctions", 2),
    ("tariff", 2),
    ("trade war", 2),
    ("trade deal", 2),
    ("antitrust", 2),
    ("sec charges", 2),
    ("sec fine", 2),
    ("doj investigation", 2),
    ("ftc ruling", 2),
    ("fed rate", 3),
    ("federal reserve", 2),
    ("interest rate decision", 3),
    ("inflation report", 2),
    ("jobs report", 2),
    ("gdp report", 2),
    ("stimulus", 2),
    ("infrastructure bill", 2),
    ("tax reform", 2),
    ("budget deal", 2),
    ("debt ceiling", 3),
    ("government shutdown", 3),
    ("nato", 1),
    ("war", 2),
    ("conflict", 1),
    ("oil embargo", 3),
    ("opec", 2),
]

# Sector-specific policy keywords → which sector is affected
_SECTOR_MAP: Dict[str, List[str]] = {
    "technology": [
        "chip ban", "semiconductor", "ai regulation", "section 230",
        "data privacy", "antitrust tech", "export controls", "huawei",
        "tiktok ban", "cyber", "quantum computing",
    ],
    "energy": [
        "oil", "gas", "lng", "pipeline", "clean energy", "renewable",
        "carbon tax", "paris agreement", "drilling", "opec",
        "strategic reserve", "epa rule", "emission",
    ],
    "healthcare": [
        "drug pricing", "medicare", "medicaid", "aca", "fda approval",
        "fda ban", "prescription", "pharma", "healthcare bill",
        "insulin", "biosimilar",
    ],
    "defense": [
        "defense spending", "military budget", "pentagon", "arms",
        "weapons", "nato", "ukraine aid", "taiwan", "china military",
        "f-35", "lockheed", "northrop", "raytheon",
    ],
    "financials": [
        "banking regulation", "dodd-frank", "cfpb", "credit", "basel",
        "capital requirements", "bank stress test", "fdic", "svb",
        "crypto regulation", "stablecoin", "sec ruling",
    ],
    "consumer": [
        "tariff", "import tax", "supply chain", "minimum wage",
        "labor law", "union", "retail regulation", "gig economy",
    ],
    "infrastructure": [
        "infrastructure bill", "roads", "bridges", "broadband",
        "water", "grid", "ev charging", "rail", "airport",
    ],
}


def score_headline(headline: str, summary: str = "") -> Dict:
    """
    Score a news headline/summary for policy relevance and sector impact.

    Returns a dict with:
      - score: int (0 = irrelevant, ≥2 = notable catalyst)
      - category: str ("policy", "macro", "geopolitical", or "")
      - sectors: List[str] — affected sectors
      - reason: str — matched keywords
    """
    text = (headline + " " + summary).lower()

    total_score = 0
    matched_keywords: List[str] = []

    # General policy scoring
    for keyword, pts in _POLICY_TRIGGERS:
        if keyword in text:
            total_score += pts
            matched_keywords.append(keyword)

    # Sector detection
    affected_sectors: List[str] = []
    for sector, keywords in _SECTOR_MAP.items():
        for kw in keywords:
            if kw in text:
                if sector not in affected_sectors:
                    affected_sectors.append(sector)
                if kw not in matched_keywords:
                    matched_keywords.append(kw)
                    total_score += 1
                break

    # Categorise
    category = ""
    if any(k in text for k in ("executive order", "executive action", "signed into law",
                                "passed the senate", "passed the house", "veto")):
        category = "policy"
    elif any(k in text for k in ("fed rate", "federal reserve", "interest rate",
                                  "inflation report", "jobs report", "gdp report")):
        category = "macro"
    elif any(k in text for k in ("war", "conflict", "nato", "ukraine", "taiwan",
                                  "sanctions", "oil embargo")):
        category = "geopolitical"
    elif total_score > 0:
        category = "regulatory"

    return {
        "score":    total_score,
        "category": category,
        "sectors":  affected_sectors,
        "reason":   ", ".join(matched_keywords[:5]),
    }


async def scan_policy_news(
    symbols: Optional[List[str]] = None,
    lookback_hours: int = 12,
) -> List[Dict]:
    """
    Fetch recent news and return articles with a policy score ≥ 2.

    Uses the broad market proxy symbols (SPY, QQQ, GLD, TLT) plus any
    supplied watchlist symbols to get macro / policy headlines.

    Returns a list of catalyst dicts sorted by score desc.
    """
    from data.news_service import news_service

    # Always scan broad-market ETFs for macro/policy news
    proxy_syms = ["SPY", "QQQ", "GLD", "TLT", "XLF", "XLE", "XLK"]
    scan_syms = list(set(proxy_syms + (symbols or [])))

    try:
        news_map = await news_service.get_news_multi(scan_syms)
    except Exception as e:
        logger.error(f"PolicyMonitor: news fetch failed: {e}")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    catalysts: List[Dict] = []
    seen_headlines: set = set()

    for sym, articles in news_map.items():
        for art in articles:
            headline = art.get("headline", "")
            if not headline or headline in seen_headlines:
                continue
            seen_headlines.add(headline)

            result = score_headline(headline, art.get("summary", ""))
            if result["score"] >= 2:
                catalysts.append({
                    "headline":  headline,
                    "summary":   art.get("summary", "")[:200],
                    "source":    art.get("source", ""),
                    "date":      art.get("date", ""),
                    "symbol":    sym,
                    "score":     result["score"],
                    "category":  result["category"],
                    "sectors":   result["sectors"],
                    "reason":    result["reason"],
                    "detected_at": datetime.utcnow().isoformat(),
                })

    catalysts.sort(key=lambda c: c["score"], reverse=True)
    logger.info(
        f"PolicyMonitor: scanned {len(scan_syms)} symbols, "
        f"found {len(catalysts)} policy/macro catalysts"
    )
    return catalysts
