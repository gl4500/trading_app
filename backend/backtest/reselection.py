"""Full-chassis daily re-selection backtest engine.

Drives the REAL BaseAgent.run_cycle once per trading day over point-in-time bars,
so both entry re-selection and the live exit chassis (trailing/hard stop, Kelly,
risk manager) are faithful. Runs on a single event loop (run_cycle holds an
asyncio.Lock, so a fresh loop per day would break). Isolates the only two side
effects: file-writing _update_picks (stubbed) and the decision clock (injected).
Never touches the database or the live .env.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from agents.base_agent import BaseAgent
from backtest.bars_provider import BarsProvider
from config import config


@dataclass
class BacktestResult:
    realized_pnl: float
    final_equity: float
    equity_curve: List[Tuple[date, float]] = field(default_factory=list)
    trades: List[dict] = field(default_factory=list)
    n_cycles: int = 0


@contextmanager
def _override_config(overrides: Dict[str, Any]):
    saved = {k: getattr(config, k) for k in overrides}
    try:
        for k, v in overrides.items():
            setattr(config, k, v)
        yield
    finally:
        for k, v in saved.items():
            setattr(config, k, v)


def _asof_clock(day: date) -> Callable[[], datetime]:
    dt = datetime(day.year, day.month, day.day, 21, 0, tzinfo=timezone.utc)  # ~after US close
    return lambda: dt


async def run_backtest(
    agent_factory: Callable[[], BaseAgent],
    universe: List[str],
    start: date,
    end: date,
    bars: BarsProvider,
    config_overrides: Optional[Dict[str, Any]] = None,
) -> BacktestResult:
    with _override_config(config_overrides or {}):
        agent = agent_factory()
        agent._is_active = True
        agent._update_picks = lambda signals: None  # isolate file I/O side effect

        trades: List[dict] = []
        equity_curve: List[Tuple[date, float]] = []

        for day in bars.trading_days(start, end):
            agent._clock = _asof_clock(day)

            held = list(agent.portfolio.positions.keys())
            prices: Dict[str, float] = {}
            market_context: Dict[str, dict] = {}
            for sym in set(universe) | set(held):
                close = bars.close_asof(sym, day)
                if close is None:
                    continue
                prices[sym] = close
                b = bars.bars_asof(sym, day)
                if b is not None:
                    market_context[sym] = {"price": close, "long_term_bars": b}

            if not market_context:
                continue

            n_before = len(agent.portfolio.trade_history)
            await agent.run_cycle(market_context, prices)
            for tr in agent.portfolio.trade_history[n_before:]:
                trades.append({
                    "date": day.isoformat(), "symbol": tr.symbol, "action": tr.action,
                    "shares": tr.shares, "price": tr.price,
                    "reasoning": tr.reasoning, "pnl": tr.pnl,
                })
            equity_curve.append((day, agent.portfolio.get_total_value(prices)))

        realized = sum(t["pnl"] for t in trades if t["action"] == "SELL")
        final_equity = equity_curve[-1][1] if equity_curve else agent.portfolio.starting_capital
        return BacktestResult(
            realized_pnl=realized, final_equity=final_equity,
            equity_curve=equity_curve, trades=trades, n_cycles=len(equity_curve),
        )
