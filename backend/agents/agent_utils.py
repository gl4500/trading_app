"""
Shared utilities for AI trading agents (ClaudeAgent, GeminiAgent).
Extracted to eliminate code duplication — both agents use identical
bar formatting, portfolio context, decision parsing, and fallback logic.
"""
import json
import math
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import pandas as pd

from agents.base_agent import Signal

logger = logging.getLogger(__name__)

_ET = timezone(timedelta(hours=-5))   # EST (NYSE standard; close enough for open/close gates)
_EDT = timezone(timedelta(hours=-4))  # EDT


def _et_now() -> datetime:
    """Return current time in US/Eastern (auto-adjusts for DST via UTC offset heuristic)."""
    utc = datetime.now(timezone.utc)
    # Simple DST heuristic: second Sunday in March → first Sunday in November
    year = utc.year
    dst_start = datetime(year, 3,  8, 2, tzinfo=timezone.utc) + timedelta(days=(6 - datetime(year, 3,  8).weekday()) % 7)
    dst_end   = datetime(year, 11, 1, 2, tzinfo=timezone.utc) + timedelta(days=(6 - datetime(year, 11, 1).weekday()) % 7)
    return utc.astimezone(_EDT if dst_start <= utc < dst_end else _ET)


def _is_market_hours() -> bool:
    """Return True during NYSE regular trading hours (09:30–15:59 ET, Mon–Fri)."""
    now = _et_now()
    if now.weekday() >= 5:
        return False
    h, m = now.hour, now.minute
    return (h == 9 and m >= 30) or (10 <= h <= 15)


def format_bars_for_prompt(bars: pd.DataFrame, limit: int = 30) -> str:
    """Format OHLCV bars as CSV text suitable for an AI prompt."""
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


def build_portfolio_context(portfolio) -> str:
    """Build a human-readable portfolio state string for an AI prompt."""
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
    lines.append(
        f"\nTotal portfolio cost basis: "
        f"${sum(p.total_cost for p in portfolio.positions.values()):,.2f}"
    )
    return "\n".join(lines)


def parse_ai_decisions(
    response: Dict,
    market_context: Dict,
    prices: Dict[str, float],
    portfolio,
    max_position_size: float,
    agent_prefix: str,
) -> List[Signal]:
    """
    Convert a structured AI response (decisions list) into Signal objects.

    agent_prefix: label prepended to reasoning, e.g. "CLAUDE ANALYSIS" or "GEMINI ANALYSIS".
    """
    signals = []
    decisions = response.get("decisions", [])
    market_analysis = response.get("market_analysis", "")
    # Attach market_analysis to first real (dict-valued) symbol only
    first_symbol = next(
        (k for k in market_context if isinstance(market_context.get(k), dict)), None
    )

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
            portfolio_value = portfolio.get_total_value(prices)
            max_alloc = portfolio_value * max_position_size * confidence
            max_alloc = min(max_alloc, portfolio.cash * 0.95)
            max_shares = math.floor(max_alloc / current_price * 100) / 100
            shares = min(shares_requested, max_shares) if shares_requested > 0 else max_shares
            if shares < 0.01:
                action = "HOLD"
                shares = 0
        elif action == "SELL":
            if symbol not in portfolio.positions:
                action = "HOLD"
                shares = 0
            else:
                pos = portfolio.positions[symbol]
                shares = min(shares_requested if shares_requested > 0 else pos.shares, pos.shares)
        else:
            shares = 0

        full_reasoning = f"{agent_prefix}: {reasoning}"
        if market_analysis and symbol == first_symbol:
            full_reasoning = f"MARKET VIEW: {market_analysis[:100]}. {full_reasoning}"

        signals.append(Signal(
            action=action, symbol=symbol, confidence=confidence,
            shares=shares, reasoning=full_reasoning,
        ))

    return signals


def fill_missing_symbols(
    signals: List[Signal],
    market_context: Dict,
    prices: Dict[str, float],
    portfolio,
    picks: Dict,
    max_position_size: float,
    agent_prefix: str,
) -> List[Signal]:
    """
    Add signals for any market_context symbols not covered by the provided list.
    Replays stored pick conviction instead of emitting a blank HOLD when available.
    """
    covered = {s.symbol for s in signals}
    for symbol in market_context:
        if symbol in covered or not isinstance(market_context.get(symbol), dict):
            continue
        pick = picks.get(symbol)
        if pick and pick.get("action") == "BUY":
            current_price = prices.get(symbol, 0)
            confidence = float(pick.get("confidence", 0.5))
            shares = 0
            if current_price > 0 and symbol not in portfolio.positions:
                portfolio_value = portfolio.get_total_value(prices)
                max_alloc = min(
                    portfolio_value * max_position_size * confidence,
                    portfolio.cash * 0.95,
                )
                shares = math.floor(max_alloc / current_price * 100) / 100
            signals.append(Signal(
                action="BUY" if shares >= 0.01 else "HOLD",
                symbol=symbol,
                confidence=confidence,
                shares=shares,
                reasoning=f"{agent_prefix} [pick replay]: {pick.get('reasoning', 'prior conviction')}",
            ))
        else:
            signals.append(Signal(
                action="HOLD", symbol=symbol, confidence=0.5, shares=0,
                reasoning=f"{agent_prefix}: symbol not in current analysis window — HOLD",
            ))
    return signals


def extract_json(text: str) -> Optional[Dict]:
    """Parse a JSON object from an LLM response string.

    Tries direct parse first (fast path for clean responses), then falls back
    to a regex search for the outermost ``{...}`` block (handles prose-wrapped
    or markdown-fenced output).  Returns None if no valid JSON object is found.
    """
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        pass
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group())
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def get_fallback_signals(market_context: Dict, agent_prefix: str) -> List[Signal]:
    """Return HOLD signals for all symbols when the agent's API is unavailable."""
    return [
        Signal(action="HOLD", symbol=symbol, confidence=0.5, shares=0,
               reasoning=f"{agent_prefix}: API unavailable, holding positions")
        for symbol in market_context.keys()
    ]
