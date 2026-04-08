"""
Macro Context Builder — Inter-Market Analysis for AI Decision Making

Implements the institutional framework from:
  - John Murphy's Intermarket Analysis (4-market cycle)
  - Bridgewater's All Weather regime model (growth/inflation matrix)
  - AQR momentum across asset classes
  - Goldman Sachs / JPMorgan sector rotation signals

Two-cache architecture:
  FAST (15 min)  — tactical: 1D / 5D / 20D / 60D returns + regime rules
  SLOW (24 hr)   — strategic: 52W range position, YoY returns,
                   SMA trend direction, regime duration tracking

Sector coverage:
  Core SPDR sectors (11) + Communication Services (XLC)
  Market breadth: IWM (small-cap), MDY (mid-cap)
  These extra ETFs give the AI a full market-breadth picture, not just
  large-cap tech-heavy signals.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

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
    "XLC":  "Communication Services",
}

# Market-breadth ETFs — not in ensemble vote but give size/breadth signal
BREADTH_ETFS: Dict[str, str] = {
    "IWM": "Russell 2000 (small-cap)",
    "MDY": "S&P 400 Mid-Cap",
    "SPY": "S&P 500 (benchmark)",
    "QQQ": "Nasdaq 100 (tech/growth)",
}

_CORE_SYMBOLS  = list(MACRO_PROXIES.keys()) + list(SECTOR_ETFS.keys())
_ALL_SYMBOLS   = _CORE_SYMBOLS + list(BREADTH_ETFS.keys())

# ── Cache configuration ───────────────────────────────────────────────────────
_FAST_CACHE_SECONDS = 15 * 60        # 15 minutes — tactical signals
_SLOW_CACHE_SECONDS = 24 * 60 * 60   # 24 hours   — strategic signals

_fast_cache_text: str = ""
_fast_cache_ts:   float = 0.0
_slow_cache_data: Optional[Dict] = None
_slow_cache_ts:   float = 0.0

# ── Regime duration tracking (in-process; resets on restart) ─────────────────
_current_regime:  str            = ""
_regime_start_ts: Optional[float] = None


def _reset_regime_tracking() -> None:
    """Reset regime duration state — used in tests."""
    global _current_regime, _regime_start_ts
    _current_regime  = ""
    _regime_start_ts = None


def _update_regime_duration(new_regime: str, _now: float = None) -> int:
    """
    Track how many days the current macro regime has been active.
    Returns integer days. Resets to 0 when regime changes.
    _now is injectable for testing (avoids time.time() in unit tests).
    """
    global _current_regime, _regime_start_ts
    now = _now if _now is not None else time.time()
    if new_regime != _current_regime:
        _current_regime  = new_regime
        _regime_start_ts = now
        return 0
    if _regime_start_ts is None:
        _regime_start_ts = now
    return max(0, int((now - _regime_start_ts) / 86400))


# ── Inter-market rules (tactical) ────────────────────────────────────────────

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
        return ret.get(sym, {}).get(period, 0.0) or 0.0

    gold_5d = r("GLD")
    tlt_5d  = r("TLT")
    usd_5d  = r("UUP")
    oil_5d  = r("USO")

    # ── Rule 1: Gold ──────────────────────────────────────────────────────
    if gold_5d > 2.0:
        signals.append(
            f"Gold +{gold_5d:.1f}% (5D) → RISK-OFF: capital fleeing to safety. "
            f"Defensives (XLU, XLV, XLP) outperform; Growth/Tech (XLK, XLY, XLC) underperform."
        )
        for s in ("XLU", "XLV", "XLP"):
            sector_bias[s] = "bullish"
        for s in ("XLK", "XLY", "XLRE", "XLC"):
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
        for s in ("XLK", "XLY", "XLI", "XLF", "XLC"):
            sector_bias[s] = "bullish"
        for s in ("XLU", "XLP"):
            sector_bias.setdefault(s, "bearish")

    # ── Rule 2: Bond prices / Yield direction ─────────────────────────────
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
    if usd_5d > 1.5:
        signals.append(
            f"USD +{usd_5d:.1f}% (5D) → STRONG DOLLAR: commodities (GLD, USO, XLB) "
            f"face headwind. Multinationals (XLK, XLC) have FX drag. "
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
        for s in ("XLK", "XLY", "XLI", "XLC"):
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

    # ── Rule 6: Bridgewater regime ────────────────────────────────────────
    growth_signal    = (gold_5d < -0.5 and tlt_5d < -0.5 and oil_5d < 1.0)
    inflation_signal = (gold_5d > 1.0 and oil_5d > 2.0 and tlt_5d < -0.5)
    deflation_signal = (gold_5d > 1.0 and tlt_5d > 1.5 and vix_price > 20)
    stagflation_risk = (gold_5d > 1.5 and oil_5d > 3.0 and tlt_5d < -1.0)

    if stagflation_risk:
        signals.append(
            "STAGFLATION SIGNAL (Gold ↑ + Oil ↑ + Yields ↑): worst macro regime for equities. "
            "Hard assets (XLE, XLB) > Defensives > Growth."
        )
    elif inflation_signal:
        signals.append(
            "INFLATION REGIME (Bridgewater): Gold + Oil rising, bonds selling off. "
            "Overweight: XLE (energy), XLB (materials). Underweight: XLK, bonds."
        )
    elif deflation_signal:
        signals.append(
            "DEFLATION / RECESSION FEAR (Bridgewater): Gold + Bonds rising, VIX elevated. "
            "Overweight: TLT, XLU, XLV, XLP. Underweight: XLE, XLB, XLY."
        )
    elif growth_signal:
        signals.append(
            "GROWTH REGIME (Bridgewater): yields rising, gold falling — growth expectations high. "
            "Overweight: XLK, XLF, XLY, XLI. Underweight: TLT, XLU."
        )

    # ── Rule 7: Small/Mid-cap breadth divergence ──────────────────────────
    # If IWM/MDY lag SPY, risk appetite is narrowing (institutional concern)
    iwm_5d = r("IWM")
    spy_5d = r("SPY")
    if spy_5d > 1.0 and iwm_5d < (spy_5d - 2.0):
        signals.append(
            f"Breadth: SPY +{spy_5d:.1f}% vs IWM {iwm_5d:+.1f}% (5D) — "
            f"large-cap leading, small-cap lagging. Rally may lack broad support. "
            f"Favour quality large-caps; avoid high-beta small/mid."
        )
    elif iwm_5d > (spy_5d + 2.0) and spy_5d > 0:
        signals.append(
            f"Breadth: IWM +{iwm_5d:.1f}% vs SPY {spy_5d:+.1f}% (5D) — "
            f"small-cap leading. Broad risk-on; cyclicals and growth favoured."
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


# ── Strategic insight generator (pure — no side effects, testable) ────────────

def _compute_slow_insights(slow: Dict) -> List[str]:
    """
    Generate key strategic insights from 2-year weekly data.
    Pure function — no globals, no side effects.
    """
    insights: List[str] = []

    def g(sym: str, key: str, default=None):
        return slow.get(sym, {}).get(key, default)

    gld_pos = g("GLD", "pos_52w")
    tlt_pos = g("TLT", "pos_52w")
    gld_52w = g("GLD", "52w", 0.0) or 0.0
    tlt_52w = g("TLT", "52w", 0.0) or 0.0
    uso_52w = g("USO", "52w", 0.0) or 0.0
    uup_52w = g("UUP", "52w", 0.0) or 0.0
    iwm_52w = g("IWM", "52w", 0.0) or 0.0
    spy_52w = g("SPY", "52w", 0.0) or 0.0
    qqq_52w = g("QQQ", "52w", 0.0) or 0.0

    # ── Gold position in 52W range ────────────────────────────────────────
    if gld_pos is not None and gld_pos > 85:
        insights.append(
            f"GLD at {gld_pos:.0f}% of 52W range (+{gld_52w:.0f}% YoY) — "
            f"sustained risk-off regime confirmed, not a short-term spike. "
            f"Defensives have structural tailwind."
        )
    elif gld_pos is not None and gld_pos < 20:
        insights.append(
            f"GLD at {gld_pos:.0f}% of 52W range ({gld_52w:+.0f}% YoY) — "
            f"risk-on firmly established long-term. Gold rallies are likely counter-trend."
        )

    # ── Bond market structural regime ─────────────────────────────────────
    if tlt_pos is not None and tlt_pos < 20:
        insights.append(
            f"TLT at {tlt_pos:.0f}% of 52W range ({tlt_52w:+.0f}% YoY) — "
            f"bond bear market. Yields structurally elevated. "
            f"XLU/XLRE face persistent headwind; XLF benefits."
        )
    elif tlt_pos is not None and tlt_pos > 80:
        insights.append(
            f"TLT at {tlt_pos:.0f}% of 52W range (+{tlt_52w:.0f}% YoY) — "
            f"bonds near highs; deflation/recession bid. Duration trade in favour."
        )

    # ── Long-term stagflation divergence ─────────────────────────────────
    if gld_52w > 10.0 and tlt_52w < -10.0:
        insights.append(
            f"52W: GLD +{gld_52w:.0f}% vs TLT {tlt_52w:.0f}% — "
            f"stagflation divergence confirmed over full year. "
            f"Hard assets (XLE, XLB) > Defensives > Growth."
        )

    # ── Oil structural trend ──────────────────────────────────────────────
    if uso_52w > 20.0:
        insights.append(
            f"Oil +{uso_52w:.0f}% (52W) — structural energy bull cycle. "
            f"XLE tailwind durable; consumer cost pressure persistent."
        )
    elif uso_52w < -20.0:
        insights.append(
            f"Oil {uso_52w:.0f}% (52W) — structural energy bear. "
            f"XLE headwind may persist; consumer relief supports XLY."
        )

    # ── USD structural trend ──────────────────────────────────────────────
    if uup_52w > 5.0:
        insights.append(
            f"USD +{uup_52w:.0f}% (52W) — structural dollar strength. "
            f"Commodity sectors (XLB, XLE) face sustained FX headwind."
        )
    elif uup_52w < -5.0:
        insights.append(
            f"USD {uup_52w:.0f}% (52W) — structural dollar weakness. "
            f"Commodities and EM have multi-month tailwind."
        )

    # ── Market breadth — size divergence over 52W ─────────────────────────
    if spy_52w and iwm_52w is not None:
        breadth_gap = spy_52w - iwm_52w
        if breadth_gap > 10.0:
            insights.append(
                f"52W breadth: SPY +{spy_52w:.0f}% vs IWM {iwm_52w:+.0f}% — "
                f"large-cap concentration; rally driven by mega-cap. "
                f"Narrow market breadth is a late-cycle warning sign."
            )
        elif breadth_gap < -10.0:
            insights.append(
                f"52W breadth: IWM +{iwm_52w:.0f}% vs SPY {spy_52w:+.0f}% — "
                f"small-cap leading over full year. Broad-based bull market; "
                f"risk appetite healthy."
            )

    # ── QQQ vs IWM divergence (growth vs value) ───────────────────────────
    if qqq_52w and iwm_52w is not None:
        if qqq_52w > (iwm_52w + 15.0):
            insights.append(
                f"QQQ +{qqq_52w:.0f}% vs IWM {iwm_52w:+.0f}% (52W) — "
                f"growth/tech dominance. Value rotation has not materialized. "
                f"Rate-sensitive if yields rise further."
            )
        elif iwm_52w > (qqq_52w + 15.0):
            insights.append(
                f"IWM +{iwm_52w:.0f}% vs QQQ {qqq_52w:+.0f}% (52W) — "
                f"value/small-cap outperforming growth. Classic rate-normalisation rotation."
            )

    return insights


# ── Data fetching ─────────────────────────────────────────────────────────────

def _fetch_macro_data() -> Optional[Dict]:
    """
    Fetch 65 trading days of daily bars — tactical signals.
    Covers 1D / 5D / 20D / 60D returns for all symbols.
    """
    try:
        import yfinance as yf
        tickers = yf.Tickers(" ".join(_ALL_SYMBOLS))
        hist = tickers.history(period="65d", auto_adjust=True)
        if hist.empty:
            return None

        close = hist["Close"] if "Close" in hist.columns else hist.get("close")
        if close is None or close.empty:
            return None

        result: Dict[str, Dict] = {}
        for sym in _ALL_SYMBOLS:
            if sym not in close.columns:
                continue
            series = close[sym].dropna()
            if len(series) < 2:
                continue
            price = float(series.iloc[-1])

            def pct(n, s=series):
                if len(s) <= n:
                    return None
                return (s.iloc[-1] / s.iloc[-1 - n] - 1) * 100

            result[sym] = {
                "price": price,
                "1d":    pct(1),
                "5d":    pct(5),
                "20d":   pct(20),
                "60d":   pct(60),
            }
        return result if result else None
    except Exception as e:
        logger.warning(f"MacroContext fast fetch failed: {e}")
        return None


def _fetch_macro_data_slow() -> Optional[Dict]:
    """
    Fetch 2 years of WEEKLY bars — strategic signals (24-hr cache).

    Weekly bars: ~104 rows per symbol vs ~520 daily — 5x lighter.
    Computes: 52W / 26W returns, 52W high-low range position,
              26W vs 52W SMA trend direction.
    """
    try:
        import yfinance as yf
        tickers = yf.Tickers(" ".join(_ALL_SYMBOLS))
        hist = tickers.history(period="2y", interval="1wk", auto_adjust=True)
        if hist.empty:
            return None

        close = hist["Close"] if "Close" in hist.columns else hist.get("close")
        if close is None or close.empty:
            return None

        result: Dict[str, Dict] = {}
        for sym in _ALL_SYMBOLS:
            if sym not in close.columns:
                continue
            series = close[sym].dropna()
            if len(series) < 10:
                continue

            price = float(series.iloc[-1])

            def wpct(n, s=series):
                if len(s) <= n:
                    return None
                return (s.iloc[-1] / s.iloc[-1 - n] - 1) * 100

            # 52W high/low range position (0–100%)
            window   = series.iloc[-52:] if len(series) >= 52 else series
            high_52w = float(window.max())
            low_52w  = float(window.min())
            rng      = high_52w - low_52w
            pos_52w  = round((price - low_52w) / rng * 100, 1) if rng > 0 else 50.0

            # Long-term trend: 26W SMA vs 52W SMA
            sma_26w  = float(series.iloc[-26:].mean()) if len(series) >= 26 else None
            sma_52w  = float(series.iloc[-52:].mean()) if len(series) >= 52 else None
            trend_up = (sma_26w > sma_52w) if (sma_26w is not None and sma_52w is not None) else None

            result[sym] = {
                "price":    price,
                "52w":      wpct(52),
                "26w":      wpct(26),
                "pos_52w":  pos_52w,
                "high_52w": high_52w,
                "low_52w":  low_52w,
                "trend_up": trend_up,
            }
        return result if result else None
    except Exception as e:
        logger.warning(f"MacroContext slow fetch failed: {e}")
        return None


# ── Formatting helpers ────────────────────────────────────────────────────────

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


def _range_bar(pos: float, width: int = 20) -> str:
    """Visual progress bar for 52W range position. E.g. [========            ] 40%"""
    pos    = max(0.0, min(100.0, pos))
    filled = round(pos / 100 * width)
    bar    = "=" * filled + " " * (width - filled)
    return f"[{bar}] {pos:.0f}%"


def _fmt(v: Optional[float]) -> str:
    return f"{v:+.1f}%" if v is not None else "  n/a "


def _trend_label(trend_up: Optional[bool]) -> str:
    if trend_up is True:
        return "LT-UPTREND"
    if trend_up is False:
        return "LT-DOWNTREND"
    return "LT-NEUTRAL"


# ── Text builder ──────────────────────────────────────────────────────────────

def _build_macro_text(data: Dict, slow_data: Optional[Dict] = None) -> str:
    """
    Format macro data into a prompt-ready text block.
    slow_data is optional — omitting it produces tactical-only output.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    ret: Dict[str, Dict[str, float]] = {}
    for sym, d in data.items():
        ret[sym] = {k: v for k, v in d.items()
                    if k in ("1d", "5d", "20d", "60d") and v is not None}

    vix_price = data.get("^VIX", {}).get("price", 18.0) or 18.0
    yield_10y = data.get("^TNX", {}).get("price", 4.5)  or 4.5

    regime, signals, sector_bias = _apply_intermarket_rules(ret, vix_price, yield_10y)
    regime_days = _update_regime_duration(regime)

    lines = [
        f"## Macro Sector Rotation Context  [{now}]",
        f"",
        f"MACRO REGIME: {regime}  "
        f"(active ~{regime_days} day{'s' if regime_days != 1 else ''})",
        f"10Y Yield: {yield_10y:.2f}%   |   VIX: {vix_price:.1f}",
        f"",
    ]

    # ── STRATEGIC CONTEXT (slow / 2-year weekly) ──────────────────────────
    if slow_data:
        insights = _compute_slow_insights(slow_data)
        lines.append("─" * 72)
        lines.append("STRATEGIC CONTEXT  (2-year weekly — is this regime structural or noise?)")
        lines.append("")

        lines.append("  Macro Proxies — 52W Range Position & Long-Term Trend:")
        for sym in ("GLD", "TLT", "UUP", "USO"):
            sd = slow_data.get(sym, {})
            if not sd:
                continue
            pos = sd.get("pos_52w")
            bar = _range_bar(pos) if pos is not None else " " * 24
            tr  = _trend_label(sd.get("trend_up"))
            lines.append(
                f"    {sym:<6}  52W:{_fmt(sd.get('52w'))}  26W:{_fmt(sd.get('26w'))}"
                f"  Range: {bar}  {tr}"
            )

        lines.append("")
        lines.append("  Sector ETFs — 52W Range Position & Long-Term Trend:")
        for sym, label in SECTOR_ETFS.items():
            sd = slow_data.get(sym, {})
            if not sd:
                continue
            pos     = sd.get("pos_52w")
            bar     = _range_bar(pos) if pos is not None else " " * 24
            tr      = _trend_label(sd.get("trend_up"))
            tac     = sector_bias.get(sym, "")
            conflict = ""
            if tac and sd.get("trend_up") is not None:
                if tac == "bullish" and not sd.get("trend_up"):
                    conflict = "  [!CONFLICT: tactical-BULL vs LT-DOWNTREND]"
                elif tac == "bearish" and sd.get("trend_up"):
                    conflict = "  [!CONFLICT: tactical-BEAR vs LT-UPTREND]"
            lines.append(
                f"    {sym:<6}  52W:{_fmt(sd.get('52w'))}"
                f"  Range: {bar}  {tr}{conflict}"
            )

        lines.append("")
        lines.append("  Market Breadth — Size Factor (52W):")
        for sym, label in BREADTH_ETFS.items():
            sd = slow_data.get(sym, {})
            if not sd:
                continue
            pos = sd.get("pos_52w")
            bar = _range_bar(pos) if pos is not None else " " * 24
            tr  = _trend_label(sd.get("trend_up"))
            lines.append(
                f"    {sym:<6}  {label:<28}  52W:{_fmt(sd.get('52w'))}"
                f"  Range: {bar}  {tr}"
            )

        if insights:
            lines.append("")
            lines.append("  KEY STRATEGIC INSIGHTS:")
            for ins in insights:
                lines.append(f"    • {ins}")
        lines.append("─" * 72)
        lines.append("")

    # ── TACTICAL SIGNALS ──────────────────────────────────────────────────
    if signals:
        lines.append("INTER-MARKET SIGNALS (John Murphy / Bridgewater framework):")
        for s in signals:
            lines.append(f"  • {s}")
        lines.append("")

    # ── Macro proxy table (tactical) ──────────────────────────────────────
    lines.append("MACRO PROXY PERFORMANCE (1D / 5D / 20D / 60D):")
    for sym, label in MACRO_PROXIES.items():
        d = data.get(sym, {})
        if not d:
            continue
        arrow = _momentum_arrow(d.get("5d"), d.get("20d"))
        lines.append(
            f"  {sym:<6} {label:<42}"
            f"{_fmt(d.get('1d'))} / {_fmt(d.get('5d'))} / "
            f"{_fmt(d.get('20d'))} / {_fmt(d.get('60d'))}  {arrow}"
        )
    lines.append("")

    # ── Sector ETF table (tactical) ───────────────────────────────────────
    lines.append("SECTOR ETF PERFORMANCE (1D / 5D / 20D / 60D)  [inter-market bias]:")
    for sym, label in SECTOR_ETFS.items():
        d = data.get(sym, {})
        if not d:
            continue
        arrow    = _momentum_arrow(d.get("5d"), d.get("20d"))
        bias     = sector_bias.get(sym, "")
        bias_tag = f"  ← {bias.upper()}" if bias else ""
        lines.append(
            f"  {sym:<6} {label:<24}"
            f"{_fmt(d.get('1d'))} / {_fmt(d.get('5d'))} / "
            f"{_fmt(d.get('20d'))} / {_fmt(d.get('60d'))}  {arrow}{bias_tag}"
        )
    lines.append("")

    # ── Market breadth table (tactical) ──────────────────────────────────
    lines.append("MARKET BREADTH (1D / 5D / 20D / 60D):")
    for sym, label in BREADTH_ETFS.items():
        d = data.get(sym, {})
        if not d:
            continue
        arrow = _momentum_arrow(d.get("5d"), d.get("20d"))
        lines.append(
            f"  {sym:<6} {label:<28}"
            f"{_fmt(d.get('1d'))} / {_fmt(d.get('5d'))} / "
            f"{_fmt(d.get('20d'))} / {_fmt(d.get('60d'))}  {arrow}"
        )
    lines.append("")

    # ── Trading implications ──────────────────────────────────────────────
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
    if slow_data:
        lines.append(
            "  Check CONFLICT flags above: a tactical headwind against a "
            "long-term uptrend may be a buying opportunity, not a sell signal."
        )

    return "\n".join(lines)


# ── Public async API ──────────────────────────────────────────────────────────

async def get_macro_context_text() -> str:
    """
    Return a formatted macro context string for injection into AI prompts.

    Fast path (15 min cache): tactical 1D/5D/20D/60D signals.
    Slow path (24 hr cache):  strategic 52W range, trend, breadth insights.

    Returns stale cache text on fetch failure rather than empty string.
    """
    global _fast_cache_text, _fast_cache_ts, _slow_cache_data, _slow_cache_ts

    now  = time.time()
    loop = asyncio.get_event_loop()

    # ── Refresh slow cache if stale (24 hr) ──────────────────────────────
    slow_data = _slow_cache_data
    if not slow_data or (now - _slow_cache_ts) >= _SLOW_CACHE_SECONDS:
        try:
            fresh_slow = await loop.run_in_executor(None, _fetch_macro_data_slow)
            if fresh_slow:
                _slow_cache_data = fresh_slow
                _slow_cache_ts   = now
                slow_data        = fresh_slow
                logger.info("MacroContext: slow cache refreshed (2Y weekly, %d symbols)", len(fresh_slow))
            else:
                logger.warning("MacroContext: slow fetch returned no data — using stale")
        except Exception as e:
            logger.warning("MacroContext: slow fetch error: %s", e)

    # ── Return fast cache if still valid ──────────────────────────────────
    if _fast_cache_text and (now - _fast_cache_ts) < _FAST_CACHE_SECONDS:
        return _fast_cache_text

    # ── Refresh fast cache ────────────────────────────────────────────────
    try:
        fast_data = await loop.run_in_executor(None, _fetch_macro_data)
        if not fast_data:
            logger.warning("MacroContext: fast fetch returned no data — using stale")
            return _fast_cache_text

        text = _build_macro_text(fast_data, slow_data)
        _fast_cache_text = text
        _fast_cache_ts   = now
        logger.info("MacroContext: fast cache refreshed (%d instruments)", len(fast_data))
        return text
    except Exception as e:
        logger.warning("MacroContext: error building context: %s", e)
        return _fast_cache_text
