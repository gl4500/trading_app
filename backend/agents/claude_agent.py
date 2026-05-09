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
from typing import Dict, List, Optional, Any

from agents.base_agent import Signal
from agents.cloud_agent import CloudAgent
from agents.agent_utils import (
    extract_json,
    format_bars_for_prompt,
    build_portfolio_context,
    parse_ai_decisions,
    fill_missing_symbols,
    get_fallback_signals,
    _is_market_hours,
)
from config import config
from data.learning_manager import get_learning_summary, record_trade
from data.sector_analysis import format_sector_summary
from data.news_service import news_service
try:
    from data.risk_assessor import get_assessment_context as _get_risk_assessment_context
    _HAS_RISK_ASSESSOR = True
except Exception:
    _HAS_RISK_ASSESSOR = False
from data.technicals import format_for_prompt as format_technicals
from data.signal_aggregator import format_for_prompt as format_composite
from database import save_token_log, get_daily_token_total

logger = logging.getLogger(__name__)

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False
    logger.warning("Anthropic package not available")


class ClaudeAgent(CloudAgent):
    """AI trading agent using Claude Opus 4.6 with extended thinking."""

    def __init__(self):
        super().__init__(
            name="ClaudeAgent",
            strategy_description="Claude Opus 4.6 with adaptive thinking for deep market analysis",
            open_interval=5,    # API call every 5 cycles during market hours
            closed_interval=25, # API call every 25 cycles off-hours
            hourly_call_limit=config.CLAUDE_HOURLY_CALL_LIMIT,
            initial_backoff_seconds=60.0,
        )

    async def seed_from_history(self) -> None:
        """Restore rolling 24h token window from DB after a restart."""
        try:
            prior = await get_daily_token_total("ClaudeAgent", hours=24)
            if prior > 0:
                self._token_window.append((time.time(), prior))
        except Exception:
            pass

    def _get_client(self):
        if not HAS_ANTHROPIC:
            return None
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        return self._client

    # ── Static system text (cached across every call) ──────────────────────────

    _SYSTEM_TEXT: str = (
        "You are an expert quantitative trader and portfolio manager competing in a "
        "trading competition. Your goal is to maximize risk-adjusted returns.\n\n"
        "## Your Task\n"
        "Analyze each stock using ALL three lenses together and make trading decisions:\n\n"
        "**Signal Correlation Framework:**\n"
        "- STRONG BUY: Bullish news catalyst + RSI not overbought (<65) + MACD positive/crossing + price above SMA20\n"
        "- STRONG SELL: Negative news + RSI overbought (>65) + MACD negative/crossing + price below SMA20\n"
        "- CONFLICTED (proceed cautiously): News and technicals disagree — e.g. positive news but RSI=80, "
        "or negative news but RSI=25 (oversold bounce possible)\n"
        "- When signals diverge, prefer the technical picture for timing and news for direction\n\n"
        "Additional considerations:\n"
        "1. Risk management — don't over-concentrate, preserve capital\n"
        "2. Correlation between current holdings\n"
        "3. Portfolio cash available vs. target allocation\n\n"
        "## Response Format\n"
        'You must respond with ONLY a valid JSON object in this exact format:\n'
        "{\n"
        '  "market_analysis": "<brief overall market assessment in 2-3 sentences>",\n'
        '  "decisions": [\n'
        "    {\n"
        '      "symbol": "<TICKER>",\n'
        '      "action": "BUY" | "SELL" | "HOLD",\n'
        '      "shares": <number, 0 for HOLD>,\n'
        '      "confidence": <float 0.0-1.0>,\n'
        '      "reasoning": "<specific reasoning for this stock in 1-2 sentences>"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Only recommend BUY if you have strong conviction. Manage risk carefully.\n\n"
        "CRITICAL: Output raw JSON only. No markdown, no code fences (```), no explanation text "
        "before or after the JSON. The very first character of your response must be '{' and the "
        "very last character must be '}'."
    )

    def _build_stable_context(self, market_context: Dict) -> str:
        """
        Portfolio state + learning summary + macro context.
        Changes only when a trade executes, learning updates, or macro refreshes (15 min).
        """
        portfolio_ctx = build_portfolio_context(self.portfolio)
        learning_ctx  = get_learning_summary()
        assessment_ctx = ""
        try:
            if _HAS_RISK_ASSESSOR:
                assessment_ctx = _get_risk_assessment_context()
        except Exception:
            pass
        macro_ctx = market_context.get("__macro_context__", "")
        macro_section = f"\n\n{macro_ctx}" if macro_ctx else ""
        return (
            f"## Current Portfolio State\n{portfolio_ctx}\n"
            f"{learning_ctx}{assessment_ctx}{macro_section}"
        )

    def _build_dynamic_context(self, market_context: Dict, watchlist: List[str]) -> str:
        """
        Market data, prices, news, macro, sector context.
        Changes every trading cycle — never cached.
        """
        market_sections = []
        for symbol in watchlist:
            ctx = market_context.get(symbol, {})
            bars = ctx.get("bars")
            stats = ctx.get("stats", {})
            price = ctx.get("price", 0)

            bars_text       = format_bars_for_prompt(bars, limit=5) if bars is not None else "No data"
            news_items      = ctx.get("news", [])
            news_text       = news_service.format_for_prompt(symbol, news_items)
            ind             = ctx.get("indicators")
            tech_text       = format_technicals(symbol, ind, price)
            composite_sig   = ctx.get("composite_signal", {})
            composite_text  = format_composite(composite_sig)
            greeks_text     = ctx.get("greeks_text", "")
            sector_ctx_text = ctx.get("sector_context_text", "")

            greeks_section = f"\n{greeks_text}\n" if greeks_text else ""
            sector_line    = f"\n### Sector Context\n{sector_ctx_text}\n" if sector_ctx_text else ""

            section = f"""
## {symbol} - Current Price: ${price:.2f}
Stats: 1D: {stats.get('price_change_1d', 0):+.1f}%, 5D: {stats.get('price_change_5d', 0):+.1f}%, 20D: {stats.get('price_change_20d', 0):+.1f}%
52W High: ${stats.get('high_52w', 0):.2f} | 52W Low: ${stats.get('low_52w', 0):.2f}
{sector_line}
### Multi-Source Composite Signal (weighted validity score)
{composite_text}

### Technical Indicators
{tech_text}
{greeks_section}
### News — Alpaca (last 24h)
{news_text}

### OHLCV Data (last 30 days)
{bars_text}
"""
            market_sections.append(section)

        market_data = "\n".join(market_sections)

        overnight = market_context.get("__overnight_catalysts__", [])
        if isinstance(overnight, list) and overnight:
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

        gemini_view = market_context.get("__gemini_market_view__")
        gemini_section = f"\n## Gemini Market View\n{gemini_view}\n" if gemini_view else ""

        macro_ctx = market_context.get("__massive_macro__", "")
        macro_section = f"\n{macro_ctx}\n" if macro_ctx else ""

        sector_perf = market_context.get("__sector_context__", {})
        sector_summary = format_sector_summary(sector_perf)
        sector_section = f"\n## Macro → Sector Context\n{sector_summary}\n" if sector_summary else ""

        stooq_macro = market_context.get("__stooq_macro__", {})
        from data.stooq_client import format_macro_for_prompt as _fmt_macro
        stooq_macro_text = _fmt_macro(stooq_macro)
        stooq_section = f"\n## Market Indicators (VIX / Rates / Gold / DXY)\n{stooq_macro_text}\n" if stooq_macro_text else ""

        return (
            f"{gemini_section}{macro_section}{sector_section}{stooq_section}{overnight_section}"
            f"\n## Market Data\n{market_data}\n"
            f"\nInclude an entry for each symbol: {', '.join(watchlist)}"
        )

    def _build_market_prompt(self, market_context: Dict, watchlist: List[str]) -> str:
        """Full prompt as one string — used by existing tests and fallback logging."""
        stable  = self._build_stable_context(market_context)
        dynamic = self._build_dynamic_context(market_context, watchlist)
        return f"{self._SYSTEM_TEXT}\n\n{stable}\n{dynamic}"

    async def _get_claude_decisions(self, market_context: Dict, watchlist: List[str]) -> Optional[Dict]:
        """Get trading decisions from Claude with adaptive thinking and prompt caching."""
        client = self._get_client()
        if client is None or not config.ANTHROPIC_API_KEY:
            return None

        stable  = self._build_stable_context(market_context)
        dynamic = self._build_dynamic_context(market_context, watchlist)

        if not self._check_hourly_rate_limit(self._hourly_call_limit):
            return None

        try:
            response = await client.messages.create(
                model="claude-opus-4-6",
                max_tokens=5000,
                thinking={"type": "adaptive"},
                # Cached system prompt — static instructions, never changes
                system=[
                    {"type": "text", "text": self._SYSTEM_TEXT,
                     "cache_control": {"type": "ephemeral"}}
                ],
                messages=[
                    {
                        "role": "user",
                        "content": [
                            # Block 1 — stable: portfolio + learning (cache hit after first call)
                            {"type": "text", "text": stable,
                             "cache_control": {"type": "ephemeral"}},
                            # Block 2 — dynamic: market data, prices, news (never cached)
                            {"type": "text", "text": dynamic},
                        ],
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

            # Record timestamp and accumulate rolling 24h window
            self._call_timestamps.append(time.time())
            input_tok      = response.usage.input_tokens
            output_tok     = response.usage.output_tokens
            cache_create   = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
            cache_read     = getattr(response.usage, "cache_read_input_tokens", 0) or 0
            self._token_window.append((time.time(), input_tok + output_tok))
            self._session_tokens += input_tok + output_tok
            logger.info(
                f"ClaudeAgent: tokens — in={input_tok} out={output_tok} "
                f"cache_write={cache_create} cache_read={cache_read} "
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

            result = extract_json(text_content)
            if result is None:
                logger.error(f"ClaudeAgent: Could not parse JSON from response: {text_content[:200]}")
            return result

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
        """Analyze market using cloud Claude only.

        Local Ollama is handled by OllamaAgent — a separate ensemble member.
        Until 2026-05-08, this method routed between Claude / Ollama / hybrid
        modes via OLLAMA_ONLY_MODE / OLLAMA_HYBRID_MODE flags. That coupling
        meant a malformed Ollama response could crash the Claude code path
        (e.g. the `'str' object has no attribute 'get'` bug from PR #26).
        Now ClaudeAgent only ever calls Anthropic; Ollama is fully isolated.
        """
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

            # Cycle throttle: replay cached decisions between API calls.
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
            claude_response = await self._get_claude_decisions(market_context, watchlist)

            try:
                if claude_response is None:
                    if self._last_decisions:
                        logger.debug("ClaudeAgent: No response — replaying last decisions")
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

                logger.info(f"ClaudeAgent: Got {len(signals)} signals")
                return signals

            except Exception as e:
                logger.error(f"ClaudeAgent: Error in analyze: {e}", exc_info=True)
                return get_fallback_signals(market_context, "ClaudeAgent")
