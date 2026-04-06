"""
Unit tests for database.py (async SQLite layer).
Uses a temporary file-based DB for each test class.
Requires: aiosqlite
"""
import sys
import os
import asyncio
import tempfile
import unittest

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import database


def run(coro):
    """Run a coroutine in a fresh event loop (Python 3.12 compatible)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestDatabaseBase(unittest.TestCase):
    """Base class: creates a fresh temp DB before each test."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._orig_path = database.DB_PATH
        database.DB_PATH = self.db_path
        run(database.init_db())

    def tearDown(self):
        database.DB_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass


class TestInitDb(TestDatabaseBase):

    def test_init_creates_agents_table(self):
        # upsert_agent would fail if table didn't exist
        agent_id = run(database.upsert_agent("TestAgent", "test strategy"))
        self.assertIsInstance(agent_id, int)

    def test_init_idempotent(self):
        # Calling init_db twice should not raise
        run(database.init_db())

    def test_pnl_column_exists(self):
        # save_trade includes pnl — if column missing this would fail
        aid = run(database.upsert_agent("A", "s"))
        run(database.save_trade(aid, "AAPL", "BUY", 10, 150.0, "test"))


class TestUpsertAgent(TestDatabaseBase):

    def test_insert_returns_int(self):
        aid = run(database.upsert_agent("AgentX", "strategy X"))
        self.assertIsInstance(aid, int)
        self.assertGreater(aid, 0)

    def test_duplicate_name_returns_same_id(self):
        id1 = run(database.upsert_agent("AgentX", "s"))
        id2 = run(database.upsert_agent("AgentX", "s"))
        self.assertEqual(id1, id2)

    def test_different_agents_different_ids(self):
        id1 = run(database.upsert_agent("AgentA", "s"))
        id2 = run(database.upsert_agent("AgentB", "s"))
        self.assertNotEqual(id1, id2)


class TestSaveTrade(TestDatabaseBase):

    def setUp(self):
        super().setUp()
        self.aid = run(database.upsert_agent("TradeAgent", "trades"))

    def test_save_buy_trade(self):
        run(database.save_trade(self.aid, "AAPL", "BUY", 10, 150.0, "bought"))
        trades = run(database.get_agent_trades(self.aid))
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["symbol"], "AAPL")
        self.assertEqual(trades[0]["action"], "BUY")

    def test_save_sell_trade(self):
        run(database.save_trade(self.aid, "AAPL", "SELL", 10, 160.0, "sold"))
        trades = run(database.get_agent_trades(self.aid))
        self.assertEqual(trades[0]["action"], "SELL")

    def test_trade_includes_agent_name(self):
        run(database.save_trade(self.aid, "MSFT", "BUY", 5, 300.0, ""))
        trades = run(database.get_agent_trades())
        self.assertEqual(trades[0]["agent_name"], "TradeAgent")

    def test_limit_respected(self):
        for i in range(10):
            run(database.save_trade(self.aid, "AAPL", "BUY", 1, 100 + i, ""))
        trades = run(database.get_agent_trades(self.aid, limit=3))
        self.assertEqual(len(trades), 3)

    def test_get_trades_filtered_by_agent(self):
        aid2 = run(database.upsert_agent("OtherAgent", "other"))
        run(database.save_trade(self.aid,  "AAPL", "BUY", 1, 100.0, ""))
        run(database.save_trade(aid2, "MSFT", "BUY", 1, 300.0, ""))
        trades = run(database.get_agent_trades(self.aid))
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["symbol"], "AAPL")

    def test_pnl_persisted_for_sell(self):
        run(database.save_trade(self.aid, "AAPL", "SELL", 10, 160.0, "sold", pnl=100.0))
        trades = run(database.get_agent_trades(self.aid))
        self.assertAlmostEqual(trades[0]["pnl"], 100.0)

    def test_pnl_defaults_to_zero_for_buy(self):
        run(database.save_trade(self.aid, "AAPL", "BUY", 10, 150.0, "bought"))
        trades = run(database.get_agent_trades(self.aid))
        self.assertAlmostEqual(trades[0]["pnl"], 0.0)

    def test_negative_pnl_persisted(self):
        run(database.save_trade(self.aid, "AAPL", "SELL", 5, 140.0, "loss", pnl=-50.0))
        trades = run(database.get_agent_trades(self.aid))
        self.assertAlmostEqual(trades[0]["pnl"], -50.0)


class TestRecalculateTradePnl(TestDatabaseBase):

    def setUp(self):
        super().setUp()
        self.aid = run(database.upsert_agent("RecalcAgent", "recalc"))

    def _save(self, action, shares, price, pnl=0.0):
        run(database.save_trade(self.aid, "AAPL", action, shares, price, "", pnl))

    def _trades(self):
        return run(database.get_agent_trades(self.aid))

    def test_simple_buy_then_sell_profit(self):
        # Buy 10 @ $100, sell 10 @ $120 → pnl = $200
        self._save("BUY", 10, 100.0)
        self._save("SELL", 10, 120.0)
        run(database.recalculate_trade_pnl())
        trades = self._trades()  # returns DESC
        sell = next(t for t in trades if t["action"] == "SELL")
        self.assertAlmostEqual(sell["pnl"], 200.0)

    def test_simple_buy_then_sell_loss(self):
        # Buy 10 @ $100, sell 10 @ $90 → pnl = -$100
        self._save("BUY", 10, 100.0)
        self._save("SELL", 10, 90.0)
        run(database.recalculate_trade_pnl())
        sell = next(t for t in self._trades() if t["action"] == "SELL")
        self.assertAlmostEqual(sell["pnl"], -100.0)

    def test_partial_sell(self):
        # Buy 10 @ $100, sell 4 @ $110 → pnl = 4 * $10 = $40
        self._save("BUY", 10, 100.0)
        self._save("SELL", 4, 110.0)
        run(database.recalculate_trade_pnl())
        sell = next(t for t in self._trades() if t["action"] == "SELL")
        self.assertAlmostEqual(sell["pnl"], 40.0)

    def test_averaged_cost_basis(self):
        # Buy 10 @ $100, buy 10 @ $120 → avg = $110
        # Sell 10 @ $130 → pnl = 10 * $20 = $200
        self._save("BUY", 10, 100.0)
        self._save("BUY", 10, 120.0)
        self._save("SELL", 10, 130.0)
        run(database.recalculate_trade_pnl())
        sell = next(t for t in self._trades() if t["action"] == "SELL")
        self.assertAlmostEqual(sell["pnl"], 200.0)

    def test_buy_pnl_stays_zero(self):
        self._save("BUY", 10, 100.0)
        run(database.recalculate_trade_pnl())
        buy = next(t for t in self._trades() if t["action"] == "BUY")
        self.assertAlmostEqual(buy["pnl"], 0.0)

    def test_multiple_agents_isolated(self):
        aid2 = run(database.upsert_agent("OtherRecalc", "other"))
        run(database.save_trade(self.aid, "AAPL", "BUY", 10, 100.0, ""))
        run(database.save_trade(self.aid, "AAPL", "SELL", 10, 110.0, ""))
        run(database.save_trade(aid2, "MSFT", "BUY", 5, 200.0, ""))
        run(database.save_trade(aid2, "MSFT", "SELL", 5, 180.0, ""))
        run(database.recalculate_trade_pnl())
        agent1_sell = next(
            t for t in run(database.get_agent_trades(self.aid)) if t["action"] == "SELL"
        )
        agent2_sell = next(
            t for t in run(database.get_agent_trades(aid2)) if t["action"] == "SELL"
        )
        self.assertAlmostEqual(agent1_sell["pnl"], 100.0)
        self.assertAlmostEqual(agent2_sell["pnl"], -100.0)

    def test_idempotent(self):
        self._save("BUY", 10, 100.0)
        self._save("SELL", 10, 115.0)
        run(database.recalculate_trade_pnl())
        run(database.recalculate_trade_pnl())
        sell = next(t for t in self._trades() if t["action"] == "SELL")
        self.assertAlmostEqual(sell["pnl"], 150.0)


class TestSavePerformance(TestDatabaseBase):

    def setUp(self):
        super().setUp()
        self.aid = run(database.upsert_agent("PerfAgent", "perf"))

    def test_save_and_retrieve_performance(self):
        run(database.save_performance(self.aid, 105_000.0, 50_000.0, 5.0, 1.2, 0.6))
        history = run(database.get_performance_history(self.aid))
        self.assertEqual(len(history), 1)
        self.assertAlmostEqual(history[0]["total_value"], 105_000.0)
        self.assertAlmostEqual(history[0]["win_rate"], 0.6)

    def test_performance_history_ordered_asc(self):
        for i in range(3):
            run(database.save_performance(self.aid, 100_000 + i * 1000, 50_000.0, float(i), 0.0, 0.5))
        history = run(database.get_performance_history(self.aid))
        values = [h["total_value"] for h in history]
        self.assertEqual(values, sorted(values))


class TestResetDatabase(TestDatabaseBase):

    def test_reset_clears_all_data(self):
        aid = run(database.upsert_agent("AgentR", "reset test"))
        run(database.save_trade(aid, "AAPL", "BUY", 10, 150.0, ""))
        run(database.reset_database())
        # After reset: no agents → no trades
        trades = run(database.get_agent_trades())
        self.assertEqual(len(trades), 0)


class TestUpsertPortfolioPosition(TestDatabaseBase):

    def setUp(self):
        super().setUp()
        self.aid = run(database.upsert_agent("PortAgent", "portfolio"))

    def test_insert_position(self):
        run(database.upsert_portfolio_position(self.aid, "AAPL", 10, 150.0, 1600.0, 100.0))

    def test_delete_when_shares_zero(self):
        run(database.upsert_portfolio_position(self.aid, "AAPL", 10, 150.0, 1600.0, 100.0))
        # Selling all → shares=0 → should delete
        run(database.upsert_portfolio_position(self.aid, "AAPL", 0, 0, 0, 0))

    def test_last_price_stored_and_returned(self):
        """last_price is persisted and returned by get_portfolio_positions."""
        run(database.upsert_portfolio_position(
            self.aid, "AAPL", 10, 150.0, 1650.0, 150.0, last_price=165.0
        ))
        result = run(database.get_portfolio_positions(self.aid))
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["last_price"], 165.0)

    def test_last_price_defaults_to_zero(self):
        """Omitting last_price defaults to 0 (backward-compatible callers)."""
        run(database.upsert_portfolio_position(self.aid, "MSFT", 5, 300.0, 1550.0, 50.0))
        result = run(database.get_portfolio_positions(self.aid))
        self.assertAlmostEqual(result[0]["last_price"], 0.0)

    def test_last_price_updated_on_upsert(self):
        """Upserting an existing position updates last_price."""
        run(database.upsert_portfolio_position(
            self.aid, "AAPL", 10, 150.0, 1600.0, 100.0, last_price=160.0
        ))
        run(database.upsert_portfolio_position(
            self.aid, "AAPL", 10, 150.0, 1750.0, 250.0, last_price=175.0
        ))
        result = run(database.get_portfolio_positions(self.aid))
        self.assertAlmostEqual(result[0]["last_price"], 175.0)


class TestGetLatestCash(TestDatabaseBase):

    def setUp(self):
        super().setUp()
        self.aid = run(database.upsert_agent("CashAgent", "cash"))

    def test_returns_none_when_no_data(self):
        result = run(database.get_latest_cash(self.aid))
        self.assertIsNone(result)

    def test_returns_most_recent_cash(self):
        run(database.save_performance(self.aid, 105_000.0, 60_000.0, 5.0, 1.2, 0.6))
        run(database.save_performance(self.aid, 106_000.0, 55_000.0, 6.0, 1.3, 0.7))
        result = run(database.get_latest_cash(self.aid))
        self.assertAlmostEqual(result, 55_000.0)

    def test_isolated_by_agent(self):
        aid2 = run(database.upsert_agent("CashAgent2", "cash2"))
        run(database.save_performance(self.aid, 100_000.0, 80_000.0, 0.0, 0.0, 0.0))
        run(database.save_performance(aid2, 100_000.0, 70_000.0, 0.0, 0.0, 0.0))
        result = run(database.get_latest_cash(self.aid))
        self.assertAlmostEqual(result, 80_000.0)


class TestGetPortfolioPositions(TestDatabaseBase):

    def setUp(self):
        super().setUp()
        self.aid = run(database.upsert_agent("PosAgent", "positions"))

    def test_returns_empty_when_no_positions(self):
        result = run(database.get_portfolio_positions(self.aid))
        self.assertEqual(result, [])

    def test_returns_position_fields(self):
        run(database.upsert_portfolio_position(
            self.aid, "AAPL", 10, 150.0, 1600.0, 100.0, last_price=160.0
        ))
        result = run(database.get_portfolio_positions(self.aid))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["symbol"], "AAPL")
        self.assertAlmostEqual(result[0]["shares"], 10)
        self.assertAlmostEqual(result[0]["avg_cost"], 150.0)
        self.assertAlmostEqual(result[0]["last_price"], 160.0)

    def test_multiple_positions(self):
        run(database.upsert_portfolio_position(self.aid, "AAPL", 10, 150.0, 1600.0, 100.0))
        run(database.upsert_portfolio_position(self.aid, "MSFT", 5, 300.0, 1550.0, 50.0))
        result = run(database.get_portfolio_positions(self.aid))
        symbols = {r["symbol"] for r in result}
        self.assertEqual(symbols, {"AAPL", "MSFT"})

    def test_isolated_by_agent(self):
        aid2 = run(database.upsert_agent("PosAgent2", "p2"))
        run(database.upsert_portfolio_position(self.aid, "AAPL", 10, 150.0, 1600.0, 100.0))
        run(database.upsert_portfolio_position(aid2, "MSFT", 5, 300.0, 1550.0, 50.0))
        result = run(database.get_portfolio_positions(self.aid))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["symbol"], "AAPL")


class TestCleanupStalePositions(TestDatabaseBase):

    def setUp(self):
        super().setUp()
        self.aid = run(database.upsert_agent("CleanupAgent", "cleanup"))

    def test_removes_fully_sold_position(self):
        run(database.save_trade(self.aid, "LYFT", "BUY", 100, 14.0, ""))
        run(database.save_trade(self.aid, "LYFT", "SELL", 100, 14.09, ""))
        # Stale: DB still shows LYFT open
        run(database.upsert_portfolio_position(self.aid, "LYFT", 100, 14.0, 1400.0, 0.0))
        run(database.cleanup_stale_positions())
        positions = run(database.get_portfolio_positions(self.aid))
        symbols = [p["symbol"] for p in positions]
        self.assertNotIn("LYFT", symbols)

    def test_keeps_partially_open_position(self):
        run(database.save_trade(self.aid, "NVDA", "BUY", 50, 200.0, ""))
        run(database.save_trade(self.aid, "NVDA", "SELL", 20, 210.0, ""))
        run(database.upsert_portfolio_position(self.aid, "NVDA", 30, 200.0, 6300.0, 300.0))
        run(database.cleanup_stale_positions())
        positions = run(database.get_portfolio_positions(self.aid))
        symbols = [p["symbol"] for p in positions]
        self.assertIn("NVDA", symbols)

    def test_keeps_position_never_sold(self):
        run(database.save_trade(self.aid, "AAPL", "BUY", 10, 150.0, ""))
        run(database.upsert_portfolio_position(self.aid, "AAPL", 10, 150.0, 1600.0, 100.0))
        run(database.cleanup_stale_positions())
        positions = run(database.get_portfolio_positions(self.aid))
        self.assertEqual(len(positions), 1)

    def test_multiple_agents_isolated(self):
        aid2 = run(database.upsert_agent("CleanupAgent2", "c2"))
        # Agent1: sold LYFT (stale)
        run(database.save_trade(self.aid, "LYFT", "BUY", 100, 14.0, ""))
        run(database.save_trade(self.aid, "LYFT", "SELL", 100, 14.09, ""))
        run(database.upsert_portfolio_position(self.aid, "LYFT", 100, 14.0, 1400.0, 0.0))
        # Agent2: still holds MSFT
        run(database.save_trade(aid2, "MSFT", "BUY", 5, 300.0, ""))
        run(database.upsert_portfolio_position(aid2, "MSFT", 5, 300.0, 1550.0, 50.0))
        run(database.cleanup_stale_positions())
        self.assertEqual(run(database.get_portfolio_positions(self.aid)), [])
        self.assertEqual(len(run(database.get_portfolio_positions(aid2))), 1)

    def test_idempotent(self):
        run(database.save_trade(self.aid, "LYFT", "BUY", 100, 14.0, ""))
        run(database.save_trade(self.aid, "LYFT", "SELL", 100, 14.09, ""))
        run(database.upsert_portfolio_position(self.aid, "LYFT", 100, 14.0, 1400.0, 0.0))
        run(database.cleanup_stale_positions())
        run(database.cleanup_stale_positions())
        self.assertEqual(run(database.get_portfolio_positions(self.aid)), [])


class TestRestoreValueHistory(TestDatabaseBase):

    def setUp(self):
        super().setUp()
        self.aid = run(database.upsert_agent("HistAgent", "history"))

    def test_empty_when_no_performance_data(self):
        result = run(database.restore_value_history(self.aid))
        self.assertEqual(result, [])

    def test_returns_datetime_float_tuples(self):
        from datetime import datetime
        run(database.save_performance(self.aid, 105_000.0, 50_000.0, 5.0, 1.2, 0.6))
        result = run(database.restore_value_history(self.aid))
        self.assertEqual(len(result), 1)
        ts, val = result[0]
        self.assertIsInstance(ts, datetime)
        self.assertAlmostEqual(val, 105_000.0)

    def test_ordered_ascending(self):
        for v in [100_000.0, 101_000.0, 102_000.0]:
            run(database.save_performance(self.aid, v, 50_000.0, 0.0, 0.0, 0.0))
        result = run(database.restore_value_history(self.aid))
        values = [v for _, v in result]
        self.assertEqual(values, sorted(values))

    def test_limit_respected(self):
        for i in range(10):
            run(database.save_performance(self.aid, 100_000.0 + i, 50_000.0, 0.0, 0.0, 0.0))
        result = run(database.restore_value_history(self.aid, limit=5))
        self.assertEqual(len(result), 5)

    def test_different_agents_isolated(self):
        aid2 = run(database.upsert_agent("OtherHistAgent", "other"))
        run(database.save_performance(self.aid, 110_000.0, 50_000.0, 10.0, 1.0, 0.5))
        run(database.save_performance(aid2, 99_000.0, 50_000.0, -1.0, 0.0, 0.0))
        result = run(database.restore_value_history(self.aid))
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0][1], 110_000.0)


class TestTokenLog(TestDatabaseBase):

    def test_save_and_retrieve_basic(self):
        run(database.save_token_log("SentimentAgent", "gpt-4o-mini", 120, 80, 200, 200, False, daily_limit=10_000))
        rows = run(database.get_token_log())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["agent"], "SentimentAgent")
        self.assertEqual(rows[0]["model"], "gpt-4o-mini")
        self.assertEqual(rows[0]["prompt_tokens"], 120)
        self.assertEqual(rows[0]["completion_tokens"], 80)
        self.assertEqual(rows[0]["total_tokens"], 200)
        self.assertEqual(rows[0]["daily_total"], 200)
        self.assertEqual(rows[0]["daily_limit"], 10_000)
        self.assertFalse(rows[0]["limit_hit"])

    def test_limit_hit_flagged(self):
        run(database.save_token_log("SentimentAgent", "gpt-4o-mini", 0, 0, 0, 10_000, True))
        rows = run(database.get_token_log())
        self.assertTrue(rows[0]["limit_hit"])

    def test_filter_by_agent(self):
        run(database.save_token_log("ClaudeAgent", "claude-opus-4-6", 500, 200, 700, 5000, False))
        run(database.save_token_log("SentimentAgent", "gpt-4o-mini", 100, 50, 150, 500, False))
        rows = run(database.get_token_log(agent="ClaudeAgent"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["agent"], "ClaudeAgent")

    def test_filter_limit_hit_only(self):
        run(database.save_token_log("SentimentAgent", "gpt-4o-mini", 100, 50, 150, 9000, False))
        run(database.save_token_log("SentimentAgent", "gpt-4o-mini", 0, 0, 0, 10_000, True))
        rows = run(database.get_token_log(limit_hit_only=True))
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["limit_hit"])

    def test_multiple_agents_all_returned(self):
        run(database.save_token_log("ClaudeAgent", "claude-opus-4-6", 500, 200, 700, 700, False))
        run(database.save_token_log("GeminiAgent", "gemini-2.0-flash", 300, 100, 400, 400, False))
        run(database.save_token_log("SentimentAgent", "gpt-4o-mini", 100, 50, 150, 150, False))
        rows = run(database.get_token_log())
        self.assertEqual(len(rows), 3)

    def test_cleanup_removes_old_rows(self):
        import aiosqlite
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        _ET = ZoneInfo("America/New_York")

        async def insert_old():
            old_ts = (datetime.now(_ET) - timedelta(hours=25)).isoformat()
            async with aiosqlite.connect(database.DB_PATH) as db:
                await db.execute(
                    """INSERT INTO token_log
                       (timestamp, agent, model, prompt_tokens, completion_tokens,
                        total_tokens, daily_total, daily_limit, limit_hit)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (old_ts, "OldAgent", "old-model", 10, 5, 15, 15, None, 0)
                )
                await db.commit()

        run(insert_old())
        run(database.save_token_log("NewAgent", "new-model", 10, 5, 15, 15, False))
        run(database.cleanup_token_log(hours=24))
        rows = run(database.get_token_log())
        agents = [r["agent"] for r in rows]
        self.assertNotIn("OldAgent", agents)
        self.assertIn("NewAgent", agents)

    def test_rows_ordered_newest_first(self):
        run(database.save_token_log("A", "m", 10, 5, 15, 15, False))
        run(database.save_token_log("B", "m", 20, 10, 30, 30, False))
        rows = run(database.get_token_log())
        self.assertEqual(rows[0]["agent"], "B")

    def test_daily_limit_none_stored(self):
        run(database.save_token_log("GeminiAgent", "gemini-2.0-flash", 300, 100, 400, 400, False, daily_limit=None))
        rows = run(database.get_token_log())
        self.assertIsNone(rows[0]["daily_limit"])

    def test_hours_zero_returns_all_entries(self):
        """hours=0 means all-time — entries older than 24h should be included."""
        import aiosqlite
        from datetime import datetime, timedelta

        async def insert_old():
            old_ts = (datetime.utcnow() - timedelta(hours=48)).isoformat()
            async with aiosqlite.connect(database.DB_PATH) as db:
                await db.execute(
                    """INSERT INTO token_log
                       (timestamp, agent, model, prompt_tokens, completion_tokens,
                        total_tokens, daily_total, daily_limit, limit_hit)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (old_ts, "OldAgent", "old-model", 10, 5, 15, 15, None, 0)
                )
                await db.commit()

        run(insert_old())
        run(database.save_token_log("NewAgent", "new-model", 10, 5, 15, 15, False))

        # Default hours=24 should NOT return the 48h-old entry
        rows_24h = run(database.get_token_log(hours=24))
        agents_24h = [r["agent"] for r in rows_24h]
        self.assertNotIn("OldAgent", agents_24h)
        self.assertIn("NewAgent", agents_24h)

        # hours=0 should return ALL entries including the old one
        rows_all = run(database.get_token_log(hours=0))
        agents_all = [r["agent"] for r in rows_all]
        self.assertIn("OldAgent", agents_all)
        self.assertIn("NewAgent", agents_all)

    def test_hours_zero_with_agent_filter(self):
        """hours=0 + agent filter returns only matching agent across all time."""
        import aiosqlite
        from datetime import datetime, timedelta

        async def insert_old():
            old_ts = (datetime.utcnow() - timedelta(hours=48)).isoformat()
            async with aiosqlite.connect(database.DB_PATH) as db:
                await db.execute(
                    """INSERT INTO token_log
                       (timestamp, agent, model, prompt_tokens, completion_tokens,
                        total_tokens, daily_total, daily_limit, limit_hit)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (old_ts, "ClaudeAgent", "claude-opus-4-6", 500, 200, 700, 700, None, 0)
                )
                await db.commit()

        run(insert_old())
        run(database.save_token_log("SentimentAgent", "gpt-4o-mini", 100, 50, 150, 150, False))

        rows = run(database.get_token_log(hours=0, agent="ClaudeAgent"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["agent"], "ClaudeAgent")


class TestNewsPriceSnapshots(TestDatabaseBase):
    """Tests for save_price_snapshot / update_price_snapshot / get_price_snapshots."""

    def _snap(self, symbol="AAPL", score=3, category="macro",
              during_session=False, price_at=150.0,
              detected_at="2024-01-02T00:00:00Z"):
        return {
            "symbol":           symbol,
            "headline":         "Test catalyst headline",
            "score":            score,
            "category":         category,
            "price_at":         price_at,
            "detected_at":      detected_at,
            "during_session":   during_session,
            "price_open":       None,
            "price_1h":         None,
            "change_open":      None,
            "change_1h":        None,
            "open_recorded_at": None,
        }

    def test_save_returns_integer_id(self):
        snap_id = run(database.save_price_snapshot(self._snap()))
        self.assertIsInstance(snap_id, int)
        self.assertGreater(snap_id, 0)

    def test_save_persists_core_fields(self):
        run(database.save_price_snapshot(self._snap(symbol="MSFT", score=4, category="policy")))
        rows = run(database.get_price_snapshots())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "MSFT")
        self.assertEqual(rows[0]["score"], 4)
        self.assertEqual(rows[0]["category"], "policy")

    def test_save_persists_during_session_flag(self):
        run(database.save_price_snapshot(self._snap(during_session=True)))
        rows = run(database.get_price_snapshots())
        self.assertTrue(rows[0]["during_session"])

    def test_update_sets_price_open(self):
        snap_id = run(database.save_price_snapshot(self._snap()))
        run(database.update_price_snapshot(snap_id, price_open=155.0, change_open=3.33))
        rows = run(database.get_price_snapshots())
        self.assertAlmostEqual(rows[0]["price_open"], 155.0)
        self.assertAlmostEqual(rows[0]["change_open"], 3.33)

    def test_update_sets_price_1h(self):
        snap_id = run(database.save_price_snapshot(self._snap()))
        run(database.update_price_snapshot(snap_id, price_1h=158.0, change_1h=5.33))
        rows = run(database.get_price_snapshots())
        self.assertAlmostEqual(rows[0]["price_1h"], 158.0)
        self.assertAlmostEqual(rows[0]["change_1h"], 5.33)

    def test_update_sets_open_recorded_at(self):
        snap_id = run(database.save_price_snapshot(self._snap()))
        run(database.update_price_snapshot(snap_id, open_recorded_at="2024-01-02T09:35:00"))
        rows = run(database.get_price_snapshots())
        self.assertEqual(rows[0]["open_recorded_at"], "2024-01-02T09:35:00")

    def test_get_returns_newest_first(self):
        run(database.save_price_snapshot(self._snap(symbol="AAPL", detected_at="2024-01-01T00:00:00Z")))
        run(database.save_price_snapshot(self._snap(symbol="MSFT", detected_at="2024-01-02T00:00:00Z")))
        rows = run(database.get_price_snapshots())
        self.assertEqual(rows[0]["symbol"], "MSFT")

    def test_get_limited_to_100(self):
        for i in range(110):
            run(database.save_price_snapshot(self._snap(symbol=f"S{i:03d}")))
        rows = run(database.get_price_snapshots())
        self.assertEqual(len(rows), 100)

    def test_get_returns_empty_list_when_none(self):
        rows = run(database.get_price_snapshots())
        self.assertEqual(rows, [])

    def test_multiple_snapshots_same_symbol(self):
        run(database.save_price_snapshot(self._snap(symbol="AAPL", detected_at="2024-01-01T00:00:00Z")))
        run(database.save_price_snapshot(self._snap(symbol="AAPL", detected_at="2024-01-02T00:00:00Z")))
        rows = run(database.get_price_snapshots())
        self.assertEqual(len(rows), 2)


class TestTokenLogTimezone(TestDatabaseBase):
    """Timestamps written by save_token_log must be in Eastern Time."""

    def test_timestamp_has_eastern_offset(self):
        """Saved timestamp must include a -05:00 or -04:00 UTC offset (EST/EDT)."""
        run(database.save_token_log("ClaudeAgent", "claude-opus-4-6", 100, 50, 150, 150, False))
        rows = run(database.get_token_log())
        ts = rows[0]["timestamp"]
        # Must contain an Eastern offset: -05:00 (EST) or -04:00 (EDT)
        self.assertTrue(
            ts.endswith("-05:00") or ts.endswith("-04:00"),
            f"Expected Eastern offset in timestamp, got: {ts}"
        )

    def test_timestamp_is_not_utc(self):
        """Timestamp must not be a bare UTC value (no +00:00 or Z suffix)."""
        run(database.save_token_log("ClaudeAgent", "claude-opus-4-6", 100, 50, 150, 150, False))
        rows = run(database.get_token_log())
        ts = rows[0]["timestamp"]
        self.assertFalse(ts.endswith("+00:00"), f"Timestamp is UTC: {ts}")
        self.assertFalse(ts.endswith("Z"), f"Timestamp is UTC: {ts}")


class TestGetAgentCallsThisHour(TestDatabaseBase):
    """get_agent_calls_this_hour returns count of non-limit-hit calls in the last 60 min."""

    def test_counts_recent_calls(self):
        run(database.save_token_log("ScannerAgent/Claude", "claude-opus-4-6", 10000, 1500, 11500, 11500, False))
        run(database.save_token_log("ScannerAgent/Claude", "claude-opus-4-6", 10000, 1500, 11500, 23000, False))
        result = run(database.get_agent_calls_this_hour("ScannerAgent/Claude"))
        self.assertEqual(result, 2)

    def test_excludes_other_agents(self):
        run(database.save_token_log("ScannerAgent/Claude", "claude-opus-4-6", 10000, 1500, 11500, 11500, False))
        run(database.save_token_log("ScannerAgent/Gemini", "gemini-2.0-flash", 8000, 1000, 9000, 9000, False))
        result = run(database.get_agent_calls_this_hour("ScannerAgent/Claude"))
        self.assertEqual(result, 1)

    def test_excludes_limit_hit_rows(self):
        run(database.save_token_log("ScannerAgent/Claude", "claude-opus-4-6", 10000, 1500, 11500, 11500, False))
        run(database.save_token_log("ScannerAgent/Claude", "claude-opus-4-6", 0, 0, 0, 11500, True))
        result = run(database.get_agent_calls_this_hour("ScannerAgent/Claude"))
        self.assertEqual(result, 1)

    def test_excludes_old_entries(self):
        import aiosqlite
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        _ET = ZoneInfo("America/New_York")

        async def insert_old():
            old_ts = (datetime.now(_ET) - timedelta(hours=2)).isoformat()
            async with aiosqlite.connect(database.DB_PATH) as db:
                await db.execute(
                    """INSERT INTO token_log
                       (timestamp, agent, model, prompt_tokens, completion_tokens,
                        total_tokens, daily_total, daily_limit, limit_hit)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (old_ts, "ScannerAgent/Claude", "claude-opus-4-6", 10000, 1500, 11500, 11500, None, 0)
                )
                await db.commit()

        run(insert_old())
        result = run(database.get_agent_calls_this_hour("ScannerAgent/Claude"))
        self.assertEqual(result, 0)

    def test_returns_zero_when_no_calls(self):
        result = run(database.get_agent_calls_this_hour("ScannerAgent/OpenAI"))
        self.assertEqual(result, 0)


class TestPrunePerformanceTable(TestDatabaseBase):
    """Tests for database.prune_performance_table."""

    def _insert_performance(self, agent_id: int, timestamp: str, value: float = 1000.0):
        """Helper: insert a single performance row with an explicit timestamp."""
        import aiosqlite

        async def _do():
            async with aiosqlite.connect(database.DB_PATH) as db:
                await db.execute(
                    """INSERT INTO performance
                       (agent_id, timestamp, total_value, cash, total_return_pct, sharpe_ratio, win_rate)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (agent_id, timestamp, value, 500.0, 0.0, 0.0, 0.5),
                )
                await db.commit()

        run(_do())

    def _count_performance(self) -> int:
        import aiosqlite

        async def _do():
            async with aiosqlite.connect(database.DB_PATH) as db:
                cursor = await db.execute("SELECT COUNT(*) FROM performance")
                row = await cursor.fetchone()
                return row[0]

        return run(_do())

    def test_deletes_old_rows(self):
        from datetime import datetime, timedelta
        aid = run(database.upsert_agent("TestAgent", "test strategy"))
        old_ts = (datetime.utcnow() - timedelta(days=10)).isoformat()
        self._insert_performance(aid, old_ts)
        deleted = run(database.prune_performance_table(days=3))
        self.assertEqual(deleted, 1)
        self.assertEqual(self._count_performance(), 0)

    def test_keeps_recent_rows(self):
        from datetime import datetime, timedelta
        aid = run(database.upsert_agent("TestAgent", "test strategy"))
        recent_ts = (datetime.utcnow() - timedelta(hours=1)).isoformat()
        self._insert_performance(aid, recent_ts)
        deleted = run(database.prune_performance_table(days=3))
        self.assertEqual(deleted, 0)
        self.assertEqual(self._count_performance(), 1)

    def test_returns_zero_when_table_empty(self):
        deleted = run(database.prune_performance_table(days=3))
        self.assertEqual(deleted, 0)

    def test_mixed_old_and_recent(self):
        from datetime import datetime, timedelta
        aid = run(database.upsert_agent("TestAgent", "test strategy"))
        old_ts = (datetime.utcnow() - timedelta(days=5)).isoformat()
        recent_ts = (datetime.utcnow() - timedelta(hours=2)).isoformat()
        self._insert_performance(aid, old_ts)
        self._insert_performance(aid, recent_ts)
        deleted = run(database.prune_performance_table(days=3))
        self.assertEqual(deleted, 1)
        self.assertEqual(self._count_performance(), 1)


class TestPruneNewsPriceSnapshots(TestDatabaseBase):
    """Tests for database.prune_news_price_snapshots."""

    def _insert_snapshot(self, created_at: str, price_1h=None):
        """Helper: insert a news_price_snapshot row with explicit timestamps."""
        import aiosqlite

        async def _do():
            async with aiosqlite.connect(database.DB_PATH) as db:
                await db.execute(
                    """INSERT INTO news_price_snapshots
                       (symbol, headline, score, category, price_at, detected_at,
                        during_session, price_open, price_1h, change_open, change_1h,
                        open_recorded_at, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    ("AAPL", "Test headline", 0.5, "positive", 150.0, created_at,
                     1, None, price_1h, None, None, None, created_at),
                )
                await db.commit()

        run(_do())

    def _count_snapshots(self) -> int:
        import aiosqlite

        async def _do():
            async with aiosqlite.connect(database.DB_PATH) as db:
                cursor = await db.execute("SELECT COUNT(*) FROM news_price_snapshots")
                row = await cursor.fetchone()
                return row[0]

        return run(_do())

    def test_deletes_old_completed_rows(self):
        from datetime import datetime, timedelta
        old_ts = (datetime.utcnow() - timedelta(days=20)).isoformat()
        self._insert_snapshot(old_ts, price_1h=155.0)  # completed
        deleted = run(database.prune_news_price_snapshots(days=14))
        self.assertEqual(deleted, 1)
        self.assertEqual(self._count_snapshots(), 0)

    def test_keeps_pending_rows_within_cutoff(self):
        """Pending rows (price_1h IS NULL) within 3× window are preserved."""
        from datetime import datetime, timedelta
        old_ts = (datetime.utcnow() - timedelta(days=20)).isoformat()
        self._insert_snapshot(old_ts, price_1h=None)  # pending
        deleted = run(database.prune_news_price_snapshots(days=14))
        self.assertEqual(deleted, 0)
        self.assertEqual(self._count_snapshots(), 1)

    def test_deletes_very_old_pending_rows(self):
        """Pending rows older than 3× the window (>42 days) are cleaned up."""
        from datetime import datetime, timedelta
        ancient_ts = (datetime.utcnow() - timedelta(days=50)).isoformat()
        self._insert_snapshot(ancient_ts, price_1h=None)  # pending but ancient
        deleted = run(database.prune_news_price_snapshots(days=14))
        self.assertEqual(deleted, 1)

    def test_keeps_recent_rows(self):
        from datetime import datetime, timedelta
        recent_ts = (datetime.utcnow() - timedelta(days=3)).isoformat()
        self._insert_snapshot(recent_ts, price_1h=155.0)
        deleted = run(database.prune_news_price_snapshots(days=14))
        self.assertEqual(deleted, 0)
        self.assertEqual(self._count_snapshots(), 1)

    def test_returns_zero_when_table_empty(self):
        deleted = run(database.prune_news_price_snapshots(days=14))
        self.assertEqual(deleted, 0)


if __name__ == "__main__":
    unittest.main()
