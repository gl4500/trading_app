"""
Macro Context Builder — Inter-Market Analysis for AI Decision Making

Implements the institutional framework from:
  - John Murphy's Intermarket Analysis (4-market cycle)
  - Bridgewater's All Weather regime model (growth/inflation matrix)
  - AQR momentum across asset classes
  - Goldman Sachs / JPMorgan sector rotation signals

Tracks macro proxies and sector ETFs via yfinance (free, no API key).
Produces a formatted text block injected into Ollama / Claude prompts so
agents can reason about WHERE money is flowing across the whole market,
not just individual stock technicals.

Cache: 15 minutes — macro context doesn't change every 60 seconds.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Instrument definitions ────────────────────────────────────────────────────

MACRO_PROXIES: Dict[str, str] = {
    "GLD":  "Gold (risk-off safe haven; inverse USD)",
    "TLT":  "20Y Treasuries (bond prices; inverse of yields)",
    "UUP":  "US Dollar (DXY proxy; inverse commodities/EM)",
    "USO":  "Oil (WTI proxy; energy costs)",
    "^VIX": "Volatility / Fear Index",
    "^TNX": "10Y Treasury Yield",
}

SECTOR_ETFS: Dict[str, str] = {
    "XLK":  "Technology",
    "XLF":  "Financials",
    "XLE":  "Energy",
    "XLU":  "Utilities",
    "XLV":  "Healthcare",
    "XLI":  "Industrials",
    "XLP":  "Consumer Staples",
    "XLY":  "Consumer Discretionary",
    "XLB":  "Materials",
    "XLRE": "Real Estate",
}

_ALL_SYMBOLS = list(MACRO_PROXIES.keys()) + list(SECTOR_ETFS.keys())
_CACHE_SECONDS = 15 * 60   # 15-minute cache
_cache_text: str = ""
_cache_ts: float = 0.0

# ── Inter-market relationship rules ──────────────────────────────────────────
# Each rule: (signal description, {sector: "bullish"|"bearish"})
# Based on Murphy's intermarket analysis + institutional practice

def _apply_intermarket_rules(
    ret: Dict[str, Dict[str, float]],
    vix_price: float,
    yield_10y: float,
) -> Tuple[str, list, Dict[str, str]]:
    """
    Apply John Murphy's intermarket rules + Bridgewater regime logic.

    Returns (regime, [signal_strings], {sector_etf: "bullish"|"bearish"})
    """
    signals: list = []
    sector_bias: Dict[str, str] = {}

    def r(sym, period="5d") -> float:
        return ret.get(sym, {}).get(period, 0.0)

    gold_5d = r("GLD")
    tlt_5d  = r("TLT")
    usd_5d  = r("UUP")
    oil_5d  = r("USO")
    gold_1d = r("GLD", "1d")
    tlt_1d  = r("TLT", "1d")

    # ── Rule 1: Gold rallying ─────────────────────────────────────────────
    # Classic risk-off: money flees equities into gold + bonds
    if gold_5d > 2.0:
        signals.append(
            f"Gold +{gold_5d:.1f}% (5D) → RISK-OFF: capital fleeing to safety. "
            f"Defensives (XLU, XLV, XLP) outperform; Growth/Tech (XLK, XLY) underperform."
        )
        for s in ("XLU", "XLV", "XLP"):
            sector_bias[s] = "bullish"
        for s in ("XLK", "XLY", "XLRE"):
            sector_bias.setdefault(s, "bearish")
    elif gold_5d > 0.8:
        signals.append(
            f"Gold +{gold_5d:.1f}% (5D) → Mild risk-off bias; monitor for acceleration."
        )
    elif gold_5d < -1.5:
        signals.append(
            f"Gold {gold_5d:.1f}% (5D) → RISK-ON rotation: capital moving into equities. "
            f"Growth/cyclicals favoured over defensives."
        )
        for s in ("XLK", "XLY", "XLI", "XLF"):
            sector_bias[s] = "bullish"
        for s in ("XLU", "XLP"):
            sector_bias.setdefault(s, "bearish")

    # ── Rule 2: Bond prices / Yield direction ─────────────────────────────
    # TLT falls → yields rising → Financials benefit, rate-sensitives hurt
    if tlt_5d < -2.0:
        signals.append(
            f"Bonds (TLT) {tlt_5d:.1f}% (5D) → YIELDS RISING sharply. "
            f"XLF (Financials) benefits from wider margins. "
            f"XLU, XLRE, XLK face higher discount rate headwind."
        )
        sector_bias["XLF"] = "bullish"
        for s in ("XLU", "XLRE", "XLK"):
            sector_bias.setdefault(s, "bearish")
    elif tlt_5d < -0.8:
        signals.append(
            f"Bonds (TLT) {tlt_5d:.1f}% (5D) → Yields drifting higher. "
            f"Rate-sensitive sectors (XLU, XLRE) face mild headwind."
        )
        for s in ("XLU", "XLRE"):
            sector_bias.setdefault(s, "bearish")
    elif tlt_5d > 2.0:
        signals.append(
            f"Bonds (TLT) +{tlt_5d:.1f}% (5D) → YIELDS FALLING (flight to safety). "
            f"Defensive / rate-sensitive sectors (XLU, XLRE) benefit. "
            f"Signals growth concern — XLK, XLY may lag."
        )
        for s in ("XLU", "XLRE", "XLV"):
            sector_bias.setdefault(s, "bullish")

    # ── Rule 3: USD strength ──────────────────────────────────────────────
    # Strong USD = commodity headwind, EM pressure, multinational FX drag
    if usd_5d > 1.5:
        signals.append(
            f"USD +{usd_5d:.1f}% (5D) → STRONG DOLLAR: commodities (GLD, USO, XLB) "
            f"face headwind. Multinationals (large-cap XLK) have FX drag. "
            f"Domestic-focused stocks less affected."
        )
        for s in ("XLB", "XLE"):
            sector_bias.setdefault(s, "bearish")
    elif usd_5d < -1.5:
        signals.append(
            f"USD {usd_5d:.1f}% (5D) → WEAK DOLLAR: commodities and EM benefit. "
            f"Materials (XLB) and Energy (XLE) get tailwind."
        )
        for s in ("XLB", "XLE"):
            sector_bias.setdefault(s, "bullish")

    # ── Rule 4: Oil / Energy ──────────────────────────────────────────────
    if oil_5d > 4.0:
        signals.append(
            f"Oil +{oil_5d:.1f}% (5D) → ENERGY SURGE: XLE benefits directly. "
            f"Consumer Discretionary (XLY) and Industrials (XLI) face higher input costs."
        )
        sector_bias["XLE"] = "bullish"
        for s in ("XLY", "XLI"):
            sector_bias.setdefault(s, "bearish")
    elif oil_5d < -4.0:
        signals.append(
            f"Oil {oil_5d:.1f}% (5D) → OIL FALLING: XLE headwind; "
            f"Consumer Discretionary (XLY) and airlines/transport get relief."
        )
        sector_bias.setdefault("XLE", "bearish")
        sector_bias.setdefault("XLY", "bullish")

    # ── Rule 5: VIX / Fear ────────────────────────────────────────────────
    if vix_price > 30:
        signals.append(
            f"VIX at {vix_price:.1f} → EXTREME FEAR (>30): high-beta assets at risk. "
            f"Strongly favour defensives. Consider reducing all equity exposure."
        )
        for s in ("XLU", "XLV", "XLP"):
            sector_bias[s] = "bullish"
        for s in ("XLK", "XLY", "XLI"):
            sector_bias.setdefault(s, "bearish")
    elif vix_price > 20:
        signals.append(
            f"VIX at {vix_price:.1f} → ELEVATED FEAR (20-30): prefer lower-beta positions. "
            f"Defensive bias recommended."
        )
    elif vix_price < 14:
        signals.append(
            f"VIX at {vix_price:.1f} → LOW FEAR (<14): complacency; "
            f"Risk-on environment supports cyclicals and growth."
        )

    # ── Rule 6: Bridgewater Regime (growth/inflation matrix) ─────────────
    # Growth signal: Gold ↓ + Bonds ↓ (rising yields = growth expectations)
    # Inflation signal: Gold ↑ + Oil ↑ + Bonds ↓
    growth_signal   = (gold_5d < -0.5 and tlt_5d < -0.5 and oil_5d < 1.0)
    inflation_signal = (gold_5d > 1.0 and oil_5d > 2.0 and tlt_5d < -0.5)
    deflation_signal = (gold_5d > 1.0 and tlt_5d > 1.5 and vix_price > 20)
    stagflation_risk  = (gold_5d > 1.5 and oil_5d > 3.0 and tlt_5d < -1.0)

    if stagflation_risk:
        signals.append(
            "STAGFLATION SIGNAL (Gold ↑ + Oil ↑ + Yields ↑): worst macro regime for equities. "
            "Hard assets (XLE, XLB) > Defensives > Growth."
        )
    elif inflation_signal:
        signals.append(
            "INFLATION REGIME (Bridgewater): Gold + Oil rising, bonds selling off. "
            "Overweight: XLE (energy), XLB (materials), TIPS proxies. "
            "Underweight: long-duration tech (XLK), bonds."
        )
    elif deflation_signal:
        signals.append(
            "DEFLATION / RECESSION FEAR (Bridgewater): Gold + Bonds rising, VIX elevated. "
            "Overweight: TLT, XLU, XLV, XLP. Underweight: XLE, XLB, XLY."
        )
    elif growth_signal:
        signals.append(
            "GROWTH REGIME (Bridgewater): yields rising, gold falling — growth expectations high. "
            "Overweight: XLK (tech), XLF (financials), XLY, XLI. "
            "Underweight: TLT, XLU."
        )

    # ── Determine overall regime ──────────────────────────────────────────
    bearish_count = sum(1 for v in sector_bias.values() if v == "bearish")
    bullish_count = sum(1 for v in sector_bias.values() if v == "bullish")

    if stagflation_risk:
        regime = "STAGFLATION RISK"
    elif deflation_signal or gold_5d > 2.0:
        regime = "RISK-OFF / DEFENSIVE"
    elif growth_signal and vix_price < 18:
        regime = "RISK-ON / GROWTH"
    elif inflation_signal:
        regime = "INFLATIONARY"
    elif vix_price > 25:
        regime = "HIGH VOLATILITY"
    elif bearish_count > bullish_count + 2:
        regime = "CAUTIOUS"
    elif bullish_count > bearish_count + 2:
        regime = "CONSTRUCTIVE"
    else:
        regime = "NEUTRAL / MIXED"

    return regime, signals, sector_bias


# ── Data fetching ─────────────────────────────────────────────────────────────

def _fetch_macro_data() -> Optional[Dict]:
    """Fetch 25 days of daily bars for all macro/sector symbols via yfinance."""
    try:
        import yfinance as yf
        tickers = yf.Tickers(" ".join(_ALL_SYMBOLS))
        hist = tickers.history(period="25d", auto_adjust=True)
        if hist.empty:
            return None

        close = hist["Close"] if "Close" in hist.columns else hist.get("close")
        if close is None or close.empty:
            return None

        result: Dict[str, Dict] = {}
        for sym in _ALL_SYMBOLS:
            col = sym
            if col not in close.columns:
                continue
            series = close[col].dropna()
            if len(series) < 2:
                continue
            price = float(series.iloc[-1])

            def pct(n):
                if len(series) <= n:
                    return None
                return (series.iloc[-1] / series.iloc[-1 - n] - 1) * 100

            result[sym] = {
                "price": price,
                "1d":    pct(1),
                "5d":    pct(5),
                "20d":   pct(20),
            }
        return result if result else None
    except Exception as e:
        logger.warning(f"MacroContext: fetch failed: {e}")
        return None


def _momentum_arrow(ret_5d: Optional[float], ret_20d: Optional[float]) -> str:
    if ret_5d is None:
        return "→"
    if ret_5d > 2.0 and (ret_20d or 0) > 3.0:
        return "↑↑"
    if ret_5d > 0.5:
        return "↑ "
    if ret_5d < -2.0 and (ret_20d or 0) < -3.0:
        return "↓↓"
    if ret_5d < -0.5:
        return "↓ "
    return "→ "


def _fmt(v: Optional[float]) -> str:
    return f"{v:+.1f}%" if v is not None else "  n/a "


def _build_macro_text(data: Dict) -> str:
    """Format macro data into a prompt-ready text block."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Extract returns dict (handle None values)
    ret: Dict[str, Dict[str, float]] = {}
    for sym, d in data.items():
        ret[sym] = {k: v for k, v in d.items() if k in ("1d", "5d", "20d") and v is not None}

    vix_price  = data.get("^VIX", {}).get("price", 18.0) or 18.0
    yield_10y  = data.get("^TNX", {}).get("price", 4.5) or 4.5

    regime, signals, sector_bias = _apply_intermarket_rules(ret, vix_price, yield_10y)

    lines = [
        f"## Macro Sector Rotation Context  [{now}]",
        f"",
        f"MACRO REGIME: {regime}",
        f"10Y Yield: {yield_10y:.2f}%   |   VIX: {vix_price:.1f}",
        f"",
    ]

    # ── Inter-market signals ──────────────────────────────────────────────
    if signals:
        lines.append("INTER-MARKET SIGNALS (John Murphy / Bridgewater framework):")
        for s in signals:
            lines.append(f"  • {s}")
        lines.append("")

    # ── Macro proxy performance ───────────────────────────────────────────
    lines.append("MACRO PROXY PERFORMANCE (1D / 5D / 20D):")
    for sym, label in MACRO_PROXIES.items():
        d = data.get(sym, {})
        if not d:
            continue
        arrow = _momentum_arrow(d.get("5d"), d.get("20d"))
        lines.append(
            f"  {sym:<6} {label:<40} "
            f"{_fmt(d.get('1d'))} / {_fmt(d.get('5d'))} / {_fmt(d.get('20d'))}  {arrow}"
        )
    lines.append("")

    # ── Sector performance table ──────────────────────────────────────────
    lines.append("SECTOR ETF PERFORMANCE (1D / 5D / 20D)  [bias from inter-market rules]:")
    for sym, label in SECTOR_ETFS.items():
        d = data.get(sym, {})
        if not d:
            continue
        arrow = _momentum_arrow(d.get("5d"), d.get("20d"))
        bias  = sector_bias.get(sym, "")
        bias_tag = f"  ← {bias.upper()}" if bias else ""
        lines.append(
            f"  {sym:<6} {label:<22} "
            f"{_fmt(d.get('1d'))} / {_fmt(d.get('5d'))} / {_fmt(d.get('20d'))}  {arrow}{bias_tag}"
        )
    lines.append("")

    # ── Actionable summary ────────────────────────────────────────────────
    bullish_sectors = [f"{SECTOR_ETFS[s]} ({s})" for s, b in sector_bias.items() if b == "bullish"]
    bearish_sectors = [f"{SECTOR_ETFS[s]} ({s})" for s, b in sector_bias.items() if b == "bearish"]

    lines.append("TRADING IMPLICATIONS FOR YOUR WATCHLIST:")
    if bullish_sectors:
        lines.append(f"  Macro TAILWIND: {', '.join(bullish_sectors)}")
    if bearish_sectors:
        lines.append(f"  Macro HEADWIND: {', '.join(bearish_sectors)}")
    lines.append(
        "  Apply these as a tiebreaker: when technicals are mixed, "
        "prefer macro tailwind sectors and require stronger conviction "
        "in macro headwind sectors before buying."
    )

    return "\n".join(lines)


# ── Public async API ──────────────────────────────────────────────────────────

async def get_macro_context_text() -> str:
    """
    Return a formatted macro context string for injection into AI prompts.
    Results are cached for 15 minutes. Returns empty string on any error.
    """
    global _cache_text, _cache_ts

    now = time.time()
    if _cache_text and (now - _cache_ts) < _CACHE_SECONDS:
        return _cache_text

    try:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, _fetch_macro_data)
        if not data:
            logger.warning("MacroContext: no data returned — skipping macro section")
            return _cache_text  # return stale cache rather than nothing

        text = _build_macro_text(data)
        _cache_text = text
        _cache_ts   = now
        logger.info(f"MacroContext: updated ({len(data)} instruments fetched)")
        return text
    except Exception as e:
        logger.warning(f"MacroContext: error building context: {e}")
        return _cache_text  # return stale on error rather than crashing
