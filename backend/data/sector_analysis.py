"""
Sector analysis — macro-to-micro relative strength context.

Provides:
  get_sector_performance()         — fetch/cache sector ETF returns vs SPY
  get_stock_vs_sector()            — how a stock is doing vs its sector
  format_sector_summary()          — market + sector summary string for prompts
  format_stock_sector_context()    — per-symbol sector string for prompts
"""
import logging
import time
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ── Sector → representative ETF mapping ──────────────────────────────────────

SECTOR_ETF_MAP: Dict[str, str] = {
    "Technology":             "XLK",
    "Healthcare":             "XLV",
    "Finance":                "XLF",
    "Energy":                 "XLE",
    "Consumer_Discretionary": "XLY",
    "Consumer_Staples":       "XLP",
    "Industrial":             "XLI",
    "Communication":          "XLC",
    "Materials":              "XLB",
}

BROAD_MARKET: List[str] = ["SPY", "QQQ", "IWM"]
ALL_ETFS: List[str] = BROAD_MARKET + list(SECTOR_ETF_MAP.values())

# Threshold for "leading" / "lagging" vs SPY (percentage points)
_LEADING_THRESHOLD  =  0.5
_LAGGING_THRESHOLD  = -0.5

# Threshold for stock outperforming / underperforming its sector (percentage points)
_STOCK_OUT_THRESHOLD   =  1.0
_STOCK_UNDER_THRESHOLD = -1.0

_CACHE_TTL: float = 300.0   # 5 minutes

# Module-level cache
_cache: Optional[Dict] = None
_cache_ts: float = 0.0


# ── Internal helpers ──────────────────────────────────────────────────────────

def _pct_change(bars: Optional[pd.DataFrame], periods: int) -> Optional[float]:
    """Return percentage change over `periods` bars, or None if insufficient data."""
    if bars is None or bars.empty or len(bars) < periods + 1:
        return None
    close = bars["close"].values
    prev = close[-(periods + 1)]
    if prev == 0:
        return None
    return float((close[-1] - prev) / prev * 100)


_BARS_NEEDED = 22  # enough for 20D pct change + RSI/MACD computation


async def _fetch_bars(symbols: List[str]) -> Dict[str, pd.DataFrame]:
    """Fetch last 22 daily bars for sector ETFs (20D pct + RSI/MACD).

    Priority: Alpaca → yfinance → Massive.
    Alpaca handles ETF bars reliably and has no per-symbol rate cap.
    Massive is last because its free tier rate-limits quickly on batches.
    """
    from trading.alpaca_client import alpaca_client

    try:
        result = await alpaca_client.get_bars_multi(symbols, limit=_BARS_NEEDED)
        if result and any(v is not None and not v.empty for v in result.values()):
            # Fill any missing symbols via yfinance
            missing = [s for s in symbols if s not in result or result[s].empty]
            if missing:
                result.update(await _fetch_bars_yfinance(missing))
            return result
    except Exception as e:
        logger.debug(f"sector_analysis: Alpaca fetch failed: {e}")

    # yfinance fallback (free, no rate cap for small batches)
    try:
        return await _fetch_bars_yfinance(symbols)
    except Exception as e:
        logger.debug(f"sector_analysis: yfinance fetch failed: {e}")

    # Massive last resort — only called if both above fail
    try:
        from data.massive_client import massive_client
        return await massive_client.get_bars_multi(symbols, days=_BARS_NEEDED)
    except Exception as e:
        logger.warning(f"sector_analysis: all bar sources failed: {e}")
        return {}


async def _fetch_bars_yfinance(symbols: List[str]) -> Dict[str, pd.DataFrame]:
    """Fetch last 22 daily bars from yfinance (no API key, free)."""
    import asyncio
    import yfinance as yf

    def _sync_fetch() -> Dict[str, pd.DataFrame]:
        result: Dict[str, pd.DataFrame] = {}
        for sym in symbols:
            try:
                ticker = yf.Ticker(sym)
                hist = ticker.history(period="30d", interval="1d", auto_adjust=True)
                if hist.empty:
                    continue
                hist = hist.rename(columns={
                    "Open": "open", "High": "high", "Low": "low",
                    "Close": "close", "Volume": "volume",
                })
                hist.index = hist.index.strftime("%Y-%m-%d")
                hist = hist.reset_index().rename(columns={"index": "timestamp", "Date": "timestamp"})
                result[sym] = hist.tail(_BARS_NEEDED)
            except Exception:
                pass
        return result

    return await asyncio.to_thread(_sync_fetch)


# ── Public API ────────────────────────────────────────────────────────────────

def _market_regime(spy_20d: Optional[float]) -> str:
    """Classify broad market trend from SPY 20-day return."""
    if spy_20d is None:
        return "unknown"
    if spy_20d >= 3.0:
        return "bull"
    if spy_20d >= 0.0:
        return "rally"
    if spy_20d >= -5.0:
        return "correction"
    return "bear"


async def get_sector_performance() -> Dict:
    """
    Fetch 1d, 5d, and 20d returns for sector ETFs and broad market indices.
    Also computes RSI for SPY/QQQ and a market regime label.
    Result is cached for 5 minutes.

    Returns a dict shaped::

        {
            "benchmark_1d":    0.4,          # SPY 1d % change
            "market_regime":   "bull",       # bull | rally | correction | bear | unknown
            "sectors": {
                "Technology": {
                    "etf":       "XLK",
                    "pct_1d":    1.2,
                    "pct_5d":    2.3,
                    "vs_spy_1d": 0.8,        # XLK - SPY 1d
                    "trend":     "leading",
                },
                ...
            },
            "broad": {
                "SPY": {"pct_1d": 0.4, "pct_5d": 1.1, "pct_20d": 3.2, "rsi": 58},
                "QQQ": {"pct_1d": 0.9, "pct_5d": 2.2, "pct_20d": 5.1, "rsi": 62},
                "IWM": {"pct_1d": -0.2, "pct_5d": 0.1, "pct_20d": 1.0, "rsi": 49},
            }
        }
    """
    global _cache, _cache_ts

    now = time.time()
    if _cache and (now - _cache_ts) < _CACHE_TTL:
        return _cache

    bars_dict = await _fetch_bars(ALL_ETFS)

    # ── Broad market ──────────────────────────────────────────────────────────
    from data import technicals as _tech

    broad: Dict[str, Dict] = {}
    for etf in BROAD_MARKET:
        bars = bars_dict.get(etf)
        p1   = _pct_change(bars, 1)
        p5   = _pct_change(bars, 5)
        p20  = _pct_change(bars, 20)
        ind  = _tech.compute(bars) if bars is not None and not bars.empty else {}
        rsi  = ind.get("rsi") if ind else None
        if p1 is not None:
            broad[etf] = {
                "pct_1d":  round(p1, 2),
                "pct_5d":  round(p5, 2)  if p5  is not None else None,
                "pct_20d": round(p20, 2) if p20 is not None else None,
                "rsi":     round(rsi, 1) if rsi  is not None else None,
            }

    benchmark_1d: Optional[float] = broad.get("SPY", {}).get("pct_1d")

    # ── Sector ETFs ───────────────────────────────────────────────────────────
    sectors: Dict[str, Dict] = {}
    for sector_name, etf in SECTOR_ETF_MAP.items():
        p1 = _pct_change(bars_dict.get(etf), 1)
        if p1 is None:
            continue   # skip if no data
        p5  = _pct_change(bars_dict.get(etf), 5)
        vs_spy = round(p1 - benchmark_1d, 2) if benchmark_1d is not None else None

        if vs_spy is None:
            trend = "neutral"
        elif vs_spy >= _LEADING_THRESHOLD:
            trend = "leading"
        elif vs_spy <= _LAGGING_THRESHOLD:
            trend = "lagging"
        else:
            trend = "neutral"

        sectors[sector_name] = {
            "etf":      etf,
            "pct_1d":   round(p1, 2),
            "pct_5d":   round(p5, 2) if p5 is not None else None,
            "vs_spy_1d": vs_spy,
            "trend":    trend,
        }

    spy_20d = broad.get("SPY", {}).get("pct_20d")
    result: Dict = {
        "benchmark_1d":  benchmark_1d,
        "market_regime": _market_regime(spy_20d),
        "sectors":       sectors,
        "broad":         broad,
    }
    _cache    = result
    _cache_ts = now
    return result


def get_stock_vs_sector(
    symbol: str,
    stock_pct_1d: Optional[float],
    sector_perf: Dict,
) -> Dict:
    """
    Return context on how a stock is performing relative to its sector and the
    broad market.

    Returns::

        {
            "sector_name":    "Technology",
            "sector_etf":     "XLK",
            "sector_pct_1d":  1.2,
            "sector_trend":   "leading",
            "stock_vs_sector": 1.8,           # stock_pct_1d - sector_pct_1d
            "stock_label":    "outperforming sector",
            "benchmark_1d":   0.4,
        }
    """
    from data.stock_universe import get_sector

    sector_name: str = get_sector(symbol)
    sectors      = sector_perf.get("sectors", {})
    sector_data  = sectors.get(sector_name, {})
    benchmark_1d = sector_perf.get("benchmark_1d")

    sector_pct_1d = sector_data.get("pct_1d")
    sector_etf    = sector_data.get("etf", "")
    sector_trend  = sector_data.get("trend", "neutral")

    stock_vs_sector: Optional[float] = None
    stock_label = "unknown"
    if stock_pct_1d is not None and sector_pct_1d is not None:
        stock_vs_sector = round(stock_pct_1d - sector_pct_1d, 2)
        if stock_vs_sector >= _STOCK_OUT_THRESHOLD:
            stock_label = "outperforming sector"
        elif stock_vs_sector <= _STOCK_UNDER_THRESHOLD:
            stock_label = "underperforming sector"
        else:
            stock_label = "in line with sector"

    return {
        "sector_name":    sector_name,
        "sector_etf":     sector_etf,
        "sector_pct_1d":  sector_pct_1d,
        "sector_trend":   sector_trend,
        "stock_vs_sector": stock_vs_sector,
        "stock_label":    stock_label,
        "benchmark_1d":   benchmark_1d,
    }


def format_sector_summary(sector_perf: Dict) -> str:
    """
    Format the macro→sector picture as a compact multi-line string.

    Example::

        Market Regime: BULL | SPY +0.4% (1D) +1.1% (5D) +3.2% (20D) RSI=58 | QQQ +0.9% (1D) +2.2% (5D) RSI=62 | IWM -0.2% (1D)
        Leading Sectors: Technology (XLK +1.2%), Communication (XLC +0.7%)
        Lagging Sectors: Energy (XLE -0.8%)
        Neutral: Healthcare (XLV +0.3%), Industrial (XLI +0.2%)
    """
    if not sector_perf:
        return ""

    broad   = sector_perf.get("broad", {})
    sectors = sector_perf.get("sectors", {})
    regime  = sector_perf.get("market_regime", "unknown")

    if not broad and not sectors:
        return ""

    lines = []

    # Broad market line with regime + multi-timeframe
    def _index_str(etf: str) -> Optional[str]:
        d = broad.get(etf, {})
        p1  = d.get("pct_1d")
        if p1 is None:
            return None
        parts = [f"{etf} {'+' if p1 >= 0 else ''}{p1:.1f}% (1D)"]
        p5 = d.get("pct_5d")
        if p5 is not None:
            parts.append(f"{'+' if p5 >= 0 else ''}{p5:.1f}% (5D)")
        p20 = d.get("pct_20d")
        if p20 is not None:
            parts.append(f"{'+' if p20 >= 0 else ''}{p20:.1f}% (20D)")
        rsi = d.get("rsi")
        if rsi is not None:
            parts.append(f"RSI={rsi:.0f}")
        return " ".join(parts)

    mkt_parts = [s for s in (_index_str(e) for e in ["SPY", "QQQ", "IWM"]) if s]
    if mkt_parts:
        regime_label = regime.upper() if regime != "unknown" else ""
        prefix = f"Market Regime: {regime_label} | " if regime_label else "Market: "
        lines.append(prefix + " | ".join(mkt_parts))

    def _fmt(name: str, d: Dict) -> str:
        etf = d.get("etf", "")
        p   = d.get("pct_1d")
        if p is not None and etf:
            return f"{name} ({etf} {'+' if p >= 0 else ''}{p:.1f}%)"
        return name

    leading = [(n, d) for n, d in sectors.items() if d.get("trend") == "leading"]
    lagging = [(n, d) for n, d in sectors.items() if d.get("trend") == "lagging"]
    neutral = [(n, d) for n, d in sectors.items() if d.get("trend") == "neutral"]

    if leading:
        sorted_leading = sorted(leading, key=lambda x: x[1].get("vs_spy_1d", 0), reverse=True)
        lines.append("Leading Sectors: " + ", ".join(_fmt(n, d) for n, d in sorted_leading))
    if lagging:
        sorted_lagging = sorted(lagging, key=lambda x: x[1].get("vs_spy_1d", 0))
        lines.append("Lagging Sectors: " + ", ".join(_fmt(n, d) for n, d in sorted_lagging))
    if neutral:
        sorted_neutral = sorted(neutral, key=lambda x: x[1].get("pct_1d", 0), reverse=True)
        lines.append("Neutral: " + ", ".join(_fmt(n, d) for n, d in sorted_neutral))

    return "\n".join(lines)


def format_stock_sector_context(symbol: str, stock_vs_sector_data: Dict) -> str:
    """
    Format a single stock's sector context for injection into agent prompts.

    Example::

        Sector: Technology | XLK +1.2% (leading vs SPY) | NVDA +1.8% vs XLK → outperforming sector
    """
    if not stock_vs_sector_data:
        return ""

    sector_name = stock_vs_sector_data.get("sector_name", "Unknown")
    sector_etf  = stock_vs_sector_data.get("sector_etf", "")
    sector_pct  = stock_vs_sector_data.get("sector_pct_1d")
    trend       = stock_vs_sector_data.get("sector_trend", "neutral")
    stock_vs    = stock_vs_sector_data.get("stock_vs_sector")
    label       = stock_vs_sector_data.get("stock_label", "")

    parts = [f"Sector: {sector_name}"]

    if sector_pct is not None and sector_etf:
        parts.append(f"{sector_etf} {'+' if sector_pct >= 0 else ''}{sector_pct:.1f}% ({trend} vs SPY)")

    if stock_vs is not None:
        parts.append(f"{symbol} {'+' if stock_vs >= 0 else ''}{stock_vs:.1f}% vs {sector_etf} → {label}")

    return " | ".join(parts)
