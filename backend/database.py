"""
Async SQLite database layer using aiosqlite.
Manages agents, portfolios, trades, and performance data.
"""
import aiosqlite
import asyncio
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any

from config import config

logger = logging.getLogger(__name__)

DB_PATH = config.DATABASE_URL


async def init_db() -> None:
    """Initialize database schema."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                strategy TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS portfolios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                shares REAL NOT NULL DEFAULT 0,
                avg_cost REAL NOT NULL DEFAULT 0,
                current_value REAL NOT NULL DEFAULT 0,
                unrealized_pnl REAL NOT NULL DEFAULT 0,
                FOREIGN KEY (agent_id) REFERENCES agents(id),
                UNIQUE(agent_id, symbol)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                shares REAL NOT NULL,
                price REAL NOT NULL,
                timestamp TEXT NOT NULL,
                reasoning TEXT,
                FOREIGN KEY (agent_id) REFERENCES agents(id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                total_value REAL NOT NULL,
                cash REAL NOT NULL,
                total_return_pct REAL NOT NULL DEFAULT 0,
                sharpe_ratio REAL NOT NULL DEFAULT 0,
                win_rate REAL NOT NULL DEFAULT 0,
                FOREIGN KEY (agent_id) REFERENCES agents(id)
            )
        """)

        # Indexes for performance
        await db.execute("CREATE INDEX IF NOT EXISTS idx_trades_agent ON trades(agent_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_performance_agent ON performance(agent_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_performance_timestamp ON performance(timestamp)")

        # Migration: add pnl column to trades if it doesn't exist yet
        try:
            await db.execute("ALTER TABLE trades ADD COLUMN pnl REAL DEFAULT 0")
            await db.commit()
            logger.info("Database migration: added pnl column to trades")
        except Exception:
            pass  # column already exists

        await db.commit()
    logger.info("Database initialized successfully")


async def upsert_agent(name: str, strategy: str) -> int:
    """Insert or get agent, return agent_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT id FROM agents WHERE name = ?", (name,))
        row = await cursor.fetchone()
        if row:
            return row["id"]

        now = datetime.utcnow().isoformat()
        cursor = await db.execute(
            "INSERT INTO agents (name, strategy, created_at) VALUES (?, ?, ?)",
            (name, strategy, now)
        )
        await db.commit()
        return cursor.lastrowid


async def save_trade(agent_id: int, symbol: str, action: str, shares: float,
                     price: float, reasoning: str = "") -> None:
    """Record a trade in the database."""
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.utcnow().isoformat()
        await db.execute(
            """INSERT INTO trades (agent_id, symbol, action, shares, price, timestamp, reasoning)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (agent_id, symbol, action, shares, price, now, reasoning)
        )
        await db.commit()


async def save_performance(agent_id: int, total_value: float, cash: float,
                           total_return_pct: float, sharpe_ratio: float, win_rate: float) -> None:
    """Record performance snapshot."""
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.utcnow().isoformat()
        await db.execute(
            """INSERT INTO performance (agent_id, timestamp, total_value, cash, total_return_pct, sharpe_ratio, win_rate)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (agent_id, now, total_value, cash, total_return_pct, sharpe_ratio, win_rate)
        )
        await db.commit()


async def upsert_portfolio_position(agent_id: int, symbol: str, shares: float,
                                    avg_cost: float, current_value: float, unrealized_pnl: float) -> None:
    """Update or insert a portfolio position."""
    async with aiosqlite.connect(DB_PATH) as db:
        if shares <= 0:
            await db.execute(
                "DELETE FROM portfolios WHERE agent_id = ? AND symbol = ?",
                (agent_id, symbol)
            )
        else:
            await db.execute(
                """INSERT INTO portfolios (agent_id, symbol, shares, avg_cost, current_value, unrealized_pnl)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(agent_id, symbol) DO UPDATE SET
                   shares = excluded.shares,
                   avg_cost = excluded.avg_cost,
                   current_value = excluded.current_value,
                   unrealized_pnl = excluded.unrealized_pnl""",
                (agent_id, symbol, shares, avg_cost, current_value, unrealized_pnl)
            )
        await db.commit()


async def get_agent_trades(agent_id: Optional[int] = None, limit: int = 50) -> List[Dict]:
    """Retrieve recent trades, optionally filtered by agent."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if agent_id is not None:
            cursor = await db.execute(
                """SELECT t.*, a.name as agent_name FROM trades t
                   JOIN agents a ON t.agent_id = a.id
                   WHERE t.agent_id = ?
                   ORDER BY t.timestamp DESC LIMIT ?""",
                (agent_id, limit)
            )
        else:
            cursor = await db.execute(
                """SELECT t.*, a.name as agent_name FROM trades t
                   JOIN agents a ON t.agent_id = a.id
                   ORDER BY t.timestamp DESC LIMIT ?""",
                (limit,)
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_performance_history(agent_id: int, limit: int = 200) -> List[Dict]:
    """Get performance history for an agent."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM performance WHERE agent_id = ?
               ORDER BY timestamp ASC LIMIT ?""",
            (agent_id, limit)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def reset_database() -> None:
    """Clear all trading data (keep schema)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM portfolios")
        await db.execute("DELETE FROM trades")
        await db.execute("DELETE FROM performance")
        await db.execute("DELETE FROM agents")
        await db.commit()
    logger.info("Database reset complete")
