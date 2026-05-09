"""
ScannerAgent — Multi-agent parallel stock scanner powered by Claude, Gemini, and Ollama.

How it works:
  1. Pre-screener: fetches daily bars for ~160 universe symbols from Alpaca,
     ranks by 1-day momentum + volume surge → picks top 20 candidates.
  2. Parallel AI scan: splits candidates across available AI providers and
     runs all agentic tool-use loops concurrently via asyncio.gather.
     - Claude Opus   → top candidates  (highest conviction, second-opinion quality)
     - Gemini Flash  → middle tier     (cheap, fast, free tier available)
     - Ollama local  → lower tier      (zero token cost, runs on local GPU/CPU)
  3. Recommendations are merged, deduplicated by symbol (highest confidence
     wins), capped at MAX_RECOMMENDATIONS, cached for 30 minutes.

Tools available to each AI:
  - get_stock_analysis(symbol)     → composite signal + technicals + news
  - get_sector_leaders(sector)     → top momentum stocks in a sector
  - add_recommendation(...)        → submit a final BUY/SELL/WATCH pick

The scanner runs independently — it does NOT trade; it only recommends.
"""
import asyncio
import json
import logging
import math
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import save_token_log, get_daily_token_total

logger = logging.getLogger(__name__)

SCAN_CACHE_TTL  = 30 * 60  # 30 minutes — default TTL for tokenized agents (Claude/Gemini/OpenAI)
OLLAMA_SCAN_TTL =  5 * 60  # 5 minutes — shorter TTL for free local Ollama scans
MAX_TOOL_ROUNDS = 6         # safety ceiling per agent
MAX_RECOMMENDATIONS = 8     # final output limit after merge

# Persist scans here so results survive restarts
_CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "scan_cache.json")

# Append-only JSONL of every scanner runner's input + output. Enables
# offline Claude-vs-Ollama overlap analysis + per-scanner value attribution
# (link each recommendation to subsequent trades). One line per scanner
# call. Created lazily on first write.
_SCANNER_RECS_LOG = os.path.join(
    os.path.dirname(__file__), "..", "logs", "scanner_recs.jsonl",
)


def _append_scanner_recs_log(
    scanner: str,
    model: str,
    candidates: List[Dict],
    recommendations: List[Dict],
) -> None:
    """Append one JSONL row to backend/logs/scanner_recs.jsonl.

    scanner             — "Claude" | "Ollama" | "OpenAI" | "Gemini"
    model               — exact model id used (claude-opus-4-6, llama3.1:8b, etc)
    candidates          — pre-screened input list (full dicts; we record symbols only)
    recommendations     — output list from _run_*_scanner

    Best-effort: any disk failure is logged at debug level and swallowed —
    instrumentation must never crash the scanner.
    """
    try:
        os.makedirs(os.path.dirname(_SCANNER_RECS_LOG), exist_ok=True)
        row = {
            "ts":               datetime.now(timezone.utc).isoformat(),
            "scanner":          scanner,
            "model":            model,
            "n_candidates":     len(candidates),
            "candidate_symbols": [c.get("symbol") for c in candidates if isinstance(c, dict)],
            "n_recs":           len(recommendations),
            "recs":             list(recommendations),
        }
        with open(_SCANNER_RECS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
    except Exception as exc:
        logger.debug(f"scanner_recs_log write failed ({scanner}): {exc}")

_cache: Optional[Dict] = None
_cache_ts: float = 0.0
_scan_in_progress: bool = False
_scan_lock = asyncio.Lock()  # prevents duplicate concurrent scans wasting API quota

# Ring buffer of recent scan durations (seconds) for telemetry
from collections import deque as _deque
_scan_history: _deque = _deque(maxlen=20)

# Per-scan pull tracking — reset at the start of each scan, read at the end
_pull_hits:   int = 0
_pull_misses: int = 0


def _reset_pull_stats() -> None:
    global _pull_hits, _pull_misses
    _pull_hits   = 0
    _pull_misses = 0


def _record_pull(symbol: str, success: bool) -> None:
    global _pull_hits, _pull_misses
    if success:
        _pull_hits += 1
    else:
        _pull_misses += 1
        logger.debug(f"Scanner pull miss: {symbol} — no bars/composite data")


def _get_pull_stats() -> Dict:
    total = _pull_hits + _pull_misses
    pct   = round((_pull_hits / total * 100) if total else 0.0, 1)
    return {"hits": _pull_hits, "misses": _pull_misses, "total": total, "success_pct": pct}


def _save_cache_to_disk(data: Dict) -> None:
    """Write scan result to disk so it survives restarts."""
    try:
        os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
        with open(_CACHE_FILE, "w") as f:
            json.dump(data, f, default=str)
    except Exception as e:
        logger.warning(f"Scanner: could not save cache to disk: {e}")


def _load_cache_from_disk() -> None:
    """Load last scan from disk into memory on startup."""
    global _cache, _cache_ts
    try:
        if not os.path.exists(_CACHE_FILE):
            return
        with open(_CACHE_FILE) as f:
            data = json.load(f)
        # Parse scanned_at to reconstruct cache timestamp
        scanned_at = data.get("scanned_at")
        if scanned_at:
            from datetime import timezone
            dt = datetime.fromisoformat(scanned_at)
            # treat as UTC
            ts = dt.replace(tzinfo=timezone.utc).timestamp()
        else:
            ts = 0.0
        _cache = data
        _cache_ts = ts
        age_min = (time.time() - ts) / 60
        logger.info(f"Scanner: loaded persisted cache from disk (age {age_min:.0f} min)")
    except Exception as e:
        logger.warning(f"Scanner: could not load cache from disk: {e}")


# Load persisted cache immediately on import
_load_cache_from_disk()

# ── Optional SDK imports ───────────────────────────────────────────────────────

try:
    from google import genai as _genai
    from google.genai import types as _genai_types
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

try:
    from openai import AsyncOpenAI as _AsyncOpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

# ── Tool definitions (Claude / OpenAI JSON Schema format) ─────────────────────

TOOLS = [
    {
        "name": "get_stock_analysis",
        "description": (
            "Get a deep analysis for a single stock symbol including: "
            "composite signal score (-1 to +1), analyst consensus, earnings surprise, "
            "news sentiment, congressional trade activity, RSI, MACD, Bollinger position, "
            "SMA trend, ATR, volume ratio, and latest price. "
            "Use this to evaluate a candidate before recommending it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Stock ticker symbol, e.g. AAPL",
                }
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_sector_leaders",
        "description": (
            "Get the top momentum stocks in a market sector from the universe. "
            "Returns up to 10 stocks sorted by 1-day price change and volume surge. "
            "Use this to discover candidates in a sector you want to explore."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sector": {
                    "type": "string",
                    "description": (
                        "One of: Technology, Healthcare, Finance, Energy, "
                        "Consumer_Discretionary, Consumer_Staples, Industrial, "
                        "Communication, Materials, ETF_Sectors"
                    ),
                }
            },
            "required": ["sector"],
        },
    },
    {
        "name": "add_recommendation",
        "description": (
            "Submit a final trading recommendation for a stock. "
            "Call this once you are confident in your analysis. "
            "You may submit up to 8 recommendations total — focus on high-conviction picks only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Stock ticker symbol",
                },
                "action": {
                    "type": "string",
                    "enum": ["BUY", "SELL", "WATCH"],
                    "description": "BUY = bullish opportunity, SELL = bearish/exit signal, WATCH = flagged but not actionable yet",
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "Conviction level 0.0 to 1.0",
                },
                "reasoning": {
                    "type": "string",
                    "description": "Concise explanation of why this stock is recommended (2-4 sentences)",
                },
                "composite_score": {
                    "type": "number",
                    "description": "Composite signal score from get_stock_analysis (-1 to +1)",
                },
                "price_target": {
                    "type": "number",
                    "description": "Optional analyst price target (if available from analysis)",
                },
                "stop_loss_pct": {
                    "type": "number",
                    "description": "Suggested stop-loss percentage below entry, e.g. 5 for 5%",
                },
                "catalysts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of 2-4 key catalysts or signals driving this recommendation",
                },
            },
            "required": ["symbol", "action", "confidence", "reasoning", "composite_score"],
        },
    },
]

# ── Shared prompt & cached API structures ────────────────────────────────────

_SYSTEM_PROMPT = """You are an elite quantitative stock scanner AI with access to real-time market data tools.

Your mission: identify the BEST trading opportunities in the market today.

Decision framework:
- BUY signals require: bullish composite score (>+0.15), RSI not overbought (<70), confirmed by at least 2 sources
- SELL signals require: bearish composite score (<-0.15), RSI not oversold (>30), confirmed by at least 2 sources
- WATCH: interesting setup but missing confirmation — flag for monitoring
- SKIP: insufficient signal, conflicting data, or no edge

Process:
1. Review the pre-screened momentum candidates below (primary + fallback pool)
2. Start with your PRIMARY candidates — these are the highest-momentum symbols assigned to you
3. Use get_stock_analysis to deep-dive into each candidate in order
4. IMPORTANT: If get_stock_analysis returns data_available=false or an error field, SKIP that symbol
   immediately and move to the next candidate in the list — do not waste a recommendation on bad data
5. Once you exhaust primary candidates, continue with FALLBACK candidates if you need more picks
6. Use get_sector_leaders if you want to explore a sector for additional ideas
7. Call add_recommendation for each high-conviction pick (max 8 total)
8. Prioritise quality over quantity — only recommend when you have clear conviction

Always check composite score, RSI, MACD, and volume confirmation before recommending."""

# Cached system block — sent once; subsequent rounds hit the cache at 0.1× cost
_CACHED_SYSTEM = [
    {"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
]

# Tools list with cache_control on the last entry — tool definitions are fully
# static and expensive to re-encode on every tool-use round (up to 12 rounds/scan)
_TOOLS_WITH_CACHE: List[Dict] = [
    {**tool, **({"cache_control": {"type": "ephemeral"}} if i == len(TOOLS) - 1 else {})}
    for i, tool in enumerate(TOOLS)
]


def _build_user_message(
    primary: List[Dict],
    fallback: List[Dict] = None,
    sector_summary: str = "",
) -> str:
    def _fmt(c: Dict) -> str:
        trend = c.get("trend_multiplier")
        trend_str = f"  trend×{trend:.2f}" if trend is not None and trend != 1.0 else ""
        return (
            f"  {c['symbol']:6s}  {c['pct_change']:+.2f}%  vol\u00d7{c['vol_ratio']:.1f}  "
            f"momentum={c['momentum_score']:.2f}{trend_str}"
        )

    primary_block = "\n".join(_fmt(c) for c in primary)
    sector_block  = f"\n## Sector Performance\n{sector_summary}\n" if sector_summary else ""

    fallback_block = ""
    if fallback:
        fallback_lines = "\n".join(_fmt(c) for c in fallback)
        fallback_block = (
            f"\n\n## FALLBACK candidates (use if primary data pulls fail):\n{fallback_lines}"
        )

    return (
        f"{sector_block}"
        f"## PRIMARY candidates — analyse these first (highest momentum, assigned to you):\n\n"
        f"{primary_block}"
        f"{fallback_block}\n\n"
        "Work through PRIMARY candidates in order using get_stock_analysis. "
        "If a symbol returns data_available=false or an error, skip it and move to the next. "
        "Use FALLBACK candidates if you need more picks after exhausting primary. "
        "Use get_sector_leaders to explore sectors that are outperforming. "
        "Submit recommendations only for high-conviction picks with clear catalysts."
    )


# ── Tool execution ─────────────────────────────────────────────────────────────

async def _tool_get_stock_analysis(symbol: str) -> Dict:
    """Execute get_stock_analysis tool: pull composite signal + technicals.

    Always returns a dict with ``data_available`` (bool) so AI agents can
    skip symbols with no usable data without wasting a recommendation slot.
    """
    from data.signal_aggregator import get_composite_signal
    from data.news_service import news_service
    from data import technicals
    from trading.alpaca_client import alpaca_client

    symbol = symbol.upper().strip()
    try:
        news_task   = news_service.get_news(symbol)
        bars_task   = alpaca_client.get_bars(symbol, limit=10)
        news, bars  = await asyncio.gather(news_task, bars_task, return_exceptions=False)

        sig = await get_composite_signal(symbol, news if isinstance(news, list) else [])
        sig = sig or {}   # guard: get_composite_signal returns None when all sources fail

        ind   = {}
        price = None
        has_bars = bars is not None and not bars.empty and len(bars) >= 1
        if has_bars:
            ind   = technicals.compute(bars)
            price = float(bars["close"].iloc[-1]) if "close" in bars.columns else None

        # A pull is considered successful when we have bars or a non-null composite score
        data_available = has_bars or sig.get("composite_score") is not None

        _record_pull(symbol, success=data_available)

        return {
            "symbol":            symbol,
            "data_available":    data_available,
            "price":             price,
            "composite_score":   sig.get("composite_score"),
            "confidence":        sig.get("confidence"),
            "verdict":           sig.get("verdict"),
            "sources":           sig.get("sources", {}),
            "indicators": {
                "rsi":          ind.get("rsi"),
                "macd":         ind.get("macd"),
                "macd_signal":  ind.get("macd_signal"),
                "bb_position":  ind.get("bb_position"),
                "sma20":        ind.get("sma20"),
                "sma50":        ind.get("sma50"),
                "atr":          ind.get("atr"),
                "volume_ratio": ind.get("volume_ratio"),
            },
            "recent_news_count": len(news) if isinstance(news, list) else 0,
        }
    except Exception as e:
        # exc_info=True captures the stack trace so we can pinpoint the
        # source of "'NoneType' object has no attribute 'get'"-style errors
        # instead of just the symptom (Backlog 0.3, 2026-04-29).
        logger.warning(
            f"scanner tool get_stock_analysis({symbol}): {e}",
            exc_info=True,
        )
        _record_pull(symbol, success=False)
        return {"symbol": symbol, "data_available": False, "error": str(e)}


def _extract_snapshot_fields(snap: Dict):
    """
    Safely extract price/volume from a model_dump() snapshot dict.
    Returns (price, prev_close, day_volume, prev_volume) — any may be None.
    """
    price      = None
    prev_close = None
    day_vol    = None
    prev_vol   = None
    try:
        lt = snap.get("latest_trade") or {}
        price = lt.get("price")
    except Exception:
        pass
    try:
        if not price:
            lq = snap.get("latest_quote") or {}
            ask = lq.get("ask_price") or 0
            bid = lq.get("bid_price") or 0
            if ask and bid:
                price = (ask + bid) / 2
    except Exception:
        pass
    try:
        db = snap.get("daily_bar") or {}
        day_vol = db.get("volume")
        if not price:
            price = db.get("close")
    except Exception:
        pass
    try:
        pdb = snap.get("prev_daily_bar") or {}
        prev_close = pdb.get("close")
        prev_vol   = pdb.get("volume")
    except Exception:
        pass
    return price, prev_close, day_vol, prev_vol


async def _tool_get_sector_leaders(sector: str) -> Dict:
    """Execute get_sector_leaders tool: rank universe stocks in a sector by momentum."""
    from data.stock_universe import get_sector_symbols
    from trading.alpaca_client import alpaca_client

    syms = get_sector_symbols(sector)
    if not syms:
        return {"sector": sector, "error": "Unknown sector", "leaders": []}

    try:
        snapshots = await alpaca_client.get_snapshot(syms)
    except Exception as e:
        return {"sector": sector, "error": str(e), "leaders": []}

    leaders = []
    for sym, snap in snapshots.items():
        try:
            price, prev_close, day_volume, prev_vol = _extract_snapshot_fields(snap)
            pct_change = ((price - prev_close) / prev_close * 100) if price and prev_close else None
            vol_ratio  = (day_volume / prev_vol) if day_volume and prev_vol and prev_vol > 0 else None

            leaders.append({
                "symbol":     sym,
                "price":      round(price, 2) if price else None,
                "pct_change": round(pct_change, 2) if pct_change is not None else None,
                "vol_ratio":  round(vol_ratio, 2) if vol_ratio else None,
            })
        except Exception:
            pass

    leaders.sort(
        key=lambda x: abs(x.get("pct_change") or 0) * (x.get("vol_ratio") or 1),
        reverse=True,
    )
    return {"sector": sector, "leaders": leaders[:10]}


async def _dispatch_tool(name: str, inputs: Dict) -> str:
    """Route a tool call to the appropriate handler."""
    if name == "get_stock_analysis":
        result = await _tool_get_stock_analysis(inputs["symbol"])
    elif name == "get_sector_leaders":
        result = await _tool_get_sector_leaders(inputs["sector"])
    elif name == "add_recommendation":
        result = {"status": "recommendation_recorded", "symbol": inputs.get("symbol")}
    else:
        result = {"error": f"Unknown tool: {name}"}
    return json.dumps(result, default=str)


def _coerce_rec(rec: Dict) -> Dict:
    """Ensure numeric fields in a recommendation are actually numeric."""
    for field in ("confidence", "composite_score", "price_target", "stop_loss_pct"):
        if field in rec and rec[field] is not None:
            try:
                rec[field] = float(rec[field])
            except (TypeError, ValueError):
                pass
    if "action" in rec:
        rec["action"] = str(rec["action"]).upper()
    return rec


# ── Pre-screener ───────────────────────────────────────────────────────────────

def _compute_trend_multiplier(stooq_bars, price: float) -> float:
    """
    Derive a trend-alignment multiplier from Stooq long-term daily bars.

    Multiplier components:
      above_200ma  — 1.3 if price > 200-day SMA (uptrend), 0.9 if below
      near_52w_high — 1.4 if price is within 3% of the 52-week high (breakout zone)

    Combined range:  0.90 (downtrend, far from highs)  →  1.82 (uptrend breakout)

    Returns 1.0 when Stooq data is absent or insufficient — pure momentum score
    is used unchanged so the fallback never degrades the candidate ranking.
    """
    try:
        import pandas as pd
        if stooq_bars is None or not isinstance(stooq_bars, pd.DataFrame):
            return 1.0
        if stooq_bars.empty or "close" not in stooq_bars.columns:
            return 1.0

        closes = stooq_bars["close"].dropna()
        if len(closes) < 20:          # need at least a month of data
            return 1.0

        # 200-day SMA (or all available bars if history < 200 days)
        sma_200 = float(closes.tail(200).mean())
        above_200ma = 1.3 if price > sma_200 else 0.9

        # 52-week high from the high column (fallback: close column)
        if "high" in stooq_bars.columns:
            highs = stooq_bars["high"].dropna()
        else:
            highs = closes
        high_52w = float(highs.tail(252).max())
        near_52w_high = 1.4 if high_52w > 0 and price >= high_52w * 0.97 else 1.0

        return round(above_200ma * near_52w_high, 3)

    except Exception:
        return 1.0  # never let Stooq issues break the pre-screen


async def _pre_screen(top_n: int = 50) -> List[Dict]:
    """
    Fast pre-screen using daily bars (more reliable than snapshots on IEX feed).

    Stage 1 — Alpaca (5 daily bars, batched 40 at a time):
      short_score = abs(pct_change) × max(vol_ratio, 0.1)

    Stage 2 — Stooq (252 daily bars, concurrent with Alpaca per batch):
      trend_multiplier = above_200ma × near_52w_high
        above_200ma  : 1.3 if price > 200-day SMA else 0.9
        near_52w_high: 1.4 if price ≥ 52-week high × 0.97 else 1.0

    Final score = short_score × trend_multiplier

    Stooq has a 4-hour in-memory cache — only the first scan of the day hits
    the network.  If Stooq is unavailable, trend_multiplier falls back to 1.0
    so the short-term momentum score is used unchanged.

    Default pool is 50 (cloud mode) or 20 (OLLAMA_ONLY_MODE).
    """
    from data.stock_universe import ALL_SYMBOLS
    from trading.alpaca_client import alpaca_client
    from data.stooq_client import stooq_client

    BATCH = 40
    batches = [ALL_SYMBOLS[i:i+BATCH] for i in range(0, len(ALL_SYMBOLS), BATCH)]
    logger.info(f"Scanner pre-screen: {len(ALL_SYMBOLS)} symbols across {len(batches)} batches")

    candidates = []
    for batch in batches:
        try:
            # Fetch Alpaca (5 bars) and Stooq (252 bars = 1 year) concurrently
            alpaca_result, stooq_result = await asyncio.gather(
                alpaca_client.get_bars_multi(batch, limit=5),
                stooq_client.get_bars_multi(batch, days=252),
                return_exceptions=True,
            )

            bars_dict  = alpaca_result  if isinstance(alpaca_result,  dict) else {}
            stooq_dict = stooq_result   if isinstance(stooq_result,   dict) else {}

            for sym, bars in bars_dict.items():
                if bars is None or bars.empty or len(bars) < 2:
                    continue
                try:
                    price      = float(bars["close"].iloc[-1])
                    prev_close = float(bars["close"].iloc[-2])
                except (TypeError, ValueError):
                    continue
                day_vol  = float(bars["volume"].iloc[-1]) if "volume" in bars.columns else 0
                prev_vol = float(bars["volume"].iloc[-2]) if "volume" in bars.columns else 0

                if prev_close == 0:
                    continue

                pct_change       = (price - prev_close) / prev_close * 100
                vol_ratio        = (day_vol / prev_vol) if prev_vol > 0 else 1.0
                short_score      = abs(pct_change) * max(vol_ratio, 0.1)
                trend_multiplier = _compute_trend_multiplier(stooq_dict.get(sym), price)
                final_score      = short_score * trend_multiplier

                candidates.append({
                    "symbol":           sym,
                    "price":            round(price, 2),
                    "pct_change":       round(pct_change, 2),
                    "vol_ratio":        round(vol_ratio, 2),
                    "trend_multiplier": trend_multiplier,
                    "momentum_score":   round(final_score, 3),
                })
        except Exception as e:
            logger.warning(f"Pre-screen batch failed: {e}")

    candidates.sort(key=lambda x: x["momentum_score"], reverse=True)
    top = candidates[:top_n]

    # Log top-5 with trend context so it's visible in the daily log
    if top:
        summary = "  ".join(
            f"{c['symbol']}({c['pct_change']:+.1f}% ×{c['trend_multiplier']}={c['momentum_score']:.2f})"
            for c in top[:5]
        )
        logger.info(f"Pre-screen top-5: {summary}")

    logger.info(f"Pre-screen complete: {len(candidates)} valid symbols, top-{top_n} selected")
    return top


# ── Candidate splitting ────────────────────────────────────────────────────────

def _split_candidates(candidates: List[Dict], n: int) -> List[List[Dict]]:
    """
    Split candidates into n sequential chunks.
    First chunk gets the top-ranked candidates (highest momentum scores).
    """
    if n <= 1:
        return [candidates]
    size = math.ceil(len(candidates) / n)
    return [candidates[i:i + size] for i in range(0, len(candidates), size)]


# ── Claude scanner ─────────────────────────────────────────────────────────────

async def _run_claude_scanner(candidates: List[Dict], sector_summary: str = "") -> List[Dict]:
    """Agentic Claude tool-use loop over a candidate subset."""
    from config import config
    import anthropic

    if not config.ANTHROPIC_API_KEY or not candidates:
        return []

    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    messages = [{"role": "user", "content": _build_user_message(candidates, sector_summary=sector_summary)}]
    recommendations: List[Dict] = []
    rounds = 0
    total_input_tokens = 0
    total_output_tokens = 0

    logger.info(f"Scanner/Claude: starting agentic loop ({len(candidates)} candidates)")

    while rounds < MAX_TOOL_ROUNDS:
        rounds += 1

        # Prune any prior tool results before sending to keep conversation history small.
        # Replaces full JSON blobs with a one-line summary once they've been consumed.
        if rounds > 1:
            for msg in messages:
                if msg.get("role") == "user" and isinstance(msg.get("content"), list):
                    for item in msg["content"]:
                        if isinstance(item, dict) and item.get("type") == "tool_result":
                            raw = item.get("content", "")
                            if isinstance(raw, str) and len(raw) > 100:
                                try:
                                    data  = json.loads(raw)
                                    sym   = data.get("symbol", "?")
                                    score = data.get("composite_score", "?")
                                    conf  = data.get("confidence", "?")
                                    item["content"] = f"[seen] {sym} score={score} conf={conf}"
                                except Exception:
                                    item["content"] = raw[:80] + "…"

        try:
            response = await client.messages.create(
                model=config.SCANNER_CLAUDE_MODEL,
                max_tokens=4096,
                system=_CACHED_SYSTEM,      # cached: same every round
                tools=_TOOLS_WITH_CACHE,    # cached: tool defs never change
                messages=messages,
            )
        except Exception as e:
            logger.error(f"Scanner/Claude: API error round {rounds}: {e}")
            break

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        tool_uses = []
        for block in response.content:
            if block.type == "tool_use":
                tool_uses.append(block)
                if block.name == "add_recommendation":
                    rec = _coerce_rec(dict(block.input))
                    rec["timestamp"] = datetime.now(timezone.utc).isoformat()
                    recommendations.append(rec)
                    logger.info(
                        f"Scanner/Claude: {rec.get('symbol')} {rec.get('action')} "
                        f"conf={rec.get('confidence', 0):.2f}"
                    )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use" or not tool_uses:
            logger.info(f"Scanner/Claude: done after {rounds} rounds, {len(recommendations)} recs")
            break

        tool_results = []
        for tu in tool_uses:
            result_str = await _dispatch_tool(tu.name, tu.input)
            tool_results.append({
                "type":        "tool_result",
                "tool_use_id": tu.id,
                "content":     result_str,
            })

        messages.append({"role": "user", "content": tool_results})

    try:
        _call_total = total_input_tokens + total_output_tokens
        try:
            _prior_24h = await get_daily_token_total("ScannerAgent/Claude", hours=24)
        except Exception:
            _prior_24h = 0
        await save_token_log(
            agent="ScannerAgent/Claude",
            model=config.SCANNER_CLAUDE_MODEL,
            prompt_tokens=total_input_tokens,
            completion_tokens=total_output_tokens,
            total_tokens=_call_total,
            daily_total=_prior_24h + _call_total,
            limit_hit=False,
        )
    except Exception as _e:
        logger.debug(f"Scanner/Claude: token log save failed: {_e}")

    _append_scanner_recs_log("Claude", config.SCANNER_CLAUDE_MODEL,
                             candidates, recommendations)
    return recommendations


# ── Gemini scanner ─────────────────────────────────────────────────────────────

def _build_gemini_tools():
    """Convert TOOLS definitions to Gemini FunctionDeclaration format."""
    if not HAS_GEMINI:
        return []

    S = _genai_types.Schema
    T = _genai_types.Type

    def _schema(js: Dict) -> "_genai_types.Schema":
        t = js.get("type", "string")
        desc = js.get("description", "")
        if t == "number":
            return S(type=T.NUMBER, description=desc)
        if t == "array":
            return S(type=T.ARRAY, description=desc,
                     items=_schema(js.get("items", {"type": "string"})))
        if t == "object":
            props = {k: _schema(v) for k, v in js.get("properties", {}).items()}
            return S(type=T.OBJECT, description=desc, properties=props,
                     required=js.get("required", []))
        return S(type=T.STRING, description=desc)

    decls = [
        _genai_types.FunctionDeclaration(
            name=t["name"],
            description=t["description"],
            parameters=_schema(t["input_schema"]),
        )
        for t in TOOLS
    ]
    return [_genai_types.Tool(function_declarations=decls)]


async def _run_gemini_scanner(candidates: List[Dict], sector_summary: str = "") -> List[Dict]:
    """Agentic Gemini tool-use loop over a candidate subset."""
    from config import config

    if not HAS_GEMINI or not config.GEMINI_API_KEY or not candidates:
        return []

    client = _genai.Client(api_key=config.GEMINI_API_KEY)
    gemini_tools = _build_gemini_tools()

    contents = [
        _genai_types.Content(
            role="user",
            parts=[_genai_types.Part.from_text(
                f"{_SYSTEM_PROMPT}\n\n{_build_user_message(candidates, sector_summary=sector_summary)}"
            )],
        )
    ]
    recommendations: List[Dict] = []
    rounds = 0
    total_prompt_tokens = 0
    total_candidate_tokens = 0

    logger.info(f"Scanner/Gemini: starting agentic loop ({len(candidates)} candidates)")

    while rounds < MAX_TOOL_ROUNDS:
        rounds += 1
        try:
            response = await client.aio.models.generate_content(
                model="gemini-2.0-flash",
                contents=contents,
                config=_genai_types.GenerateContentConfig(tools=gemini_tools),
            )
        except Exception as e:
            logger.error(f"Scanner/Gemini: API error round {rounds}: {e}")
            break

        usage = getattr(response, "usage_metadata", None)
        if usage:
            total_prompt_tokens += getattr(usage, "prompt_token_count", 0) or 0
            total_candidate_tokens += getattr(usage, "candidates_token_count", 0) or 0

        if not response.candidates:
            break

        model_content = response.candidates[0].content
        function_calls = []
        for part in model_content.parts:
            fc = getattr(part, "function_call", None)
            if fc and getattr(fc, "name", None):
                function_calls.append(fc)
                if fc.name == "add_recommendation":
                    rec = _coerce_rec(dict(fc.args))
                    rec["timestamp"] = datetime.now(timezone.utc).isoformat()
                    recommendations.append(rec)
                    logger.info(
                        f"Scanner/Gemini: {rec.get('symbol')} {rec.get('action')} "
                        f"conf={rec.get('confidence', 0):.2f}"
                    )

        contents.append(model_content)

        if not function_calls:
            logger.info(f"Scanner/Gemini: done after {rounds} rounds, {len(recommendations)} recs")
            break

        result_parts = []
        for fc in function_calls:
            result_str = await _dispatch_tool(fc.name, dict(fc.args))
            result_dict = json.loads(result_str)
            result_parts.append(
                _genai_types.Part.from_function_response(
                    name=fc.name,
                    response=result_dict,
                )
            )
        contents.append(_genai_types.Content(role="user", parts=result_parts))

    try:
        _call_total = total_prompt_tokens + total_candidate_tokens
        try:
            _prior_24h = await get_daily_token_total("ScannerAgent/Gemini", hours=24)
        except Exception:
            _prior_24h = 0
        await save_token_log(
            agent="ScannerAgent/Gemini",
            model="gemini-2.0-flash",
            prompt_tokens=total_prompt_tokens,
            completion_tokens=total_candidate_tokens,
            total_tokens=_call_total,
            daily_total=_prior_24h + _call_total,
            limit_hit=False,
        )
    except Exception as _e:
        logger.debug(f"Scanner/Gemini: token log save failed: {_e}")

    _append_scanner_recs_log("Gemini", "gemini-2.0-flash",
                             candidates, recommendations)
    return recommendations


# ── OpenAI scanner ─────────────────────────────────────────────────────────────

# Convert TOOLS to OpenAI function-calling format (same JSON Schema, different wrapper)
_OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        },
    }
    for t in TOOLS
]


async def _run_openai_scanner(candidates: List[Dict], sector_summary: str = "") -> List[Dict]:
    """Agentic OpenAI tool-use loop over a candidate subset."""
    from config import config

    if not HAS_OPENAI or not config.OPENAI_API_KEY or not candidates:
        return []

    client = _AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    messages: List[Dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_message(candidates, sector_summary=sector_summary)},
    ]
    recommendations: List[Dict] = []
    rounds = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0

    logger.info(f"Scanner/OpenAI: starting agentic loop ({len(candidates)} candidates)")

    while rounds < MAX_TOOL_ROUNDS:
        rounds += 1
        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                tools=_OPENAI_TOOLS,
                tool_choice="auto",
            )
        except Exception as e:
            logger.error(f"Scanner/OpenAI: API error round {rounds}: {e}")
            break

        if response.usage:
            total_prompt_tokens += response.usage.prompt_tokens or 0
            total_completion_tokens += response.usage.completion_tokens or 0

        choice = response.choices[0]
        msg = choice.message
        tool_calls = msg.tool_calls or []

        # Collect recommendations
        for tc in tool_calls:
            if tc.function.name == "add_recommendation":
                try:
                    rec = _coerce_rec(json.loads(tc.function.arguments))
                    rec["timestamp"] = datetime.now(timezone.utc).isoformat()
                    recommendations.append(rec)
                    logger.info(
                        f"Scanner/OpenAI: {rec.get('symbol')} {rec.get('action')} "
                        f"conf={rec.get('confidence', 0):.2f}"
                    )
                except Exception as e:
                    logger.warning(f"Scanner/OpenAI: failed to parse recommendation: {e}")

        # Append assistant turn
        assistant_msg: Dict[str, Any] = {"role": "assistant", "content": msg.content}
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ]
        messages.append(assistant_msg)

        if choice.finish_reason != "tool_calls" or not tool_calls:
            logger.info(f"Scanner/OpenAI: done after {rounds} rounds, {len(recommendations)} recs")
            break

        # Execute tools and feed results back
        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except Exception:
                args = {}
            result_str = await _dispatch_tool(tc.function.name, args)
            messages.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      result_str,
            })

    try:
        _call_total = total_prompt_tokens + total_completion_tokens
        try:
            _prior_24h = await get_daily_token_total("ScannerAgent/OpenAI", hours=24)
        except Exception:
            _prior_24h = 0
        await save_token_log(
            agent="ScannerAgent/OpenAI",
            model="gpt-4o-mini",
            prompt_tokens=total_prompt_tokens,
            completion_tokens=total_completion_tokens,
            total_tokens=_call_total,
            daily_total=_prior_24h + _call_total,
            limit_hit=False,
        )
    except Exception as _e:
        logger.debug(f"Scanner/OpenAI: token log save failed: {_e}")

    _append_scanner_recs_log("OpenAI", "gpt-4o-mini",
                             candidates, recommendations)
    return recommendations


# ── Ollama scanner ─────────────────────────────────────────────────────────────

async def _ollama_is_available() -> bool:
    """Return True if the Ollama server is reachable at the configured base URL."""
    import httpx
    from config import config
    base = config.OLLAMA_BASE_URL.rstrip("/")
    health = (base[:-3] if base.endswith("/v1") else base) + "/api/tags"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(health)
            return r.status_code == 200
    except Exception:
        return False


def _load_ollama_learning() -> str:
    """Load the Ollama scanner learning journal and return it as extra system context."""
    learning_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "ollama_scanner_learning.md"
    )
    try:
        with open(learning_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if content:
            return f"\n\n--- LEARNING JOURNAL ---\n{content}\n--- END LEARNING JOURNAL ---"
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.debug(f"Ollama: could not load learning journal: {e}")
    return ""


async def _run_ollama_scanner(
    candidates: List[Dict],
    sector_summary: str = "",
    max_rounds: int = MAX_TOOL_ROUNDS,
) -> List[Dict]:
    """Agentic Ollama tool-use loop over a candidate subset (OpenAI-compatible API).

    ``max_rounds`` is intentionally lower in OLLAMA_ONLY_MODE (passed by the
    dispatcher) so that scanner calls don't hold the single-GPU Ollama queue
    for too long and starve other agents (e.g. CNNReasoningAgent).
    """
    from config import config
    from openai import AsyncOpenAI as _OllamaClient

    if not candidates:
        return []

    client = _OllamaClient(
        api_key="ollama",
        base_url=config.OLLAMA_BASE_URL,
    )

    system_prompt = _SYSTEM_PROMPT + _load_ollama_learning()
    messages: List[Dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": _build_user_message(candidates, sector_summary=sector_summary)},
    ]
    recommendations: List[Dict] = []
    rounds = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0

    logger.info(
        f"Scanner/Ollama: starting agentic loop "
        f"({len(candidates)} candidates, model={config.OLLAMA_MODEL}, max_rounds={max_rounds})"
    )

    while rounds < max_rounds:
        rounds += 1
        # Force a tool call on round 1 so llama3/mistral-class models don't
        # return a plain-text response and exit with 0 recommendations.
        _tool_choice = "required" if rounds == 1 else "auto"
        response = None
        for _attempt in range(3):  # up to 3 attempts per round (handles 500 crashes)
            try:
                response = await client.chat.completions.create(
                    model=config.OLLAMA_MODEL,
                    messages=messages,
                    tools=_OPENAI_TOOLS,
                    tool_choice=_tool_choice,
                )
                break  # success
            except Exception as e:
                err_str = str(e)
                is_500 = "500" in err_str or "terminated" in err_str or "runner" in err_str
                if is_500 and _attempt < 2:
                    wait = 5 * (2 ** _attempt)  # 5 s, 10 s
                    logger.warning(
                        f"Scanner/Ollama: API error round {rounds} attempt {_attempt + 1} "
                        f"(Ollama crash?), retrying in {wait}s: {e}"
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(f"Scanner/Ollama: API error round {rounds}: {e}")
                    response = None
                    break
        if response is None:
            break

        if response.usage:
            total_prompt_tokens += response.usage.prompt_tokens or 0
            total_completion_tokens += response.usage.completion_tokens or 0

        choice = response.choices[0]
        msg = choice.message
        tool_calls = msg.tool_calls or []

        for tc in tool_calls:
            if tc.function.name == "add_recommendation":
                try:
                    rec = _coerce_rec(json.loads(tc.function.arguments))
                    rec["timestamp"] = datetime.now(timezone.utc).isoformat()
                    recommendations.append(rec)
                    logger.info(
                        f"Scanner/Ollama: {rec.get('symbol')} {rec.get('action')} "
                        f"conf={rec.get('confidence', 0):.2f}"
                    )
                except Exception as e:
                    logger.warning(f"Scanner/Ollama: failed to parse recommendation: {e}")

        assistant_msg: Dict[str, Any] = {"role": "assistant", "content": msg.content}
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ]
        messages.append(assistant_msg)

        if choice.finish_reason != "tool_calls" or not tool_calls:
            logger.info(f"Scanner/Ollama: done after {rounds} rounds, {len(recommendations)} recs")
            break

        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except Exception:
                args = {}
            result_str = await _dispatch_tool(tc.function.name, args)
            messages.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      result_str,
            })

    try:
        _call_total = total_prompt_tokens + total_completion_tokens
        try:
            _prior_24h = await get_daily_token_total("ScannerAgent/Ollama", hours=24)
        except Exception:
            _prior_24h = 0
        await save_token_log(
            agent="ScannerAgent/Ollama",
            model=config.OLLAMA_MODEL,
            prompt_tokens=total_prompt_tokens,
            completion_tokens=total_completion_tokens,
            total_tokens=_call_total,
            daily_total=_prior_24h + _call_total,
            limit_hit=False,
        )
    except Exception as _e:
        logger.debug(f"Scanner/Ollama: token log save failed: {_e}")

    _append_scanner_recs_log("Ollama", config.OLLAMA_MODEL,
                             candidates, recommendations)
    return recommendations


# ── Merge ──────────────────────────────────────────────────────────────────────

def _merge_recommendations(results: List[Any]) -> List[Dict]:
    """
    Merge recommendation lists from multiple agents.
    Deduplicates by symbol — highest confidence wins.
    Returns top MAX_RECOMMENDATIONS sorted by confidence descending.
    """
    best: Dict[str, Dict] = {}
    for recs in results:
        if isinstance(recs, Exception):
            logger.warning(f"Scanner sub-agent raised: {recs}")
            continue
        if not isinstance(recs, list):
            continue
        for rec in recs:
            sym = rec.get("symbol")
            if not sym:
                continue
            conf = float(rec.get("confidence") or 0)
            if sym not in best or conf > float(best[sym].get("confidence") or 0):
                best[sym] = rec

    return sorted(best.values(), key=lambda r: float(r.get("confidence") or 0), reverse=True)[
        :MAX_RECOMMENDATIONS
    ]


# ── Public API ─────────────────────────────────────────────────────────────────

async def run_scan(force: bool = False) -> Dict:
    """
    Full scan pipeline: pre-screen → parallel AI analysis → merged recommendations.

    Cache TTL:
      - Ollama-only mode: OLLAMA_SCAN_TTL (5 min) — free local model, scan often
      - Tokenized agents:  SCAN_CACHE_TTL  (30 min) — conserve API quota
      - force=True:        always run a fresh scan, ignoring cache age

    A module-level asyncio.Lock prevents multiple concurrent callers from
    all launching expensive AI scans simultaneously — the second caller waits,
    then returns the result the first caller just produced.
    """
    import os as _os
    global _cache, _cache_ts, _scan_in_progress

    ttl = OLLAMA_SCAN_TTL if _os.environ.get("OLLAMA_ONLY_MODE") == "1" else SCAN_CACHE_TTL

    # Fast path: return cache without acquiring the lock
    now = time.time()
    if not force and _cache and (now - _cache_ts) < ttl:
        logger.info("Scanner: returning cached results")
        return _cache

    async with _scan_lock:
        # Re-check after acquiring lock: a concurrent caller may have just finished
        now = time.time()
        if not force and _cache and (now - _cache_ts) < ttl:
            logger.info("Scanner: returning results from concurrent scan")
            return _cache

        _scan_in_progress = True
        try:
            return await _run_scan_inner()
        finally:
            _scan_in_progress = False


async def _run_scan_inner() -> Dict:
    global _cache, _cache_ts

    _t0 = time.time()
    started = datetime.now(timezone.utc).isoformat()
    _reset_pull_stats()

    import os as _os_inner
    # In OLLAMA_ONLY_MODE there is only one scanner — no parallel splitting.
    # Ollama is capped at MAX_TOOL_ROUNDS rounds, so a large pool just bloats
    # the prompt without adding coverage.  20 candidates is plenty for 4 rounds.
    # Cloud mode splits 50 candidates across Claude + Gemini (+ Ollama), so each
    # agent gets a meaningful ~17-symbol slice.
    _top_n = 20 if _os_inner.environ.get("OLLAMA_ONLY_MODE") == "1" else 50
    candidates = await _pre_screen(top_n=_top_n)

    if not candidates:
        result = {
            "status":          "error",
            "error":           "Pre-screen returned no candidates (Alpaca unavailable?)",
            "recommendations": [],
            "candidates":      [],
            "pull_stats":      _get_pull_stats(),
            "scanned_at":      started,
        }
        return result

    # Fetch sector performance for context-aware scanning
    sector_summary = ""
    try:
        from data.sector_analysis import get_sector_performance, format_sector_summary
        sector_perf = await get_sector_performance()
        sector_summary = format_sector_summary(sector_perf)
    except Exception as e:
        logger.debug(f"Scanner: sector performance fetch failed: {e}")

    # Determine which AI scanners are available
    import os as _os
    from config import config
    _ollama_only = _os.environ.get("OLLAMA_ONLY_MODE") == "1"
    scanners = []
    if not _ollama_only:
        if config.ANTHROPIC_API_KEY:
            scanners.append(("Claude",  _run_claude_scanner))
        if HAS_GEMINI and config.GEMINI_API_KEY:
            scanners.append(("Gemini",  _run_gemini_scanner))
    # Ollama (local, free) takes priority; fall back to OpenAI if Ollama isn't running
    if await _ollama_is_available():
        scanners.append(("Ollama", _run_ollama_scanner))
    elif not _ollama_only and HAS_OPENAI and config.OPENAI_API_KEY:
        scanners.append(("OpenAI", _run_openai_scanner))

    if not scanners:
        result = {
            "status":          "error",
            "error":           "No AI providers available (configure ANTHROPIC_API_KEY, GEMINI_API_KEY, or start Ollama at localhost:11434)",
            "recommendations": [],
            "candidates":      candidates,
            "pull_stats":      _get_pull_stats(),
            "scanned_at":      started,
        }
        return result

    # Split primary slice per scanner; each scanner also receives the rest of the
    # ranked pool as a fallback so it can continue if its primary pulls fail.
    splits = _split_candidates(candidates, len(scanners))
    agent_names = [name for name, _ in scanners]

    # Build (primary, fallback) pairs: fallback = every candidate NOT in this agent's slice
    primary_symbols_per = [set(c["symbol"] for c in s) for s in splits]
    fallback_per = [
        [c for c in candidates if c["symbol"] not in primary_syms]
        for primary_syms in primary_symbols_per
    ]

    logger.info(
        f"Scanner: running {len(scanners)} agents in parallel — "
        + ", ".join(
            f"{name}({len(s)} primary + {len(fb)} fallback)"
            for name, s, fb in zip(agent_names, splits, fallback_per)
        )
    )

    # Merge primary + fallback into a single ordered list per scanner
    # (primary first so agents always start with their highest-momentum symbols)
    combined = [primary + fb for primary, fb in zip(splits, fallback_per)]

    # In OLLAMA_ONLY_MODE the single Ollama scanner handles the full pool alone.
    # Cap its rounds at 4 (vs MAX_TOOL_ROUNDS=6) so the GPU queue stays free
    # for CNNReasoningAgent and other Ollama consumers.
    def _make_task(name: str, fn, cands: List[Dict]) -> Any:
        if name == "Ollama" and _ollama_only:
            return fn(cands, sector_summary, max_rounds=4)
        return fn(cands, sector_summary)

    tasks = [_make_task(name, fn, cands) for (name, fn), cands in zip(scanners, combined)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    recommendations = _merge_recommendations(results)
    pull_stats = _get_pull_stats()
    logger.info(
        f"Scanner: merged {len(recommendations)} unique recommendations from {len(scanners)} agents — "
        f"data pulls: {pull_stats['hits']}/{pull_stats['total']} succeeded "
        f"({pull_stats['success_pct']}%)"
    )

    result = {
        "status":           "ok",
        "recommendations":  recommendations,
        "candidates":       candidates,
        "pull_stats":       pull_stats,
        "scanned_at":       started,
        "completed_at":     datetime.now(timezone.utc).isoformat(),
        "cache_expires_in": SCAN_CACHE_TTL,
    }
    _cache    = result
    _cache_ts = time.time()
    _scan_history.append(round(time.time() - _t0, 1))
    _save_cache_to_disk(result)
    return result


def is_scan_in_progress() -> bool:
    """Return True while a scan is actively running."""
    return _scan_in_progress


def get_cached_scan(require_fresh: bool = False) -> Optional[Dict]:
    """
    Return cached scan result without triggering a new scan.

    require_fresh=True  → only return if within SCAN_CACHE_TTL (used by trading agents)
    require_fresh=False → return any persisted result, even if stale (used by UI / API)
    """
    global _cache, _cache_ts
    if not _cache:
        return None
    fresh = (time.time() - _cache_ts) < SCAN_CACHE_TTL
    if require_fresh and not fresh:
        return None
    # Tag stale results so the UI can show an age warning
    result = dict(_cache)
    result["is_stale"] = not fresh
    return result
