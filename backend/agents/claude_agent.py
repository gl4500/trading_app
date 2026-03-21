"""
Claude Agent: Uses Anthropic Claude Opus 4.6 with adaptive thinking for
deep market analysis and trading decisions.
"""
import asyncio
import json
import logging
import math
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
from data.learning_manager import get_learning_summary, record_trade
from data.news_service import news_service
try:
    from data.risk_assessor import get_assessment_context as _get_risk_assessment_context
    _HAS_RISK_ASSESSOR = True
except Exception:
    _HAS_RISK_ASSESSOR = False
from data.technicals import format_for_prompt as format_technicals
from data.signal_aggregator import format_for_prompt as format_composite
from database import save_token_log

logger = logging.getLogger(__name__)

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False
    logger.warning("Anthropic package not available")


class ClaudeAgent(BaseAgent):
    """AI trading agent using Claude Opus 4.6 with extended thinking."""

    def __init__(self):
        super().__init__(
            name="ClaudeAgent",
            strategy_description="Claude Opus 4.6 with adaptive thinking for deep market analysis",
        )
        self._client: Optional[Any] = None
        self._analysis_interval: int = 5  # overridden dynamically each cycle
        self._open_interval: int = 5      # API call every N cycles during market hours (80% budget)
        self._closed_interval: int = 25   # API call every N cycles during off hours  (20% budget)
        self._cycle_count: int = 0
        self._last_decisions: Dict[str, Dict] = {}
        self._backoff_until: float = 0.0   # epoch seconds — skip API until this time
        self._backoff_seconds: float = 60.0  # current backoff duration (doubles on repeat errors)
        self._api_lock = asyncio.Lock()  # prevents duplicate concurrent API calls (separate from base _lock)
        self._call_timestamps: List[float] = []  # sliding window for hourly rate limit
        self._hourly_call_limit: int = 2
        self._daily_tokens: int = 0
        self._session_tokens: int = 0
        self._token_reset_day: Optional[date] = None

    def _get_client(self):
        if not HAS_ANTHROPIC:
            return None
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        return self._client

    def _build_market_prompt(self, market_context: Dict, watchlist: List[str]) -> str:
        """Build comprehensive market analysis prompt for Claude."""
        portfolio_ctx = build_portfolio_context(self.portfolio)

        # Build market data section
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

### Multi-Source Composite Signal (weighted validity score)
{composite_text}

### Technical Indicators
{tech_text}

### News — Alpaca (last 24h)
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

        learning_ctx = get_learning_summary()

        assessment_ctx = ""
        try:
            if _HAS_RISK_ASSESSOR:
                assessment_ctx = _get_risk_assessment_context()
        except Exception:
            pass

        gemini_view = market_context.get("__gemini_market_view__")
        gemini_section = (
            f"\n## Gemini Market View\n{gemini_view}\n" if gemini_view else ""
        )

        macro_ctx = market_context.get("__massive_macro__", "")
        macro_section = f"\n{macro_ctx}\n" if macro_ctx else ""

        prompt = f"""You are an expert quantitative trader and portfolio manager competing in a trading competition. Your goal is to maximize risk-adjusted returns.

## Current Portfolio State
{portfolio_ctx}
{learning_ctx}{assessment_ctx}
{gemini_section}{macro_section}{overnight_section}
## Market Data
{market_data}

## Your Task
Analyze each stock using ALL three lenses together and make trading decisions:

**Signal Correlation Framework:**
- STRONG BUY: Bullish news catalyst + RSI not overbought (<65) + MACD positive/crossing + price above SMA20
- STRONG SELL: Negative news + RSI overbought (>65) + MACD negative/crossing + price below SMA20
- CONFLICTED (proceed cautiously): News and technicals disagree — e.g. positive news but RSI=80, or negative news but RSI=25 (oversold bounce possible)
- When signals diverge, prefer the technical picture for timing and news for direction

Additional considerations:
1. Risk management — don't over-concentrate, preserve capital
2. Correlation between current holdings
3. Portfolio cash available vs. target allocation

## Response Format
You must respond with ONLY a valid JSON object in this exact format:
{{
  "market_analysis": "<brief overall market assessment in 2-3 sentences>",
  "decisions": [
    {{
      "symbol": "<TICKER>",
      "action": "BUY" | "SELL" | "HOLD",
      "shares": <number, 0 for HOLD>,
      "confidence": <float 0.0-1.0>,
      "reasoning": "<specific reasoning for this stock in 1-2 sentences>"
    }}
  ]
}}

Include an entry for each symbol: {', '.join(watchlist)}
Only recommend BUY if you have strong conviction. Manage risk carefully.
"""
        return prompt

    async def _get_claude_decisions(self, market_context: Dict, watchlist: List[str]) -> Optional[Dict]:
        """Get trading decisions from Claude with adaptive thinking."""
        client = self._get_client()
        if client is None or not config.ANTHROPIC_API_KEY:
            return None

        prompt = self._build_market_prompt(market_context, watchlist)

        # Sliding-window hourly rate limit (2 calls per hour)
        now = time.time()
        self._call_timestamps = [t for t in self._call_timestamps if now - t < 3600]
        if len(self._call_timestamps) >= self._hourly_call_limit:
            next_slot = self._call_timestamps[0] + 3600
            logger.warning(
                f"ClaudeAgent: Hourly rate limit ({self._hourly_call_limit}/hr) reached — "
                f"skipping API call, next slot in {int(next_slot - now)}s"
            )
            return None

        try:
            response = await client.messages.create(
                model="claude-opus-4-6",
                max_tokens=5000,
                thinking={
                    "type": "adaptive",
                },
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            )

            # Extract text content from response
            text_content = ""
            for block in response.content:
                if block.type == "text":
                    text_content = block.text
                    break

            if not text_content:
                logger.warning("ClaudeAgent: No text content in response")
                return None

            # Record timestamp and log token usage
            self._call_timestamps.append(time.time())
            today = date.today()
            if self._token_reset_day is None:
                self._token_reset_day = today
            elif self._token_reset_day != today:
                self._daily_tokens = 0
                self._token_reset_day = today
            input_tok = response.usage.input_tokens
            output_tok = response.usage.output_tokens
            self._daily_tokens += input_tok + output_tok
            self._session_tokens += input_tok + output_tok
            logger.info(
                f"ClaudeAgent: tokens — in={input_tok} out={output_tok} "
                f"daily_total={self._daily_tokens} | "
                f"calls_this_hour={len(self._call_timestamps)}/{self._hourly_call_limit}"
            )
            try:
                await save_token_log(
                    agent="ClaudeAgent",
                    model="claude-opus-4-6",
                    prompt_tokens=input_tok,
                    completion_tokens=output_tok,
                    total_tokens=input_tok + output_tok,
                    daily_total=self._daily_tokens,
                    limit_hit=False,
                )
            except Exception as _e:
                logger.debug(f"ClaudeAgent: token log save failed: {_e}")

            # Try JSON block first, then direct parse
            json_match = re.search(r'\{[\s\S]*\}', text_content)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass

            try:
                return json.loads(text_content.strip())
            except json.JSONDecodeError:
                logger.error(f"ClaudeAgent: Could not parse JSON from response: {text_content[:200]}")
                return None

        except anthropic.APIStatusError as e:
            if e.status_code in (429, 529):  # rate limit or overloaded
                self._backoff_until = time.time() + self._backoff_seconds
                logger.warning(
                    f"ClaudeAgent: Rate limited ({e.status_code}) — backing off for {self._backoff_seconds:.0f}s"
                )
                self._backoff_seconds = min(self._backoff_seconds * 2, 600)
            elif e.status_code == 400:
                logger.error(f"ClaudeAgent: Bad request (400) — check API params: {e.message}")
            else:
                logger.error(f"ClaudeAgent: API error {e.status_code}: {e.message}")
            return None
        except anthropic.APIConnectionError as e:
            logger.error(f"ClaudeAgent: Connection error: {e}")
            return None
        except Exception as e:
            logger.error(f"ClaudeAgent: Unexpected error: {e}", exc_info=True)
            return None

    async def analyze(self, market_context: Dict) -> List[Signal]:
        """Analyze market using Claude with extended thinking."""
        prices = {s: ctx.get("price", 0) for s, ctx in market_context.items() if isinstance(ctx, dict)}

        # Build watchlist: core symbols + held positions + own picks + scanner extras,
        # capped at MAX_SYMBOLS so the prompt stays manageable.
        MAX_SYMBOLS = 12
        held  = set(self.portfolio.positions.keys())
        picks = set(self.get_pick_symbols())          # agent's own retained convictions
        core  = [s for s in config.WATCHLIST if s in market_context]
        extras = [s for s in market_context if s not in core]
        # Priority order: held → own picks → other extras
        prioritised_extras = (
            [s for s in extras if s in held] +
            [s for s in extras if s in picks and s not in held] +
            [s for s in extras if s not in held and s not in picks]
        )
        watchlist = (core + prioritised_extras)[:MAX_SYMBOLS]

        # Force a fresh API call if scanner has added symbols not seen in the last prompt
        new_symbols = set(watchlist) - set(self._last_decisions.get("_watchlist", []))
        if new_symbols and self._last_decisions:
            logger.info(f"ClaudeAgent: new scanner symbols detected {new_symbols} — forcing fresh analysis")
            self._cycle_count = 1  # reset so next check triggers an API call

        # If a concurrent call is already fetching, wait and reuse its result
        if self._api_lock.locked():
            async with self._api_lock:
                pass
            if self._last_decisions:
                return parse_ai_decisions(
                    self._last_decisions, market_context, prices,
                    self.portfolio, config.MAX_POSITION_SIZE, "CLAUDE ANALYSIS"
                )
            return get_fallback_signals(market_context, "ClaudeAgent")

        async with self._api_lock:
            self._analysis_interval = self._open_interval if _is_market_hours() else self._closed_interval
            self._cycle_count += 1

            # Only call Claude API every N cycles to manage costs
            if self._cycle_count % self._analysis_interval != 1 and self._last_decisions:
                logger.debug(f"ClaudeAgent: Replaying cached decisions (cycle {self._cycle_count})")
                signals = parse_ai_decisions(
                    self._last_decisions, market_context, prices,
                    self.portfolio, config.MAX_POSITION_SIZE, "CLAUDE ANALYSIS"
                )
                return fill_missing_symbols(
                    signals, market_context, prices,
                    self.portfolio, self._picks, config.MAX_POSITION_SIZE, "ClaudeAgent"
                )

            if not HAS_ANTHROPIC or not config.ANTHROPIC_API_KEY:
                logger.warning("ClaudeAgent: Anthropic not configured, using fallback")
                return get_fallback_signals(market_context, "ClaudeAgent")

            if time.time() < self._backoff_until:
                remaining = int(self._backoff_until - time.time())
                logger.debug(f"ClaudeAgent: In backoff, {remaining}s remaining — reusing last decisions")
                if self._last_decisions:
                    return parse_ai_decisions(
                        self._last_decisions, market_context, prices,
                        self.portfolio, config.MAX_POSITION_SIZE, "CLAUDE ANALYSIS"
                    )
                return get_fallback_signals(market_context, "ClaudeAgent")

            logger.info(f"ClaudeAgent: Requesting analysis from Claude (cycle {self._cycle_count})")

            try:
                claude_response = await self._get_claude_decisions(market_context, watchlist)

                if claude_response is None:
                    if self._last_decisions:
                        logger.debug("ClaudeAgent: No response (rate limit or error) — replaying last decisions")
                        signals = parse_ai_decisions(
                            self._last_decisions, market_context, prices,
                            self.portfolio, config.MAX_POSITION_SIZE, "CLAUDE ANALYSIS"
                        )
                        return fill_missing_symbols(
                            signals, market_context, prices,
                            self.portfolio, self._picks, config.MAX_POSITION_SIZE, "ClaudeAgent"
                        )
                    logger.warning("ClaudeAgent: No response and no cache — using fallback")
                    return get_fallback_signals(market_context, "ClaudeAgent")

                claude_response["_watchlist"] = watchlist
                self._last_decisions = claude_response
                self._backoff_seconds = 60.0  # reset backoff on success

                signals = parse_ai_decisions(
                    claude_response, market_context, prices,
                    self.portfolio, config.MAX_POSITION_SIZE, "CLAUDE ANALYSIS"
                )
                signals = fill_missing_symbols(
                    signals, market_context, prices,
                    self.portfolio, self._picks, config.MAX_POSITION_SIZE, "ClaudeAgent"
                )

                # Record completed SELL trades to learning file
                for signal in signals:
                    if signal.action == "SELL" and signal.symbol in self.portfolio.positions:
                        pos = self.portfolio.positions[signal.symbol]
                        sell_price = prices.get(signal.symbol, 0)
                        if sell_price > 0:
                            pnl = (sell_price - pos.avg_cost) * signal.shares
                            pnl_pct = (sell_price - pos.avg_cost) / pos.avg_cost * 100
                            buy_reasoning = next(
                                (t.reasoning for t in reversed(self.portfolio.trade_history)
                                 if t.symbol == signal.symbol and t.action == "BUY"),
                                "No buy reasoning recorded"
                            )
                            record_trade(
                                symbol=signal.symbol,
                                buy_price=pos.avg_cost,
                                sell_price=sell_price,
                                pnl=pnl,
                                pnl_pct=pnl_pct,
                                buy_reasoning=buy_reasoning,
                                sell_reasoning=signal.reasoning,
                                agent_name=self.name,
                            )

                logger.info(f"ClaudeAgent: Got {len(signals)} signals from Claude")
                return signals

            except Exception as e:
                logger.error(f"ClaudeAgent: Error in analyze: {e}", exc_info=True)
                return get_fallback_signals(market_context, "ClaudeAgent")
