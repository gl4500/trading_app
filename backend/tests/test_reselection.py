import unittest
import asyncio
from datetime import date, datetime, timezone
from typing import Dict, List

import pandas as pd

from agents.base_agent import BaseAgent, Signal
from backtest.reselection import run_backtest, BacktestResult
from config import config


class _FakeBars:
    """Rising price so a BUY on day 1 is in profit by the SELL on the last day."""
    def __init__(self, days, prices):
        self._days = days
        self._prices = dict(zip(days, prices))

    def trading_days(self, start, end):
        return [d for d in self._days if start <= d <= end]

    def close_asof(self, symbol, as_of):
        vals = [self._prices[d] for d in self._days if d <= as_of]
        return float(vals[-1]) if vals else None

    def bars_asof(self, symbol, as_of):
        rows = [(d, self._prices[d]) for d in self._days if d <= as_of]
        if not rows:
            return None
        idx = pd.to_datetime([d for d, _ in rows])
        return pd.DataFrame({"close": [p for _, p in rows], "volume": [1000] * len(rows)}, index=idx)


class _ScriptedAgent(BaseAgent):
    """BUY SYM on the first cycle, SELL it on the third. No pillars."""
    def __init__(self):
        super().__init__(name="ScriptedAgent", strategy_description="test")
        self._cycles = 0

    async def analyze(self, market_context: Dict) -> List[Signal]:
        self._cycles += 1
        if self._cycles == 1:
            return [Signal(action="BUY", symbol="SYM", confidence=0.5, shares=10,
                           reasoning="scripted buy")]
        if self._cycles == 3 and "SYM" in self.portfolio.positions:
            return [Signal(action="SELL", symbol="SYM", confidence=0.5,
                           shares=self.portfolio.positions["SYM"].shares, reasoning="scripted sell")]
        return [Signal(action="HOLD", symbol="SYM", confidence=0.0, shares=0, reasoning="hold")]


class TestRunBacktest(unittest.TestCase):
    def setUp(self):
        self.days = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
        self.bars = _FakeBars(self.days, [100.0, 110.0, 120.0])

    def test_engine_records_trades_and_realized_pnl(self):
        res = asyncio.run(run_backtest(
            _ScriptedAgent, universe=["SYM"],
            start=self.days[0], end=self.days[-1], bars=self.bars))
        self.assertIsInstance(res, BacktestResult)
        self.assertEqual(res.n_cycles, 3)
        actions = [t["action"] for t in res.trades]
        self.assertIn("BUY", actions)
        self.assertIn("SELL", actions)
        # bought 10 @ 100, sold 10 @ 120 -> +200 realized (Kelly may reduce shares;
        # assert sign + that realized equals (sell-buy)*executed_shares).
        buys = [t for t in res.trades if t["action"] == "BUY"]
        sold = [t for t in res.trades if t["action"] == "SELL"]
        expected = (sold[0]["price"] - buys[0]["price"]) * sold[0]["shares"]
        self.assertAlmostEqual(res.realized_pnl, expected, places=2)
        self.assertGreater(res.realized_pnl, 0.0)

    def test_config_overrides_are_restored(self):
        before = config.HIST_SEASONAL_WEIGHT
        asyncio.run(run_backtest(
            _ScriptedAgent, universe=["SYM"], start=self.days[0], end=self.days[-1],
            bars=self.bars, config_overrides={"HIST_SEASONAL_WEIGHT": 0.0}))
        self.assertEqual(config.HIST_SEASONAL_WEIGHT, before)
