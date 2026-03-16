"""
Claude Agent: Uses Anthropic Claude Opus 4.6 with adaptive thinking for
deep market analysis and trading decisions.
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
from data.learning_manager import get_learning_summary, record_trade
from data.news_service import news_service
from data.technicals import format_for_prompt as format_technicals
from data.signal_aggregator import format_for_prompt as format_composite

logger = logging.getLogger(__name__)

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False
    logger.warning("Anthropic package not available")


def _format_bars_for_claude(bars: pd.DataFrame, limit: int = 30) -> str:
    """Format OHLCV bars as readable text for Claude."""
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
    """Build portfolio context string for Claude."""
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

    lines.append(f"\nTotal portfolio cost basis: ${sum(p.total_cost for p in portfolio.positions.values()):,.2f}")
    return "\n".join(lines)


class ClaudeAgent(BaseAgent):
    """AI trading agent using Claude Opus 4.6 with extended thinking."""

    def __init__(self):
        super().__init__(
            name="ClaudeAgent",
            strategy_description="Claude Opus 4.6 with adaptive thinking for deep market analysis",
        )
        self._client: Optional[Any] = None
        self._analysis_interval: int = 5  # analyze every 5th cycle to manage API costs
        self._cycle_count: int = 0
        self._last_decisions: Dict[str, Dict] = {}
        self._backoff_until: float = 0.0   # epoch seconds — skip API until this time
        self._backoff_seconds: float = 60.0  # current backoff duration (doubles on repeat errors)
        self._api_lock = asyncio.Lock()  # prevents duplicate concurrent API calls (separate from base _lock)

    def _get_client(self):
        if not HAS_ANTHROPIC:
            return None
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        return self._client

    def _build_market_prompt(self, market_context: Dict, watchlist: List[str]) -> str:
        """Build comprehensive market analysis prompt for Claude."""
        portfolio_ctx = _build_portfolio_context(self.portfolio)

        # Build market data section
        market_sections = []
        for symbol in watchlist:
            ctx = market_context.get(symbol, {})
            bars = ctx.get("bars")
            stats = ctx.get("stats", {})
            price = ctx.get("price", 0)

            bars_text      = _format_bars_for_claude(bars, limit=15) if bars is not None else "No data"
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

        prompt = f"""You are an expert quantitative trader and portfolio manager competing in a trading competition. Your goal is to maximize risk-adjusted returns.

## Current Portfolio State
{portfolio_ctx}
{learning_ctx}
{overnight_section}
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
        if client is None:
            return None

        if not config.ANTHROPIC_API_KEY:
            return None

        prompt = self._build_market_prompt(market_context, watchlist)

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

            # Parse JSON from response
            # Try to find JSON block
            json_match = re.search(r'\{[\s\S]*\}', text_content)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass

            # Try direct parse
            try:
                return json.loads(text_content.strip())
            except json.JSONDecodeError:
                logger.error(f"ClaudeAgent: Could not parse JSON from response: {text_content[:200]}")
                return None

        except anthropic.APIStatusError as e:
            import time as _time
            if e.status_code in (429, 529):  # rate limit or overloaded
                self._backoff_until = _time.time() + self._backoff_seconds
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

    def _parse_decisions(self, claude_response: Dict, market_context: Dict,
                         prices: Dict[str, float]) -> List[Signal]:
        """Convert Claude's response into Signal objects."""
        signals = []
        decisions = claude_response.get("decisions", [])
        market_analysis = claude_response.get("market_analysis", "")

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
                signals.append(Signal(
                    action="HOLD", symbol=symbol, confidence=0, shares=0,
                    reasoning="No price data available"
                ))
                continue

            # Validate and adjust share counts
            if action == "BUY":
                # Calculate max affordable shares
                portfolio_value = self.portfolio.get_total_value(prices)
                max_alloc = portfolio_value * config.MAX_POSITION_SIZE * confidence
                max_alloc = min(max_alloc, self.portfolio.cash * 0.95)
                max_shares = math.floor(max_alloc / current_price * 100) / 100

                # Use Claude's suggestion but cap at max
                if shares_requested > 0:
                    shares = min(shares_requested, max_shares)
                else:
                    shares = max_shares

                if shares < 0.01:
                    action = "HOLD"
                    shares = 0

            elif action == "SELL":
                # Validate we have the position
                if symbol not in self.portfolio.positions:
                    action = "HOLD"
                    shares = 0
                else:
                    pos = self.portfolio.positions[symbol]
                    shares = min(shares_requested if shares_requested > 0 else pos.shares, pos.shares)
            else:
                shares = 0

            full_reasoning = f"CLAUDE ANALYSIS: {reasoning}"
            if market_analysis and symbol == list(market_context.keys())[0]:
                full_reasoning = f"MARKET VIEW: {market_analysis[:100]}. {full_reasoning}"

            signals.append(Signal(
                action=action,
                symbol=symbol,
                confidence=confidence,
                shares=shares,
                reasoning=full_reasoning,
            ))

        return signals

    def _fill_missing(self, signals: List[Signal], market_context: Dict, prices: Dict[str, float]) -> List[Signal]:
        """
        Cover any market_context symbols not included in Claude's analysis window.
        If the agent has a stored pick for the symbol, replay that conviction rather
        than emitting a blank HOLD.
        """
        covered = {s.symbol for s in signals}
        for symbol in market_context:
            if symbol in covered:
                continue
            pick = self._picks.get(symbol)
            if pick and pick.get("action") == "BUY":
                # Replay stored conviction — agent hasn't changed its mind,
                # the symbol just didn't fit in this cycle's prompt window.
                current_price = prices.get(symbol, 0)
                confidence = float(pick.get("confidence", 0.5))
                shares = 0
                if current_price > 0 and symbol not in self.portfolio.positions:
                    portfolio_value = self.portfolio.get_total_value(prices)
                    max_alloc = min(
                        portfolio_value * config.MAX_POSITION_SIZE * confidence,
                        self.portfolio.cash * 0.95,
                    )
                    import math
                    shares = math.floor(max_alloc / current_price * 100) / 100
                signals.append(Signal(
                    action="BUY" if shares >= 0.01 else "HOLD",
                    symbol=symbol,
                    confidence=confidence,
                    shares=shares,
                    reasoning=f"ClaudeAgent [pick replay]: {pick.get('reasoning', 'prior conviction')}",
                ))
            else:
                signals.append(Signal(
                    action="HOLD", symbol=symbol, confidence=0.5, shares=0,
                    reasoning="ClaudeAgent: symbol not in current analysis window — HOLD",
                ))
        return signals

    def _get_fallback_signals(self, market_context: Dict, prices: Dict[str, float]) -> List[Signal]:
        """Return HOLD signals when Claude is unavailable."""
        return [
            Signal(
                action="HOLD",
                symbol=symbol,
                confidence=0.5,
                shares=0,
                reasoning="ClaudeAgent: API unavailable, holding positions",
            )
            for symbol in market_context.keys()
        ]

    async def analyze(self, market_context: Dict) -> List[Signal]:
        """Analyze market using Claude with extended thinking."""
        prices = {s: ctx.get("price", 0) for s, ctx in market_context.items()}

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
                return self._parse_decisions(self._last_decisions, market_context, prices)
            return self._get_fallback_signals(market_context, prices)

        async with self._api_lock:
            self._cycle_count += 1

            # Only call Claude API every N cycles to manage costs
            if self._cycle_count % self._analysis_interval != 1 and self._last_decisions:
                logger.debug(f"ClaudeAgent: Replaying cached decisions (cycle {self._cycle_count})")
                signals = self._parse_decisions(self._last_decisions, market_context, prices)
                return self._fill_missing(signals, market_context, prices)

            if not HAS_ANTHROPIC or not config.ANTHROPIC_API_KEY:
                logger.warning("ClaudeAgent: Anthropic not configured, using fallback")
                return self._get_fallback_signals(market_context, prices)

            import time as _time
            if _time.time() < self._backoff_until:
                remaining = int(self._backoff_until - _time.time())
                logger.debug(f"ClaudeAgent: In backoff, {remaining}s remaining — reusing last decisions")
                if self._last_decisions:
                    return self._parse_decisions(self._last_decisions, market_context, prices)
                return self._get_fallback_signals(market_context, prices)

            logger.info(f"ClaudeAgent: Requesting analysis from Claude (cycle {self._cycle_count})")

            try:
                claude_response = await self._get_claude_decisions(market_context, watchlist)

                if claude_response is None:
                    logger.warning("ClaudeAgent: No response from Claude, using fallback")
                    return self._get_fallback_signals(market_context, prices)

                claude_response["_watchlist"] = watchlist
                self._last_decisions = claude_response
                self._backoff_seconds = 60.0  # reset backoff on success
                signals = self._parse_decisions(claude_response, market_context, prices)
                signals = self._fill_missing(signals, market_context, prices)

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
                return self._get_fallback_signals(market_context, prices)
