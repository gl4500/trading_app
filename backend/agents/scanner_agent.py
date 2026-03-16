"""
ScannerAgent — Multi-agent parallel stock scanner powered by Claude, Gemini, and OpenAI.

How it works:
  1. Pre-screener: fetches daily bars for ~160 universe symbols from Alpaca,
     ranks by 1-day momentum + volume surge → picks top 20 candidates.
  2. Parallel AI scan: splits candidates across available AI providers and
     runs all agentic tool-use loops concurrently via asyncio.gather.
     - Claude Opus   → top candidates  (highest conviction analysis)
     - Gemini Flash  → middle tier     (cheap, fast)
     - OpenAI GPT-4o → lower tier      (moderate cost)
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
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SCAN_CACHE_TTL = 30 * 60   # 30 minutes (in-memory freshness for trading)
MAX_TOOL_ROUNDS = 12        # safety ceiling per agent
MAX_RECOMMENDATIONS = 8     # final output limit after merge

# Persist scans here so results survive restarts
_CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "scan_cache.json")

_cache: Optional[Dict] = None
_cache_ts: float = 0.0
_scan_in_progress: bool = False


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

# ── Shared prompt ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are an elite quantitative stock scanner AI with access to real-time market data tools.

Your mission: identify the BEST trading opportunities in the market today.

Decision framework:
- BUY signals require: bullish composite score (>+0.15), RSI not overbought (<70), confirmed by at least 2 sources
- SELL signals require: bearish composite score (<-0.15), RSI not oversold (>30), confirmed by at least 2 sources
- WATCH: interesting setup but missing confirmation — flag for monitoring
- SKIP: insufficient signal, conflicting data, or no edge

Process:
1. Review the pre-screened momentum candidates below
2. Use get_stock_analysis to deep-dive into the most promising ones
3. Use get_sector_leaders if you want to explore a sector for additional ideas
4. Call add_recommendation for each high-conviction pick (max 8 total)
5. Prioritise quality over quantity — only recommend when you have clear conviction

Always check composite score, RSI, MACD, and volume confirmation before recommending."""


def _build_user_message(candidates: List[Dict]) -> str:
    summary = "\n".join(
        f"  {c['symbol']:6s}  {c['pct_change']:+.2f}%  vol\u00d7{c['vol_ratio']:.1f}  "
        f"momentum={c['momentum_score']:.2f}"
        for c in candidates
    )
    return (
        f"Today's pre-screened momentum leaders (top movers by price \u00d7 volume):\n\n"
        f"{summary}\n\n"
        "Analyse these candidates and any additional stocks you want to investigate. "
        "Use your tools to get full analysis, then submit your recommendations. "
        "Focus on finding high-conviction opportunities with clear catalysts."
    )


# ── Tool execution ─────────────────────────────────────────────────────────────

async def _tool_get_stock_analysis(symbol: str) -> Dict:
    """Execute get_stock_analysis tool: pull composite signal + technicals."""
    from data.signal_aggregator import get_composite_signal
    from data.news_service import news_service
    from data import technicals
    from trading.alpaca_client import alpaca_client

    symbol = symbol.upper().strip()
    try:
        news_task   = news_service.get_news(symbol)
        bars_task   = alpaca_client.get_bars(symbol, limit=60)
        news, bars  = await asyncio.gather(news_task, bars_task, return_exceptions=False)

        sig = await get_composite_signal(symbol, news if isinstance(news, list) else [])

        ind = {}
        price = None
        if bars is not None and not bars.empty:
            ind = technicals.compute(bars)
            price = float(bars["close"].iloc[-1]) if "close" in bars.columns else None

        return {
            "symbol":          symbol,
            "price":           price,
            "composite_score": sig.get("composite_score"),
            "confidence":      sig.get("confidence"),
            "verdict":         sig.get("verdict"),
            "sources":         sig.get("sources", {}),
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
        logger.warning(f"scanner tool get_stock_analysis({symbol}): {e}")
        return {"symbol": symbol, "error": str(e)}


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

async def _pre_screen(top_n: int = 20) -> List[Dict]:
    """
    Fast pre-screen using daily bars (more reliable than snapshots on IEX feed).
    Fetches last 5 bars for the full universe in batches of 40, ranks by
    |1-day pct change| x volume ratio, returns top_n candidates.
    """
    from data.stock_universe import ALL_SYMBOLS
    from trading.alpaca_client import alpaca_client

    BATCH = 40
    batches = [ALL_SYMBOLS[i:i+BATCH] for i in range(0, len(ALL_SYMBOLS), BATCH)]
    logger.info(f"Scanner pre-screen: {len(ALL_SYMBOLS)} symbols across {len(batches)} batches")

    candidates = []
    for batch in batches:
        try:
            bars_dict = await alpaca_client.get_bars_multi(batch, limit=5)
            for sym, bars in bars_dict.items():
                if bars is None or bars.empty or len(bars) < 2:
                    continue
                price      = float(bars["close"].iloc[-1])
                prev_close = float(bars["close"].iloc[-2])
                day_vol    = float(bars["volume"].iloc[-1]) if "volume" in bars.columns else 0
                prev_vol   = float(bars["volume"].iloc[-2]) if "volume" in bars.columns else 0

                if prev_close == 0:
                    continue

                pct_change = (price - prev_close) / prev_close * 100
                vol_ratio  = (day_vol / prev_vol) if prev_vol > 0 else 1.0
                score      = abs(pct_change) * max(vol_ratio, 0.1)

                candidates.append({
                    "symbol":         sym,
                    "price":          round(price, 2),
                    "pct_change":     round(pct_change, 2),
                    "vol_ratio":      round(vol_ratio, 2),
                    "momentum_score": round(score, 3),
                })
        except Exception as e:
            logger.warning(f"Pre-screen batch failed: {e}")

    candidates.sort(key=lambda x: x["momentum_score"], reverse=True)
    logger.info(f"Pre-screen complete: {len(candidates)} valid symbols, top-{top_n} selected")
    return candidates[:top_n]


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

async def _run_claude_scanner(candidates: List[Dict]) -> List[Dict]:
    """Agentic Claude tool-use loop over a candidate subset."""
    from config import config
    import anthropic

    if not config.ANTHROPIC_API_KEY or not candidates:
        return []

    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    messages = [{"role": "user", "content": _build_user_message(candidates)}]
    recommendations: List[Dict] = []
    rounds = 0

    logger.info(f"Scanner/Claude: starting agentic loop ({len(candidates)} candidates)")

    while rounds < MAX_TOOL_ROUNDS:
        rounds += 1
        try:
            response = await client.messages.create(
                model="claude-opus-4-6",
                max_tokens=4096,
                system=_SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )
        except Exception as e:
            logger.error(f"Scanner/Claude: API error round {rounds}: {e}")
            break

        tool_uses = []
        for block in response.content:
            if block.type == "tool_use":
                tool_uses.append(block)
                if block.name == "add_recommendation":
                    rec = _coerce_rec(dict(block.input))
                    rec["timestamp"] = datetime.utcnow().isoformat()
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


async def _run_gemini_scanner(candidates: List[Dict]) -> List[Dict]:
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
                f"{_SYSTEM_PROMPT}\n\n{_build_user_message(candidates)}"
            )],
        )
    ]
    recommendations: List[Dict] = []
    rounds = 0

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
                    rec["timestamp"] = datetime.utcnow().isoformat()
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


async def _run_openai_scanner(candidates: List[Dict]) -> List[Dict]:
    """Agentic OpenAI tool-use loop over a candidate subset."""
    from config import config

    if not HAS_OPENAI or not config.OPENAI_API_KEY or not candidates:
        return []

    client = _AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    messages: List[Dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_message(candidates)},
    ]
    recommendations: List[Dict] = []
    rounds = 0

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

        choice = response.choices[0]
        msg = choice.message
        tool_calls = msg.tool_calls or []

        # Collect recommendations
        for tc in tool_calls:
            if tc.function.name == "add_recommendation":
                try:
                    rec = _coerce_rec(json.loads(tc.function.arguments))
                    rec["timestamp"] = datetime.utcnow().isoformat()
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

async def run_scan() -> Dict:
    """
    Full scan pipeline: pre-screen → parallel AI analysis → merged recommendations.
    Results cached for SCAN_CACHE_TTL seconds.
    """
    global _cache, _cache_ts, _scan_in_progress

    now = time.time()
    if _cache and (now - _cache_ts) < SCAN_CACHE_TTL:
        logger.info("Scanner: returning cached results")
        return _cache

    _scan_in_progress = True
    try:
        return await _run_scan_inner()
    finally:
        _scan_in_progress = False


async def _run_scan_inner() -> Dict:
    global _cache, _cache_ts

    started = datetime.utcnow().isoformat()
    candidates = await _pre_screen(top_n=20)

    if not candidates:
        result = {
            "status":          "error",
            "error":           "Pre-screen returned no candidates (Alpaca unavailable?)",
            "recommendations": [],
            "candidates":      [],
            "scanned_at":      started,
        }
        return result

    # Determine which AI scanners are available
    from config import config
    scanners = []
    if config.ANTHROPIC_API_KEY:
        scanners.append(("Claude",  _run_claude_scanner))
    if HAS_GEMINI and config.GEMINI_API_KEY:
        scanners.append(("Gemini",  _run_gemini_scanner))
    if HAS_OPENAI and config.OPENAI_API_KEY:
        scanners.append(("OpenAI",  _run_openai_scanner))

    if not scanners:
        result = {
            "status":          "error",
            "error":           "No AI API keys configured (ANTHROPIC_API_KEY, GEMINI_API_KEY, or OPENAI_API_KEY required)",
            "recommendations": [],
            "candidates":      candidates,
            "scanned_at":      started,
        }
        return result

    # Split candidates: first scanner (Claude) gets top-ranked batch
    splits = _split_candidates(candidates, len(scanners))
    agent_names = [name for name, _ in scanners]
    logger.info(
        f"Scanner: running {len(scanners)} agents in parallel — "
        + ", ".join(f"{name}({len(s)} candidates)" for name, s in zip(agent_names, splits))
    )

    tasks = [fn(split) for (_, fn), split in zip(scanners, splits)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    recommendations = _merge_recommendations(results)
    logger.info(f"Scanner: merged {len(recommendations)} unique recommendations from {len(scanners)} agents")

    result = {
        "status":           "ok",
        "recommendations":  recommendations,
        "candidates":       candidates,
        "scanned_at":       started,
        "completed_at":     datetime.utcnow().isoformat(),
        "cache_expires_in": SCAN_CACHE_TTL,
    }
    _cache    = result
    _cache_ts = time.time()
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
