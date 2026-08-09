import unittest
import asyncio
import sqlite3
from pathlib import Path
from datetime import date

from agents.historical_trends_agent import HistoricalTrendsAgent
from backtest.bars_provider import BarsProvider
from backtest.reselection import run_backtest

HISTORY = Path(__file__).resolve().parent.parent / "data" / "history"
DB = Path(__file__).resolve().parent.parent / "trading.db"


def _live_universe_and_pnl():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        syms = [r[0] for r in con.execute(
            "SELECT DISTINCT t.symbol FROM trades t JOIN agents a ON a.id=t.agent_id "
            "WHERE a.name='HistoricalTrendsAgent'")]
        pnl = con.execute(
            "SELECT COALESCE(SUM(t.pnl),0) FROM trades t JOIN agents a ON a.id=t.agent_id "
            "WHERE a.name='HistoricalTrendsAgent' AND t.action='SELL'").fetchone()[0]
        return syms, float(pnl)
    finally:
        con.close()


@unittest.skipUnless(HISTORY.exists() and DB.exists(), "requires local history cache + trading.db")
class TestReselectionAcceptance(unittest.TestCase):
    """Trust gate: baseline must reproduce the live agent's realized PnL within +/-15%."""

    def test_baseline_reproduces_live_pnl_within_15pct(self):
        universe, live_pnl = _live_universe_and_pnl()
        bars = BarsProvider(HISTORY)
        res = asyncio.run(run_backtest(
            HistoricalTrendsAgent, universe=universe,
            start=date(2026, 3, 30), end=date(2026, 7, 31), bars=bars,
            config_overrides={"HIST_SEASONAL_WEIGHT": 0.20,
                              "HIST_PREARM_STOP_PCT": 0.0,
                              "HIST_CONFIDENCE_CAP": 0.0}))
        rel = abs(res.realized_pnl - live_pnl) / abs(live_pnl)
        print(f"\n[ACCEPTANCE] live={live_pnl:,.0f}  backtest={res.realized_pnl:,.0f}  "
              f"rel_err={rel:.1%}  trades={len(res.trades)}")
        self.assertLess(rel, 0.15, f"backtest {res.realized_pnl:,.0f} vs live {live_pnl:,.0f}")
