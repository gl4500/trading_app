"""
Gemini Agent: Uses Google Gemini for market analysis and trading decisions.
Runs in parallel with ClaudeAgent as a second AI perspective in the ensemble.
"""
import asyncio
import json
import logging
import math
import re
from typing import Dict, List, Optional, Any
import pandas as pd

from agents.base_agent import BaseAgent, Signal
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


def _format_bars(bars: pd.DataFrame, limit: int = 30) -> str:
    if bars is None or bars.empty:
        return "No data available"
    recent = bars.tail(limit)
    lines = ["Date,Open,High,Low,Close,Volume"]
    for _, row in recent.iterrows():
        date = str(row.get("timestamp", "")).split("T")[0] if "timestamp" in row else "N/A"
        lines.append(
            f"{date},{row.get('open', 0):.2f},{row.get('high', 0):.2f},"
            f"{row.get('low', 0):.2f},{row.get('close', 0):.2f},"
            f"{int(row.get('volume', 0))}"
        )
    return "\n".join(lines)


def _build_portfolio_context(portfolio) -> str:
    lines = [f"Cash: ${portfolio.cash:,.2f}"]
    if portfolio.positions:
        lines.append("\nCurrent positions:")
        for sym, pos in portfolio.positions.items():
            lines.append(
                f"  {sym}: {pos.shares:.2f} shares @ avg ${pos.avg_cost:.2f} "
                f"(cost basis: ${pos.total_cost:,.2f})"
            )
    else:
        lines.append("No current positions (fully in cash)")
    lines.append(f"\nTotal cost basis: ${sum(p.total_cost for p in portfolio.positions.values()):,.2f}")
    return "\n".join(lines)


class GeminiAgent(BaseAgent):
    """AI trading agent using Google Gemini for market analysis."""

    def __init__(self):
        super().__init__(
            name="GeminiAgent",
            strategy_description="Google Gemini 2.0 Flash for fast, broad market analysis",
        )
        self._client: Optional[Any] = None
        self._analysis_interval: int = 10  # analyze every 10th cycle to stay within free-tier quota
        self._cycle_count: int = 0
        self._last_decisions: Dict = {}
        self._backoff_until: float = 0.0   # epoch seconds — skip API until this time
        self._backoff_seconds: float = 120.0  # current backoff duration (doubles on repeat 429s)
        self._api_lock = asyncio.Lock()  # prevents duplicate concurrent API calls (separate from base _lock)

    def _get_client(self):
        if not HAS_GEMINI or not config.GEMINI_API_KEY:
            return None
        if self._client is None:
            self._client = genai.Client(api_key=config.GEMINI_API_KEY)
        return self._client

    def _build_prompt(self, market_context: Dict, watchlist: List[str]) -> str:
        portfolio_ctx = _build_portfolio_context(self.portfolio)

        market_sections = []
        for symbol in watchlist:
            ctx = market_context.get(symbol, {})
            bars = ctx.get("bars")
            stats = ctx.get("stats", {})
            price = ctx.get("price", 0)

            bars_text      = _format_bars(bars, limit=15) if bars is not None else "No data"
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
                import time as _time
                self._backoff_until = _time.time() + self._backoff_seconds
                logger.warning(
                    f"GeminiAgent: Rate limited (429) — backing off for {self._backoff_seconds:.0f}s"
                )
                self._backoff_seconds = min(self._backoff_seconds * 2, 600)  # cap at 10 min
            elif "PERMISSION_DENIED" in err:
                logger.warning(f"GeminiAgent: Permission denied: {err[:120]}")
            else:
                logger.error(f"GeminiAgent: API error: {err[:200]}")
            return None

    def _parse_decisions(self, response: Dict, market_context: Dict,
                         prices: Dict[str, float]) -> List[Signal]:
        signals = []
        decisions = response.get("decisions", [])
        market_analysis = response.get("market_analysis", "")

        for decision in decisions:
            symbol = decision.get("symbol", "")
            action = decision.get("action", "HOLD").upper()
            shares_requested = float(decision.get("shares", 0))
            confidence = float(decision.get("confidence", 0.5))
            reasoning = decision.get("reasoning", "")

            if not symbol or symbol not in market_context:
                continue

            current_price = prices.get(symbol, 0)
            if current_price <= 0:
                signals.append(Signal(action="HOLD", symbol=symbol, confidence=0,
                                      shares=0, reasoning="No price data available"))
                continue

            if action == "BUY":
                portfolio_value = self.portfolio.get_total_value(prices)
                max_alloc = portfolio_value * config.MAX_POSITION_SIZE * confidence
                max_alloc = min(max_alloc, self.portfolio.cash * 0.95)
                max_shares = math.floor(max_alloc / current_price * 100) / 100
                shares = min(shares_requested, max_shares) if shares_requested > 0 else max_shares
                if shares < 0.01:
                    action = "HOLD"
                    shares = 0
            elif action == "SELL":
                if symbol not in self.portfolio.positions:
                    action = "HOLD"
                    shares = 0
                else:
                    pos = self.portfolio.positions[symbol]
                    shares = min(shares_requested if shares_requested > 0 else pos.shares, pos.shares)
            else:
                shares = 0

            full_reasoning = f"GEMINI ANALYSIS: {reasoning}"
            if market_analysis and symbol == list(market_context.keys())[0]:
                full_reasoning = f"MARKET VIEW: {market_analysis[:100]}. {full_reasoning}"

            signals.append(Signal(
                action=action, symbol=symbol, confidence=confidence,
                shares=shares, reasoning=full_reasoning,
            ))

        return signals

    def _get_fallback_signals(self, market_context: Dict) -> List[Signal]:
        return [
            Signal(action="HOLD", symbol=symbol, confidence=0.5, shares=0,
                   reasoning="GeminiAgent: API unavailable, holding positions")
            for symbol in market_context.keys()
        ]

    def _fill_missing(self, signals: List[Signal], market_context: Dict, prices: Dict[str, float]) -> List[Signal]:
        """
        Cover market_context symbols not included in Gemini's response.
        Replays stored pick conviction instead of a blank HOLD when available.
        """
        covered = {s.symbol for s in signals}
        for symbol in market_context:
            if symbol in covered:
                continue
            pick = self._picks.get(symbol)
            if pick and pick.get("action") == "BUY":
                current_price = prices.get(symbol, 0)
                confidence = float(pick.get("confidence", 0.5))
                shares = 0
                if current_price > 0 and symbol not in self.portfolio.positions:
                    import math
                    portfolio_value = self.portfolio.get_total_value(prices)
                    max_alloc = min(
                        portfolio_value * config.MAX_POSITION_SIZE * confidence,
                        self.portfolio.cash * 0.95,
                    )
                    shares = math.floor(max_alloc / current_price * 100) / 100
                signals.append(Signal(
                    action="BUY" if shares >= 0.01 else "HOLD",
                    symbol=symbol,
                    confidence=confidence,
                    shares=shares,
                    reasoning=f"GeminiAgent [pick replay]: {pick.get('reasoning', 'prior conviction')}",
                ))
            else:
                signals.append(Signal(
                    action="HOLD", symbol=symbol, confidence=0.5, shares=0,
                    reasoning="GeminiAgent: symbol not in current analysis window — HOLD",
                ))
        return signals

    async def analyze(self, market_context: Dict) -> List[Signal]:
        prices = {s: ctx.get("price", 0) for s, ctx in market_context.items()}

        # Build watchlist prioritising held positions and own picks so they always
        # appear in the prompt rather than getting a blank HOLD from _fill_missing.
        held  = set(self.portfolio.positions.keys())
        picks = set(self.get_pick_symbols())
        all_syms = list(market_context.keys())
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
                return self._parse_decisions(self._last_decisions, market_context, prices)
            return self._get_fallback_signals(market_context)

        async with self._api_lock:
            self._cycle_count += 1

            # Reuse cached decisions between intervals to save API costs
            if self._cycle_count % self._analysis_interval != 1 and self._last_decisions:
                logger.debug(f"GeminiAgent: Replaying cached decisions (cycle {self._cycle_count})")
                signals = self._parse_decisions(self._last_decisions, market_context, prices)
                return self._fill_missing(signals, market_context, prices)

            if not HAS_GEMINI or not config.GEMINI_API_KEY:
                logger.warning("GeminiAgent: Not configured, using fallback")
                return self._get_fallback_signals(market_context)

            import time as _time
            if _time.time() < self._backoff_until:
                remaining = int(self._backoff_until - _time.time())
                logger.debug(f"GeminiAgent: In backoff, {remaining}s remaining — reusing last decisions")
                if self._last_decisions:
                    return self._parse_decisions(self._last_decisions, market_context, prices)
                return self._get_fallback_signals(market_context)

            logger.info(f"GeminiAgent: Requesting analysis from Gemini (cycle {self._cycle_count})")

            try:
                response = await self._get_gemini_decisions(market_context, watchlist)

                if response is None:
                    logger.warning("GeminiAgent: No response, using fallback")
                    return self._get_fallback_signals(market_context)

                response["_watchlist"] = watchlist
                self._last_decisions = response
                self._backoff_seconds = 120.0  # reset backoff on success
                signals = self._parse_decisions(response, market_context, prices)
                signals = self._fill_missing(signals, market_context, prices)
                logger.info(f"GeminiAgent: Got {len(signals)} signals")
                return signals

            except Exception as e:
                logger.error(f"GeminiAgent: Error in analyze: {e}", exc_info=True)
                return self._get_fallback_signals(market_context)
