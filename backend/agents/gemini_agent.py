"""
Gemini Agent: Uses Google Gemini for market analysis and trading decisions.
Runs in parallel with ClaudeAgent as a second AI perspective in the ensemble.
"""
import asyncio
import json
import logging
import re
import time
from datetime import date
from typing import Dict, List, Optional, Any

from agents.base_agent import BaseAgent, Signal
from agents.agent_utils import (
    format_bars_for_prompt,
    build_portfolio_context,
    parse_ai_decisions,
    fill_missing_symbols,
    get_fallback_signals,
    _is_market_hours,
)
from config import config
from data.news_service import news_service
from data.technicals import format_for_prompt as format_technicals
from data.signal_aggregator import format_for_prompt as format_composite

logger = logging.getLogger(__name__)

try:
    from google import genai
    from google.genai import types as genai_types
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False
    logger.warning("google-genai package not available")


class GeminiAgent(BaseAgent):
    """AI trading agent using Google Gemini for market analysis."""

    def __init__(self):
        super().__init__(
            name="GeminiAgent",
            strategy_description="Google Gemini 2.0 Flash for fast, broad market analysis",
        )
        self._client: Optional[Any] = None
        self._analysis_interval: int = 10  # overridden dynamically each cycle
        self._open_interval: int = 10      # API call every N cycles during market hours (80% budget)
        self._closed_interval: int = 50    # API call every N cycles during off hours  (20% budget)
        self._cycle_count: int = 0
        self._last_decisions: Dict = {}
        self._backoff_until: float = 0.0   # epoch seconds — skip API until this time
        self._backoff_seconds: float = 120.0  # current backoff duration (doubles on repeat 429s)
        self._api_lock = asyncio.Lock()  # prevents duplicate concurrent API calls (separate from base _lock)
        self._call_timestamps: List[float] = []  # sliding window for hourly rate limit
        self._hourly_call_limit: int = 2
        self._daily_tokens: int = 0
        self._session_tokens: int = 0
        self._token_reset_day: Optional[date] = None

    def _get_client(self):
        if not HAS_GEMINI or not config.GEMINI_API_KEY:
            return None
        if self._client is None:
            self._client = genai.Client(api_key=config.GEMINI_API_KEY)
        return self._client

    def _build_prompt(self, market_context: Dict, watchlist: List[str]) -> str:
        portfolio_ctx = build_portfolio_context(self.portfolio)

        market_sections = []
        for symbol in watchlist:
            ctx = market_context.get(symbol, {})
            bars = ctx.get("bars")
            stats = ctx.get("stats", {})
            price = ctx.get("price", 0)

            bars_text      = format_bars_for_prompt(bars, limit=15) if bars is not None else "No data"
            news_items     = ctx.get("news", [])
            news_text      = news_service.format_for_prompt(symbol, news_items)
            ind            = ctx.get("indicators")
            tech_text      = format_technicals(symbol, ind, price)
            composite_sig  = ctx.get("composite_signal", {})
            composite_text = format_composite(composite_sig)

            section = f"""
## {symbol} - Current Price: ${price:.2f}
Stats: 1D: {stats.get('price_change_1d', 0):+.1f}%, 5D: {stats.get('price_change_5d', 0):+.1f}%, 20D: {stats.get('price_change_20d', 0):+.1f}%
52W High: ${stats.get('high_52w', 0):.2f} | 52W Low: ${stats.get('low_52w', 0):.2f}

### Multi-Source Composite Signal
{composite_text}

### Technical Indicators
{tech_text}

### Recent News
{news_text}

### OHLCV Data (last 30 days)
{bars_text}
"""
            market_sections.append(section)

        market_data = "\n".join(market_sections)

        # Overnight / after-hours catalysts from the news sentinel
        overnight = market_context.get("__overnight_catalysts__", [])
        if overnight:
            overnight_lines = []
            for c in overnight[:10]:
                sym_tag = f"[{c['symbol']}] " if c.get("symbol") else ""
                overnight_lines.append(
                    f"  • {sym_tag}{c['headline']} "
                    f"(score={c.get('score',0)}, {c.get('category','news')}, {c.get('date','')})"
                )
            overnight_section = "## Overnight / After-Hours Catalysts\n" + "\n".join(overnight_lines)
        else:
            overnight_section = ""

        return f"""You are an expert quantitative trader competing in a paper trading competition. Maximize risk-adjusted returns.

## Portfolio State
{portfolio_ctx}
{overnight_section}
## Market Data
{market_data}

## Task
Analyze each stock using technical indicators, news, and price action. Make trading decisions.

Decision framework:
- STRONG BUY: Bullish catalyst + RSI < 65 + positive MACD + price above SMA20
- STRONG SELL: Negative catalyst + RSI > 65 + negative MACD + price below SMA20
- HOLD: Mixed signals or already at target allocation

Rules:
1. Preserve capital — never risk more than {config.MAX_POSITION_SIZE*100:.0f}% per position
2. Only BUY with strong conviction (confidence >= 0.6)
3. SELL to protect profits or cut losses

## Response Format
Respond ONLY with a valid JSON object:
{{
  "market_analysis": "<overall market view in 2-3 sentences>",
  "decisions": [
    {{
      "symbol": "<TICKER>",
      "action": "BUY" | "SELL" | "HOLD",
      "shares": <number, 0 for HOLD>,
      "confidence": <float 0.0-1.0>,
      "reasoning": "<specific reasoning in 1-2 sentences>"
    }}
  ]
}}

Include an entry for every symbol: {', '.join(watchlist)}
"""

    async def _get_gemini_decisions(self, market_context: Dict, watchlist: List[str]) -> Optional[Dict]:
        client = self._get_client()
        if client is None:
            return None

        prompt = self._build_prompt(market_context, watchlist)

        # Sliding-window hourly rate limit (2 calls per hour)
        now = time.time()
        self._call_timestamps = [t for t in self._call_timestamps if now - t < 3600]
        if len(self._call_timestamps) >= self._hourly_call_limit:
            next_slot = self._call_timestamps[0] + 3600
            logger.warning(
                f"GeminiAgent: Hourly rate limit ({self._hourly_call_limit}/hr) reached — "
                f"skipping API call, next slot in {int(next_slot - now)}s"
            )
            return None

        try:
            response = await client.aio.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=4096,
                ),
            )

            text = response.text.strip() if response.text else ""
            if not text:
                logger.warning("GeminiAgent: Empty response")
                return None

            # Record timestamp and log token usage
            self._call_timestamps.append(time.time())
            today = date.today()
            if self._token_reset_day is None:
                self._token_reset_day = today
            elif self._token_reset_day != today:
                self._daily_tokens = 0
                self._token_reset_day = today
            usage = response.usage_metadata
            prompt_tok = usage.prompt_token_count
            candidate_tok = usage.candidates_token_count
            self._daily_tokens += prompt_tok + candidate_tok
            self._session_tokens += prompt_tok + candidate_tok
            logger.info(
                f"GeminiAgent: tokens — in={prompt_tok} out={candidate_tok} "
                f"daily_total={self._daily_tokens} | "
                f"calls_this_hour={len(self._call_timestamps)}/{self._hourly_call_limit}"
            )

            # Extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass

            try:
                return json.loads(text)
            except json.JSONDecodeError:
                logger.error(f"GeminiAgent: Could not parse JSON: {text[:200]}")
                return None

        except Exception as e:
            err = str(e)
            if "API_KEY_INVALID" in err or "API key not valid" in err:
                logger.warning("GeminiAgent: Invalid API key — update GEMINI_API_KEY in .env (get key at aistudio.google.com/app/apikey)")
                self._client = None
            elif "429" in err or "RESOURCE_EXHAUSTED" in err or "quota" in err.lower():
                self._backoff_until = time.time() + self._backoff_seconds
                logger.warning(
                    f"GeminiAgent: Rate limited (429) — backing off for {self._backoff_seconds:.0f}s"
                )
                self._backoff_seconds = min(self._backoff_seconds * 2, 600)  # cap at 10 min
            elif "PERMISSION_DENIED" in err:
                logger.warning(f"GeminiAgent: Permission denied: {err[:120]}")
            else:
                logger.error(f"GeminiAgent: API error: {err[:200]}")
            return None

    async def get_market_view(self, market_context: Dict, watchlist: List[str]) -> Optional[str]:
        """
        Return Gemini's market analysis as a plain-text string for use as
        context by other agents.  No trading signals are produced.
        Returns None when rate-limited or unconfigured.
        """
        response = await self._get_gemini_decisions(market_context, watchlist)
        if response:
            return response.get("market_analysis") or None
        return None

    async def analyze(self, market_context: Dict) -> List[Signal]:
        prices = {s: ctx.get("price", 0) for s, ctx in market_context.items() if isinstance(ctx, dict)}

        # Build watchlist prioritising held positions and own picks so they always
        # appear in the prompt rather than getting a blank HOLD from fill_missing_symbols.
        held  = set(self.portfolio.positions.keys())
        picks = set(self.get_pick_symbols())
        all_syms = [s for s in market_context.keys() if isinstance(market_context[s], dict)]
        watchlist = (
            [s for s in all_syms if s in held] +
            [s for s in all_syms if s in picks and s not in held] +
            [s for s in all_syms if s not in held and s not in picks]
        )

        # Force fresh API call if scanner added symbols not seen in the last prompt
        new_symbols = set(watchlist) - set(self._last_decisions.get("_watchlist", []))
        if new_symbols and self._last_decisions:
            logger.info(f"GeminiAgent: new scanner symbols {new_symbols} — forcing fresh analysis")
            self._cycle_count = 1

        # If a concurrent call is already fetching, wait and reuse its result
        if self._api_lock.locked():
            async with self._api_lock:
                pass  # wait for in-flight request to finish
            if self._last_decisions:
                return parse_ai_decisions(
                    self._last_decisions, market_context, prices,
                    self.portfolio, config.MAX_POSITION_SIZE, "GEMINI ANALYSIS"
                )
            return get_fallback_signals(market_context, "GeminiAgent")

        async with self._api_lock:
            self._analysis_interval = self._open_interval if _is_market_hours() else self._closed_interval
            self._cycle_count += 1

            # Reuse cached decisions between intervals to save API costs
            if self._cycle_count % self._analysis_interval != 1 and self._last_decisions:
                logger.debug(f"GeminiAgent: Replaying cached decisions (cycle {self._cycle_count})")
                signals = parse_ai_decisions(
                    self._last_decisions, market_context, prices,
                    self.portfolio, config.MAX_POSITION_SIZE, "GEMINI ANALYSIS"
                )
                return fill_missing_symbols(
                    signals, market_context, prices,
                    self.portfolio, self._picks, config.MAX_POSITION_SIZE, "GeminiAgent"
                )

            if not HAS_GEMINI or not config.GEMINI_API_KEY:
                logger.warning("GeminiAgent: Not configured, using fallback")
                return get_fallback_signals(market_context, "GeminiAgent")

            if time.time() < self._backoff_until:
                remaining = int(self._backoff_until - time.time())
                logger.debug(f"GeminiAgent: In backoff, {remaining}s remaining — reusing last decisions")
                if self._last_decisions:
                    return parse_ai_decisions(
                        self._last_decisions, market_context, prices,
                        self.portfolio, config.MAX_POSITION_SIZE, "GEMINI ANALYSIS"
                    )
                return get_fallback_signals(market_context, "GeminiAgent")

            logger.info(f"GeminiAgent: Requesting analysis from Gemini (cycle {self._cycle_count})")

            try:
                response = await self._get_gemini_decisions(market_context, watchlist)

                if response is None:
                    if self._last_decisions:
                        logger.debug("GeminiAgent: No response (rate limit or error) — replaying last decisions")
                        signals = parse_ai_decisions(
                            self._last_decisions, market_context, prices,
                            self.portfolio, config.MAX_POSITION_SIZE, "GEMINI ANALYSIS"
                        )
                        return fill_missing_symbols(
                            signals, market_context, prices,
                            self.portfolio, self._picks, config.MAX_POSITION_SIZE, "GeminiAgent"
                        )
                    logger.warning("GeminiAgent: No response and no cache — using fallback")
                    return get_fallback_signals(market_context, "GeminiAgent")

                response["_watchlist"] = watchlist
                self._last_decisions = response
                self._backoff_seconds = 120.0  # reset backoff on success

                signals = parse_ai_decisions(
                    response, market_context, prices,
                    self.portfolio, config.MAX_POSITION_SIZE, "GEMINI ANALYSIS"
                )
                signals = fill_missing_symbols(
                    signals, market_context, prices,
                    self.portfolio, self._picks, config.MAX_POSITION_SIZE, "GeminiAgent"
                )
                logger.info(f"GeminiAgent: Got {len(signals)} signals")
                return signals

            except Exception as e:
                logger.error(f"GeminiAgent: Error in analyze: {e}", exc_info=True)
                return get_fallback_signals(market_context, "GeminiAgent")
