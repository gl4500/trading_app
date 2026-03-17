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


if __name__ == "__main__":
    unittest.main()
