"""
Signal Aggregator: combines multiple independent data sources into a
weighted composite signal with a validity/confidence score.

Sources and weights:
  - Analyst consensus    (yfinance)   weight=0.35  — professional opinion
  - Earnings surprise    (yfinance)   weight=0.22  — fundamental momentum
  - Alpaca news          (alpaca)     weight=0.18  — breaking catalysts
  - Yahoo Finance news   (yfinance)   weight=0.12  — additional coverage
  - Congressional trades (SEC EDGAR) weight=0.13  — smart-money signal

Each source emits a score in [-1, +1]:
  -1 = strongly bearish   0 = neutral   +1 = strongly bullish

Agreement across sources raises confidence; disagreement lowers it.
"""
import asyncio
import logging
import time
import math
from typing import Dict, List, Optional, Tuple

from data import finbert_scorer

logger = logging.getLogger(__name__)

# Suppress yfinance's verbose HTTP error logging — we handle errors ourselves
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

# Limit concurrent yfinance threads. Without this, asyncio.gather over 60 symbols
# spawns 60 simultaneous threads, each doing HTTP + pandas CPU work → 90%+ CPU.
# 8 concurrent fetches keeps throughput high while leaving headroom for Ollama + UI.
_YF_SEMAPHORE: asyncio.Semaphore = asyncio.Semaphore(8)

# ETFs and funds that have no analyst/earnings fundamentals
_ETF_SYMBOLS = {
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "GLD", "SLV",
    "TLT", "IEF", "HYG", "LQD", "EFA", "EEM", "VEA", "XLF",
    "XLK", "XLE", "XLV", "XLI", "XLU", "ARKK", "ARKG",
}

# Cache yfinance data for 15 minutes (it's slow and rate-limited)
YF_CACHE_TTL = 900
_yf_cache: Dict[str, Tuple[float, Dict]] = {}

# Source weights (must sum to 1.0)
# iv_rv_spread added as a fresh real-time source; existing weights scaled proportionally.
SOURCE_WEIGHTS = {
    "analyst_consensus":   0.30,
    "earnings_surprise":   0.19,
    "alpaca_news":         0.15,
    "yahoo_news":          0.10,
    "congressional_trades": 0.11,
    "iv_rv_spread":        0.15,   # IV minus RV_20d; high fear → bearish, low fear → bullish
}

# Sources excluded from the composite score — shown to the LLM as context only.
# earnings_surprise: quarterly cadence (stale for 90+ days between reports)
# congressional_trades: SEC EDGAR Form 4 has a 90-day reporting window; filings
#   can reflect trades from months ago and must not gate live decisions.
CONTEXT_ONLY_SOURCES = {"earnings_surprise", "congressional_trades"}
_FRESH_SOURCES = {"analyst_consensus", "alpaca_news", "yahoo_news", "iv_rv_spread"}

# Normalisation divisor for IV/RV spread → [-1, +1]:
# A spread of ±0.20 (20 pp) maps to ±1.0.  Larger spreads are clamped.
_IV_RV_NORM = 0.20

# Simple bullish/bearish keyword sets for news scoring
_BULLISH_WORDS = {
    "beat", "beats", "record", "upgrade", "upgraded", "outperform", "raised",
    "growth", "profit", "surge", "soar", "rally", "strong", "positive",
    "partnership", "launch", "win", "wins", "approved", "approval",
    "dividend", "buyback", "expansion",
}
_BEARISH_WORDS = {
    "miss", "misses", "downgrade", "downgraded", "underperform", "lowered",
    "loss", "losses", "decline", "fell", "fall", "weak", "negative",
    "lawsuit", "investigation", "recall", "cut", "cuts", "layoff", "layoffs",
    "concern", "risk", "warning", "slump", "disappoint",
}


def _score_headlines(articles: List[Dict]) -> Optional[float]:
    """Score a list of news articles in [-1, +1] using keyword matching.
    Retained as a fallback for `_score_yahoo_news` when FinBERT is
    unavailable; previously the only scorer for the yahoo_news channel."""
    if not articles:
        return None
    scores = []
    for a in articles:
        text = (a.get("headline", "") + " " + a.get("summary", "")).lower()
        words = set(text.split())
        bull = len(words & _BULLISH_WORDS)
        bear = len(words & _BEARISH_WORDS)
        total = bull + bear
        if total > 0:
            scores.append((bull - bear) / total)
    return sum(scores) / len(scores) if scores else None


def _score_yahoo_news(articles: List[Dict]) -> Optional[float]:
    """Score yahoo_news headlines via FinBERT, with the keyword counter as a
    fallback when FinBERT is unavailable. Task #21 swap — the keyword
    scorer's directional hit-rate (49.1%, corr +0.024) was indistinguishable
    from random; FinBERT (ProsusAI/finbert, Apache 2.0) replaces it as the
    primary scorer for the CNN's `yahoo_news` input channel."""
    if not articles:
        return None
    score = finbert_scorer.score_headlines(articles)
    if score is not None:
        return score
    return _score_headlines(articles)


def _fetch_yf_data_sync(symbol: str) -> Dict:
    """Synchronous yfinance fetch — run via asyncio.to_thread."""
    import yfinance as yf
    ticker = yf.Ticker(symbol)
    result = {}
    is_etf = symbol.upper() in _ETF_SYMBOLS

    # ── Analyst consensus (stocks only) ────────────────────────────────
    if is_etf:
        logger.debug(f"yfinance: skipping fundamentals for ETF {symbol}")
    if not is_etf:
        try:
            rec = ticker.recommendations
            if rec is not None and not rec.empty:
                latest = rec.iloc[0]
                strong_buy = int(latest.get("strongBuy", 0))
                buy        = int(latest.get("buy", 0))
                hold       = int(latest.get("hold", 0))
                sell       = int(latest.get("sell", 0))
                strong_sell= int(latest.get("strongSell", 0))
                total = strong_buy + buy + hold + sell + strong_sell
                if total > 0:
                    raw = (strong_buy * 1.0 + buy * 0.5 - sell * 0.5 - strong_sell * 1.0) / total
                    result["analyst_score"]   = round(raw, 3)
                    result["analyst_total"]   = total
                    result["analyst_bull"]    = strong_buy + buy
                    result["analyst_hold"]    = hold
                    result["analyst_bear"]    = sell + strong_sell
                    result["analyst_target"]  = ticker.info.get("targetMeanPrice")
        except Exception as e:
            logger.debug(f"yfinance analyst data failed for {symbol}: {e}")

    # ── Earnings surprise (stocks only) ───────────────────────────────
    if not is_etf:
        try:
            hist = ticker.earnings_history
            if hist is not None and not hist.empty:
                recent = hist.tail(2)
                surprises = recent["surprisePercent"].dropna().tolist()
                if surprises:
                    avg_surprise = sum(surprises) / len(surprises)
                    score = max(-1.0, min(1.0, avg_surprise / 0.20))
                    result["earnings_surprise_score"] = round(score, 3)
                    result["earnings_surprise_pct"]   = round(avg_surprise * 100, 2)
        except Exception as e:
            logger.debug(f"yfinance earnings data failed for {symbol}: {e}")

    # ── Yahoo Finance news ─────────────────────────────────────────────
    try:
        news_raw = ticker.news or []
        articles = []
        for item in news_raw[:8]:
            content = item.get("content", {})
            headline = content.get("title", "")
            summary  = content.get("summary", "")
            if headline:
                articles.append({"headline": headline, "summary": summary})
        result["yahoo_news"] = articles
        score = _score_yahoo_news(articles)
        if score is not None:
            result["yahoo_news_score"] = round(score, 3)
    except Exception as e:
        logger.debug(f"yfinance news failed for {symbol}: {e}")

    # ── IV / RV spread ─────────────────────────────────────────────────────
    # Compares near-ATM implied volatility against 20-day realized vol.
    # Both are annualized (252-day basis).  Score interpretation:
    #   IV >> RV  → market is fearful / hedging → bearish lean → negative score
    #   IV ~= RV  → fair pricing → neutral
    #   IV << RV  → complacency / vol may expand → negative score (risk-off)
    # Scoring: score = -clamp(spread / _IV_RV_NORM, -1, 1)
    try:
        import numpy as _np
        hist_iv = ticker.history(period="3mo")
        exps = ticker.options if hasattr(ticker, "options") else ()
        if not hist_iv.empty and len(hist_iv) >= 21 and exps:
            closes = hist_iv["Close"].values.astype(float)
            log_rets = _np.log(closes[1:] / _np.where(closes[:-1] > 0, closes[:-1], _np.nan))
            log_rets = log_rets[_np.isfinite(log_rets)]
            if len(log_rets) >= 20:
                rv_20d = float(log_rets[-20:].std() * _np.sqrt(252))
                chain = ticker.option_chain(exps[0])
                calls = chain.calls
                spot  = float(closes[-1])
                if not calls.empty and spot > 0:
                    calls = calls.copy()
                    calls["_dist"] = abs(calls["strike"] - spot)
                    atm = calls.nsmallest(1, "_dist").iloc[0]
                    iv  = atm.get("impliedVolatility")
                    if iv is not None and _np.isfinite(float(iv)) and float(iv) > 0:
                        iv     = float(iv)
                        spread = iv - rv_20d
                        score  = -max(-1.0, min(1.0, spread / _IV_RV_NORM))
                        result["iv_atm"]       = round(iv, 4)
                        result["rv_20d_iv"]    = round(rv_20d, 4)
                        result["iv_rv_spread"] = round(spread, 4)
                        result["iv_rv_score"]  = round(score, 3)
    except Exception as e:
        logger.debug(f"yfinance IV/RV failed for {symbol}: {e}")

    return result


async def _get_yf_data(symbol: str) -> Dict:
    """Return cached yfinance data, refreshing if stale.

    Guarded by _YF_SEMAPHORE so at most 8 yfinance threads run simultaneously,
    preventing CPU saturation when the scanner gathers 60 symbols at once.
    """
    now = time.time()
    if symbol in _yf_cache:
        ts, data = _yf_cache[symbol]
        if now - ts < YF_CACHE_TTL:
            return data
    try:
        async with _YF_SEMAPHORE:
            data = await asyncio.to_thread(_fetch_yf_data_sync, symbol)
        _yf_cache[symbol] = (now, data)
        return data
    except Exception as e:
        logger.error(f"signal_aggregator: yfinance fetch failed for {symbol}: {e}")
        return _yf_cache.get(symbol, (0, {}))[1]


def _aggregate_scores(
    analyst_score:        Optional[float],
    earnings_score:       Optional[float],
    alpaca_news_score:    Optional[float],
    yahoo_news_score:     Optional[float],
    congressional_score:  Optional[float] = None,
    iv_rv_score:          Optional[float] = None,
) -> Tuple[float, float, str]:
    """
    Compute weighted composite score and confidence.
    Returns (composite_score, confidence, verdict_text).

    Only fresh sources (analyst_consensus, alpaca_news, yahoo_news) are
    included in the composite score.  earnings_surprise and congressional_trades
    are accepted for API compatibility but are CONTEXT_ONLY_SOURCES — they are
    shown to the LLM as context, never used to compute composite or gate trades.
    """
    all_sources = {
        "analyst_consensus":    analyst_score,
        "earnings_surprise":    earnings_score,
        "alpaca_news":          alpaca_news_score,
        "yahoo_news":           yahoo_news_score,
        "congressional_trades": congressional_score,
        "iv_rv_spread":         iv_rv_score,
    }

    # Only fresh sources drive the composite score
    fresh_available = {
        k: v for k, v in all_sources.items()
        if k not in CONTEXT_ONLY_SOURCES and v is not None
    }
    if not fresh_available:
        return 0.0, 0.0, "No fresh signal data available"

    # Normalise weights to available fresh sources
    total_weight = sum(SOURCE_WEIGHTS[k] for k in fresh_available)
    composite = sum(SOURCE_WEIGHTS[k] * v for k, v in fresh_available.items()) / total_weight

    # Confidence: how well fresh sources agree (1 - normalised std dev)
    values = list(fresh_available.values())
    if len(values) > 1:
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        std = math.sqrt(variance)
        agreement = max(0.0, 1.0 - std)  # std=0 → perfect agreement=1
    else:
        agreement = 0.5  # only one source, moderate confidence

    # Scale agreement by fresh source coverage
    source_coverage = len(fresh_available) / len(_FRESH_SOURCES)
    confidence = round(agreement * source_coverage, 3)

    # Verdict
    if composite >= 0.4:     verdict = "BULLISH"
    elif composite >= 0.15:  verdict = "MILDLY BULLISH"
    elif composite <= -0.4:  verdict = "BEARISH"
    elif composite <= -0.15: verdict = "MILDLY BEARISH"
    else:                    verdict = "NEUTRAL"

    if confidence < 0.35:
        verdict += " (LOW CONFIDENCE — sources conflict)"
    elif confidence > 0.70:
        verdict += " (HIGH CONFIDENCE — sources agree)"

    return round(composite, 3), confidence, verdict


async def get_composite_signal(symbol: str, alpaca_news: List[Dict]) -> Dict:
    """
    Fetch all sources, score them, and return a composite signal dict.
    alpaca_news: list of article dicts already fetched by news_service.
    """
    from data.congressional_trading import get_congressional_signal

    yf_data, congress_data = await asyncio.gather(
        _get_yf_data(symbol),
        get_congressional_signal(symbol),
        return_exceptions=True,
    )
    # Defense in depth: gather with return_exceptions=True can hand back
    # an Exception in place of a dict if either coroutine raised. Coerce
    # to {} so downstream `.get(...)` calls don't crash with the diagnosis-
    # eating "'NoneType' object has no attribute 'get'" error we saw on
    # 2026-04-28 across many symbols (Backlog 0.3).
    if not isinstance(yf_data, dict):
        logger.warning(f"signal_aggregator: yf_data fallback to {{}} for {symbol} ({type(yf_data).__name__}: {yf_data!r:.120})")
        yf_data = {}
    if not isinstance(congress_data, dict):
        logger.warning(f"signal_aggregator: congress_data fallback to {{}} for {symbol} ({type(congress_data).__name__}: {congress_data!r:.120})")
        congress_data = {}

    alpaca_score      = _score_headlines(alpaca_news)
    analyst_score     = yf_data.get("analyst_score")
    earnings_score    = yf_data.get("earnings_surprise_score")
    yahoo_score       = yf_data.get("yahoo_news_score")
    congress_score    = congress_data.get("score")
    iv_rv_score       = yf_data.get("iv_rv_score")

    composite, confidence, verdict = _aggregate_scores(
        analyst_score, earnings_score, alpaca_score, yahoo_score,
        congressional_score=congress_score, iv_rv_score=iv_rv_score,
    )

    return {
        "symbol":            symbol,
        "composite_score":   composite,
        "confidence":        confidence,
        "verdict":           verdict,
        "sources": {
            "analyst_consensus": {
                "score":       analyst_score,
                "weight":      SOURCE_WEIGHTS["analyst_consensus"],
                "bull":        yf_data.get("analyst_bull"),
                "hold":        yf_data.get("analyst_hold"),
                "bear":        yf_data.get("analyst_bear"),
                "total":       yf_data.get("analyst_total"),
                "price_target":yf_data.get("analyst_target"),
            },
            "earnings_surprise": {
                "score":       earnings_score,
                "weight":      SOURCE_WEIGHTS["earnings_surprise"],
                "surprise_pct":yf_data.get("earnings_surprise_pct"),
            },
            "alpaca_news": {
                "score":       alpaca_score,
                "weight":      SOURCE_WEIGHTS["alpaca_news"],
                "articles":    len(alpaca_news),
            },
            "yahoo_news": {
                "score":       yahoo_score,
                "weight":      SOURCE_WEIGHTS["yahoo_news"],
                "articles":    len(yf_data.get("yahoo_news", [])),
            },
            "congressional_trades": {
                "score":           congress_score,
                "weight":          SOURCE_WEIGHTS["congressional_trades"],
                "congress_buys":   congress_data.get("congress_buys", 0),
                "congress_sells":  congress_data.get("congress_sells", 0),
                "congress_total":  congress_data.get("congress_total", 0),
                "total_filings":   congress_data.get("total_filings", 0),
                "window_days":     congress_data.get("window_days", 90),
            },
            "iv_rv_spread": {
                "score":       iv_rv_score,
                "weight":      SOURCE_WEIGHTS["iv_rv_spread"],
                "iv_atm":      yf_data.get("iv_atm"),
                "rv_20d":      yf_data.get("rv_20d_iv"),
                "spread":      yf_data.get("iv_rv_spread"),
            },
        },
        "yahoo_news_headlines": [
            a["headline"] for a in yf_data.get("yahoo_news", [])[:3]
        ],
    }


def format_for_prompt(signal: Dict) -> str:
    """Format composite signal as text for Claude's prompt."""
    if not signal:
        return "External signal: unavailable"

    verdict    = signal.get("verdict", "N/A")
    composite  = signal.get("composite_score", 0)
    confidence = signal.get("confidence", 0)
    sources    = signal.get("sources", {})

    analyst = sources.get("analyst_consensus", {})
    earnings= sources.get("earnings_surprise", {})
    alpaca  = sources.get("alpaca_news", {})
    yahoo   = sources.get("yahoo_news", {})

    lines = [
        f"  Composite: {composite:+.2f} | Verdict: {verdict} | Confidence: {confidence:.0%}",
        f"  Sources (weight → score):",
    ]

    if analyst.get("score") is not None:
        bull = analyst.get("bull", 0)
        hold = analyst.get("hold", 0)
        bear = analyst.get("bear", 0)
        target = analyst.get("price_target")
        target_str = f" | Target: ${target:.2f}" if target else ""
        lines.append(
            f"    Analyst consensus   (35%): {analyst['score']:+.2f} — "
            f"{bull} buy / {hold} hold / {bear} sell{target_str}"
        )
    else:
        lines.append("    Analyst consensus   (35%): no data")

    if earnings.get("score") is not None:
        lines.append(
            f"    Earnings surprise   (22%): {earnings['score']:+.2f} — "
            f"avg EPS surprise {earnings.get('surprise_pct', 0):+.1f}%  [CONTEXT ONLY — quarterly]"
        )
    else:
        lines.append("    Earnings surprise   (22%): no data  [CONTEXT ONLY — quarterly]")

    if alpaca.get("score") is not None:
        lines.append(
            f"    Alpaca news         (18%): {alpaca['score']:+.2f} — "
            f"{alpaca.get('articles', 0)} article(s)"
        )
    else:
        lines.append("    Alpaca news         (18%): no signal")

    if yahoo.get("score") is not None:
        lines.append(
            f"    Yahoo Finance news (12%): {yahoo['score']:+.2f} — "
            f"{yahoo.get('articles', 0)} article(s)"
        )
    else:
        lines.append("    Yahoo Finance news (12%): no signal")

    congress = sources.get("congressional_trades", {})
    if congress.get("score") is not None:
        c_buys  = congress.get("congress_buys", 0)
        c_sells = congress.get("congress_sells", 0)
        lines.append(
            f"    Congressional trades (11%): {congress['score']:+.2f} — "
            f"{c_buys} buy / {c_sells} sell (SEC EDGAR Form 4, 90 days)  [CONTEXT ONLY — 90-day window]"
        )
    else:
        lines.append("    Congressional trades (11%): no filings found  [CONTEXT ONLY — 90-day window]")

    iv_rv = sources.get("iv_rv_spread", {})
    if iv_rv.get("score") is not None:
        iv_val  = iv_rv.get("iv_atm")
        rv_val  = iv_rv.get("rv_20d_iv")
        spread  = iv_rv.get("iv_rv_spread")
        iv_str  = f"IV={iv_val:.1%} RV={rv_val:.1%} spread={spread:+.1%}" if (
            iv_val is not None and rv_val is not None and spread is not None
        ) else ""
        lines.append(
            f"    IV/RV spread        (15%): {iv_rv['score']:+.2f}"
            + (f" — {iv_str}" if iv_str else "")
        )
    else:
        lines.append("    IV/RV spread        (15%): no options data")

    extra_headlines = signal.get("yahoo_news_headlines", [])
    if extra_headlines:
        lines.append("  Yahoo headlines: " + " | ".join(extra_headlines[:2]))

    return "\n".join(lines)
