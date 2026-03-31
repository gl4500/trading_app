"""
Async SQLite database layer using aiosqlite.
Manages agents, portfolios, trades, and performance data.
"""
import aiosqlite
import asyncio
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any, Tuple

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
        except Exception as e:
            if "duplicate column" not in str(e).lower() and "already exists" not in str(e).lower():
                logger.warning(f"Database migration warning (add pnl column): {e}")
            # else: column already exists — expected on restart, not a bug

        # Migration: add last_price column to portfolios if it doesn't exist yet
        try:
            await db.execute("ALTER TABLE portfolios ADD COLUMN last_price REAL DEFAULT 0")
            await db.commit()
            logger.info("Database migration: added last_price column to portfolios")
        except Exception as e:
            if "duplicate column" not in str(e).lower() and "already exists" not in str(e).lower():
                logger.warning(f"Database migration warning (add last_price column): {e}")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS token_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                agent TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                daily_total INTEGER NOT NULL DEFAULT 0,
                daily_limit INTEGER,
                limit_hit INTEGER NOT NULL DEFAULT 0
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_token_log_timestamp ON token_log(timestamp)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_token_log_agent ON token_log(agent)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_token_log_limit_hit ON token_log(limit_hit)")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS news_price_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                headline TEXT,
                score INTEGER DEFAULT 0,
                category TEXT DEFAULT 'catalyst',
                price_at REAL DEFAULT 0,
                detected_at TEXT,
                during_session INTEGER DEFAULT 0,
                price_open REAL,
                price_1h REAL,
                change_open REAL,
                change_1h REAL,
                open_recorded_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_nps_created ON news_price_snapshots(created_at)"
        )

        await db.commit()
    logger.info("Database initialized successfully")
    await cleanup_stale_positions()
    await recalculate_trade_pnl()


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
                     price: float, reasoning: str = "", pnl: float = 0.0) -> None:
    """Record a trade in the database."""
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.utcnow().isoformat()
        await db.execute(
            """INSERT INTO trades (agent_id, symbol, action, shares, price, timestamp, reasoning, pnl)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (agent_id, symbol, action, shares, price, now, reasoning, pnl)
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
                                    avg_cost: float, current_value: float, unrealized_pnl: float,
                                    last_price: float = 0.0) -> None:
    """Update or insert a portfolio position."""
    async with aiosqlite.connect(DB_PATH) as db:
        if shares <= 0:
            await db.execute(
                "DELETE FROM portfolios WHERE agent_id = ? AND symbol = ?",
                (agent_id, symbol)
            )
        else:
            await db.execute(
                """INSERT INTO portfolios (agent_id, symbol, shares, avg_cost, current_value, unrealized_pnl, last_price)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(agent_id, symbol) DO UPDATE SET
                   shares = excluded.shares,
                   avg_cost = excluded.avg_cost,
                   current_value = excluded.current_value,
                   unrealized_pnl = excluded.unrealized_pnl,
                   last_price = excluded.last_price""",
                (agent_id, symbol, shares, avg_cost, current_value, unrealized_pnl, last_price)
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


async def get_latest_cash(agent_id: int) -> Optional[float]:
    """Get the most recent cash balance from performance snapshots."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT cash FROM performance WHERE agent_id = ? ORDER BY timestamp DESC LIMIT 1",
            (agent_id,)
        )
        row = await cursor.fetchone()
        return row["cash"] if row else None


async def get_portfolio_positions(agent_id: int) -> List[Dict]:
    """Get current portfolio positions for an agent."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT symbol, shares, avg_cost, last_price FROM portfolios WHERE agent_id = ?",
            (agent_id,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def restore_value_history(agent_id: int, limit: int = 2000) -> List[Tuple[datetime, float]]:
    """Load portfolio value history from performance table for chart restoration on startup."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT timestamp, total_value FROM performance
               WHERE agent_id = ? ORDER BY timestamp ASC LIMIT ?""",
            (agent_id, limit)
        )
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            try:
                ts = datetime.fromisoformat(row["timestamp"])
            except ValueError:
                continue
            result.append((ts, row["total_value"]))
        return result


async def cleanup_stale_positions() -> None:
    """Remove portfolios rows for positions that trade history shows are fully closed.

    Replays each agent's trades to compute net shares per symbol. Any symbol
    in the portfolios table with net shares <= 0 is deleted. Safe to run on
    every startup (idempotent).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        agent_cur = await db.execute("SELECT id FROM agents")
        agents = await agent_cur.fetchall()

        for agent_row in agents:
            agent_id = agent_row["id"]

            trade_cur = await db.execute(
                "SELECT symbol, action, shares FROM trades WHERE agent_id = ? ORDER BY timestamp ASC",
                (agent_id,)
            )
            trades = await trade_cur.fetchall()

            # Compute net shares per symbol from trade history
            net: Dict[str, float] = {}
            for trade in trades:
                sym = trade["symbol"]
                if trade["action"] == "BUY":
                    net[sym] = net.get(sym, 0.0) + trade["shares"]
                elif trade["action"] == "SELL":
                    net[sym] = net.get(sym, 0.0) - trade["shares"]

            # Delete any DB position whose net shares are <= 0
            for sym, shares in net.items():
                if shares <= 0.001:
                    await db.execute(
                        "DELETE FROM portfolios WHERE agent_id = ? AND symbol = ?",
                        (agent_id, sym)
                    )

        await db.commit()
    logger.info("Stale position cleanup complete")


async def recalculate_trade_pnl() -> None:
    """Replay all trades per agent to recompute SELL pnl from cost basis.

    Safe to run multiple times (idempotent). Corrects any trades where pnl
    was stored as 0.0 due to the missing pnl parameter bug.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        agent_cur = await db.execute("SELECT id FROM agents")
        agents = await agent_cur.fetchall()

        for agent_row in agents:
            agent_id = agent_row["id"]

            trade_cur = await db.execute(
                """SELECT id, symbol, action, shares, price FROM trades
                   WHERE agent_id = ? ORDER BY timestamp ASC""",
                (agent_id,)
            )
            trades = await trade_cur.fetchall()

            # positions: symbol -> (shares, avg_cost)
            positions: Dict[str, Tuple[float, float]] = {}

            for trade in trades:
                symbol = trade["symbol"]
                shares = trade["shares"]
                price = trade["price"]

                if trade["action"] == "BUY":
                    if symbol in positions:
                        held_shares, held_avg = positions[symbol]
                        new_shares = held_shares + shares
                        new_avg = (held_shares * held_avg + shares * price) / new_shares
                        positions[symbol] = (new_shares, new_avg)
                    else:
                        positions[symbol] = (shares, price)

                elif trade["action"] == "SELL" and symbol in positions:
                    held_shares, avg_cost = positions[symbol]
                    sold = min(shares, held_shares)
                    pnl = sold * (price - avg_cost)
                    await db.execute(
                        "UPDATE trades SET pnl = ? WHERE id = ?",
                        (pnl, trade["id"])
                    )
                    remaining = held_shares - sold
                    if remaining < 0.001:
                        del positions[symbol]
                    else:
                        positions[symbol] = (remaining, avg_cost)

        await db.commit()
    logger.info("Trade PnL recalculation complete")


async def reset_database() -> None:
    """Clear all trading data (keep schema)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM portfolios")
        await db.execute("DELETE FROM trades")
        await db.execute("DELETE FROM performance")
        await db.execute("DELETE FROM agents")
        await db.commit()
    logger.info("Database reset complete")


async def save_token_log(
    agent: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    daily_total: int,
    limit_hit: bool,
    daily_limit: Optional[int] = None,
) -> None:
    """Record a token usage event to the persistent log."""
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.utcnow().isoformat()
        await db.execute(
            """INSERT INTO token_log
               (timestamp, agent, model, prompt_tokens, completion_tokens,
                total_tokens, daily_total, daily_limit, limit_hit)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (now, agent, model, prompt_tokens, completion_tokens,
             total_tokens, daily_total, daily_limit, 1 if limit_hit else 0)
        )
        await db.commit()


async def get_token_log(
    agent: Optional[str] = None,
    hours: int = 24,
    limit_hit_only: bool = False,
    limit: int = 500,
) -> List[Dict]:
    """Retrieve token usage log, newest first. Filterable by agent, time window, limit_hit.

    hours=0 means all-time (no time filter applied).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        conditions: List[str] = []
        params: List[Any] = []

        if hours > 0:
            cutoff = (datetime.utcnow() - __import__("datetime").timedelta(hours=hours)).isoformat()
            conditions.append("timestamp >= ?")
            params.append(cutoff)

        if agent:
            conditions.append("agent = ?")
            params.append(agent)
        if limit_hit_only:
            conditions.append("limit_hit = 1")

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)
        cursor = await db.execute(
            f"SELECT * FROM token_log {where_clause} ORDER BY timestamp DESC LIMIT ?",
            params
        )
        rows = await cursor.fetchall()
        return [
            {**dict(r), "limit_hit": bool(r["limit_hit"])}
            for r in rows
        ]


async def get_daily_token_total(agent: str, hours: int = 24) -> int:
    """Return the total tokens used by an agent in the past `hours` hours.

    Excludes limit-hit events (which log total_tokens=0).
    Used by agents on startup to seed their rolling 24h window after a restart.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cutoff = (datetime.utcnow() - __import__("datetime").timedelta(hours=hours)).isoformat()
        cursor = await db.execute(
            "SELECT COALESCE(SUM(total_tokens), 0) FROM token_log "
            "WHERE agent = ? AND timestamp >= ? AND limit_hit = 0",
            (agent, cutoff),
        )
        row = await cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else 0


async def save_price_snapshot(snap: Dict) -> int:
    """Insert a new news-price snapshot row and return its DB id."""
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.utcnow().isoformat()
        cursor = await db.execute(
            """INSERT INTO news_price_snapshots
               (symbol, headline, score, category, price_at, detected_at,
                during_session, price_open, price_1h, change_open, change_1h,
                open_recorded_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snap.get("symbol", ""),
                snap.get("headline", "")[:200],
                snap.get("score", 0),
                snap.get("category", "catalyst"),
                snap.get("price_at", 0),
                snap.get("detected_at", now),
                1 if snap.get("during_session") else 0,
                snap.get("price_open"),
                snap.get("price_1h"),
                snap.get("change_open"),
                snap.get("change_1h"),
                snap.get("open_recorded_at").isoformat()
                    if snap.get("open_recorded_at") and hasattr(snap["open_recorded_at"], "isoformat")
                    else snap.get("open_recorded_at"),
                now,
            ),
        )
        await db.commit()
        return cursor.lastrowid


async def update_price_snapshot(snap_id: int, **fields) -> None:
    """Update specific fields on an existing snapshot row.

    Accepted keyword args: price_open, change_open, open_recorded_at,
                           price_1h, change_1h.
    open_recorded_at may be a datetime object or ISO string.
    """
    allowed = {"price_open", "change_open", "open_recorded_at", "price_1h", "change_1h"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    # Serialise datetime objects
    if "open_recorded_at" in updates and hasattr(updates["open_recorded_at"], "isoformat"):
        updates["open_recorded_at"] = updates["open_recorded_at"].isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    params = list(updates.values()) + [snap_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE news_price_snapshots SET {set_clause} WHERE id = ?", params
        )
        await db.commit()


async def get_price_snapshots(limit: int = 100) -> List[Dict]:
    """Return the most recent `limit` news-price snapshots, newest first."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM news_price_snapshots ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["during_session"] = bool(d.get("during_session"))
            result.append(d)
        return result


async def cleanup_token_log(hours: int = 24) -> None:
    """Delete token log entries older than `hours` hours."""
    async with aiosqlite.connect(DB_PATH) as db:
        cutoff = (datetime.utcnow() - __import__("datetime").timedelta(hours=hours)).isoformat()
        await db.execute("DELETE FROM token_log WHERE timestamp < ?", (cutoff,))
        await db.commit()
    logger.debug(f"Token log cleanup: removed entries older than {hours}h")
