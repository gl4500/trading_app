"""
OpenClawAgent: Routes AI trading analysis through the local OpenClaw gateway.

OpenClaw exposes an OpenAI-compatible HTTP endpoint at 127.0.0.1:18789/v1.
This agent uses a compact single-line-per-symbol prompt (~500 tokens vs ~10k
for ClaudeAgent) so local models with smaller context windows can handle it.

Falls back gracefully if OpenClaw is not running or not configured.
"""
import asyncio
import json
import logging
import re
import time
from typing import Dict, List, Optional

from agents.base_agent import BaseAgent, Signal
from agents.agent_utils import (
    build_portfolio_context,
    parse_ai_decisions,
    fill_missing_symbols,
    get_fallback_signals,
)
from config import config

logger = logging.getLogger(__name__)

try:
    from openai import AsyncOpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    logger.warning("OpenClawAgent: openai package not available")


def _build_compact_prompt(
    market_context: Dict,
    watchlist: List[str],
    cash: float,
    positions: Dict,
) -> str:
    """
    Build a compact one-line-per-symbol prompt.
    Roughly 500 tokens for 10 symbols vs ~10,000 for the full prompt.
    """
    lines = [
        "You are a quantitative trader. Analyze the market snapshot and respond ONLY with valid JSON.",
        "",
        f"Portfolio: Cash=${cash:,.0f}",
    ]

    if positions:
        pos_parts = [f"{sym}({int(p.shares)}sh @${p.avg_cost:.2f})" for sym, p in positions.items()]
        lines.append("Positions: " + ", ".join(pos_parts))

    lines.append("")
    lines.append("Market snapshot (symbol price | 1D% 5D% | RSI MACD | top headline):")

    for sym in watchlist:
        ctx = market_context.get(sym)
        if not isinstance(ctx, dict):
            continue
        price  = ctx.get("price", 0)
        stats  = ctx.get("stats", {})
        d1     = stats.get("price_change_1d", 0)
        d5     = stats.get("price_change_5d", 0)
        ind    = ctx.get("indicators") or {}
        rsi    = ind.get("rsi", "?")
        macd   = ind.get("macd_signal", "?")
        news   = ctx.get("news", [])
        headline = news[0].get("headline", "") if news else "No news"
        if len(headline) > 100:
            headline = headline[:97] + "..."

        rsi_str  = f"{rsi:.0f}" if isinstance(rsi, (int, float)) else str(rsi)
        macd_str = str(macd)[:8]
        lines.append(
            f"{sym} ${price:.2f} | {d1:+.1f}% {d5:+.1f}% | RSI:{rsi_str} MACD:{macd_str} | {headline}"
        )

    lines += [
        "",
        f"Symbols to decide: {', '.join(watchlist)}",
        "",
        'Respond ONLY with this JSON (no markdown, no explanation):',
        '{"decisions": [{"symbol": "X", "action": "BUY"|"SELL"|"HOLD", "shares": 0, '
        '"confidence": 0.0, "reasoning": "..."}]}',
        "Include one entry per symbol. BUY only with confidence >= 0.6. "
        f"Max position size: {config.MAX_POSITION_SIZE * 100:.0f}% of portfolio.",
    ]

    return "\n".join(lines)


class OpenClawAgent(BaseAgent):
    """Local AI trading agent via OpenClaw gateway (OpenAI-compatible endpoint)."""

    def __init__(self):
        super().__init__(
            name="OpenClawAgent",
            strategy_description="Local AI model via OpenClaw gateway — low-latency, zero cloud cost",
        )
        self._cycle_count: int = 0
        self._call_interval: int = 3   # call every 3 cycles; local model is cheap
        self._last_decisions: Dict = {}
        self._api_lock = asyncio.Lock()
        self._available: Optional[bool] = None   # None=unchecked, True/False=known

    def _get_client(self) -> Optional["AsyncOpenAI"]:
        if not HAS_OPENAI:
            return None
        if not config.OPENCLAW_BASE_URL or not config.OPENCLAW_TOKEN:
            return None
        return AsyncOpenAI(
            base_url=config.OPENCLAW_BASE_URL,
            api_key=config.OPENCLAW_TOKEN,
        )

    @staticmethod
    def _parse_response(text: str) -> Optional[Dict]:
        """Extract JSON from model response, handling markdown code fences."""
        # Strip ```json ... ``` fences
        text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
        # Find outermost JSON object
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    async def _call_openclaw(
        self,
        market_context: Dict,
        watchlist: List[str],
    ) -> Optional[Dict]:
        client = self._get_client()
        if client is None:
            return None

        prompt = _build_compact_prompt(
            market_context,
            watchlist,
            cash=self.portfolio.cash,
            positions=self.portfolio.positions,
        )

        model = config.OPENCLAW_MODEL or "llama3.2"

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=1024,
            )
            text = response.choices[0].message.content or ""
            parsed = self._parse_response(text)
            if parsed is None:
                logger.warning(f"OpenClawAgent: could not parse JSON from response: {text[:200]}")
            else:
                self._available = True
            return parsed
        except (ConnectionRefusedError, ConnectionError, OSError) as e:
            if self._available is not False:
                logger.warning(f"OpenClawAgent: cannot reach OpenClaw at {config.OPENCLAW_BASE_URL} — {e}")
            self._available = False
            return None
        except Exception as e:
            err = str(e)
            if "connection" in err.lower() or "refused" in err.lower() or "connect" in err.lower():
                if self._available is not False:
                    logger.warning(f"OpenClawAgent: OpenClaw unavailable — {err[:120]}")
                self._available = False
            else:
                logger.error(f"OpenClawAgent: unexpected error — {err[:200]}")
            return None

    async def analyze(self, market_context: Dict) -> List[Signal]:
        if not config.OPENCLAW_BASE_URL or not config.OPENCLAW_TOKEN:
            return get_fallback_signals(market_context, "OpenClawAgent")

        prices = {
            sym: ctx.get("price", 0)
            for sym, ctx in market_context.items()
            if isinstance(ctx, dict)
        }

        held  = set(self.portfolio.positions.keys())
        picks = set(self.get_pick_symbols())
        core  = [s for s in config.WATCHLIST if s in market_context]
        extras = [s for s in market_context if s not in core and isinstance(market_context[s], dict)]
        watchlist = (core + [s for s in extras if s in held or s in picks])[:10]

        if self._api_lock.locked():
            async with self._api_lock:
                pass
            if self._last_decisions:
                return parse_ai_decisions(
                    self._last_decisions, market_context, prices,
                    self.portfolio, config.MAX_POSITION_SIZE, "OPENCLAW ANALYSIS"
                )
            return get_fallback_signals(market_context, "OpenClawAgent")

        async with self._api_lock:
            self._cycle_count += 1

            if self._cycle_count % self._call_interval != 1 and self._last_decisions:
                logger.debug(f"OpenClawAgent: replaying cached decisions (cycle {self._cycle_count})")
                signals = parse_ai_decisions(
                    self._last_decisions, market_context, prices,
                    self.portfolio, config.MAX_POSITION_SIZE, "OPENCLAW ANALYSIS"
                )
                return fill_missing_symbols(
                    signals, market_context, prices,
                    self.portfolio, self._picks, config.MAX_POSITION_SIZE, "OpenClawAgent"
                )

            logger.info(f"OpenClawAgent: requesting analysis (cycle {self._cycle_count})")
            result = await self._call_openclaw(market_context, watchlist)

            if result is None:
                if self._last_decisions:
                    signals = parse_ai_decisions(
                        self._last_decisions, market_context, prices,
                        self.portfolio, config.MAX_POSITION_SIZE, "OPENCLAW ANALYSIS"
                    )
                    return fill_missing_symbols(
                        signals, market_context, prices,
                        self.portfolio, self._picks, config.MAX_POSITION_SIZE, "OpenClawAgent"
                    )
                return get_fallback_signals(market_context, "OpenClawAgent")

            result["_watchlist"] = watchlist
            self._last_decisions = result

            signals = parse_ai_decisions(
                result, market_context, prices,
                self.portfolio, config.MAX_POSITION_SIZE, "OPENCLAW ANALYSIS"
            )
            signals = fill_missing_symbols(
                signals, market_context, prices,
                self.portfolio, self._picks, config.MAX_POSITION_SIZE, "OpenClawAgent"
            )
            logger.info(f"OpenClawAgent: got {len(signals)} signals from local model")
            return signals
