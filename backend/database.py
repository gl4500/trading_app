"""
Async SQLite database layer using aiosqlite.
Manages agents, portfolios, trades, and performance data.

Schema, versioned migrations, and runtime cleanup are split into
sibling modules:
  * database_schema       — pure DDL (CREATE TABLE/INDEX)
  * database_migrations   — versioned ALTERs tracked by schema_version
  * database_maintenance  — cleanup_stale_positions / recalculate_trade_pnl
init_db() below is a thin orchestrator that wires them together.
"""
import aiosqlite
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Any, Tuple

from config import config

logger = logging.getLogger(__name__)

DB_PATH = config.DATABASE_URL


async def init_db() -> None:
    """Initialize database schema, apply pending migrations, run maintenance.

    Thin orchestrator — see database_schema / database_migrations /
    database_maintenance for the actual work. Cleanup helpers run AFTER
    the schema/migration commit so they connect with the current schema.
    """
    # Local import to avoid a circular import at module load time
    # (database_maintenance imports `database` to read DB_PATH).
    import database_schema
    import database_migrations
    import database_maintenance

    async with aiosqlite.connect(DB_PATH) as db:
        await database_schema.create_all_tables(db)
        await database_schema.create_all_indexes(db)
        await database_migrations.run_pending(db)
        await db.commit()
    logger.info("Database initialized successfully")
    await database_maintenance.cleanup_stale_positions()
    await database_maintenance.recalculate_trade_pnl()


async def upsert_agent(name: str, strategy: str) -> int:
    """Insert or get agent, return agent_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT id FROM agents WHERE name = ?", (name,))
        row = await cursor.fetchone()
        if row:
            return row["id"]

        now = datetime.now(timezone.utc).isoformat()
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
        now = datetime.now(timezone.utc).isoformat()
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
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            """INSERT INTO performance (agent_id, timestamp, total_value, cash, total_return_pct, sharpe_ratio, win_rate)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (agent_id, now, total_value, cash, total_return_pct, sharpe_ratio, win_rate)
        )
        await db.commit()


async def upsert_portfolio_position(agent_id: int, symbol: str, shares: float,
                                    avg_cost: float, current_value: float, unrealized_pnl: float,
                                    last_price: float = 0.0,
                                    entry_confidence: float = 0.5) -> None:
    """Update or insert a portfolio position.

    `entry_confidence` is persisted so the agent's original BUY conviction
    survives backend restarts — the Bayes early-exit logic compares
    Position.entry_confidence to live bayes_confidence, and silent default
    to 0.5 across restarts pinned every position at the BUY-gate floor.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        if shares <= 0:
            await db.execute(
                "DELETE FROM portfolios WHERE agent_id = ? AND symbol = ?",
                (agent_id, symbol)
            )
        else:
            await db.execute(
                """INSERT INTO portfolios (agent_id, symbol, shares, avg_cost, current_value, unrealized_pnl, last_price, entry_confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(agent_id, symbol) DO UPDATE SET
                   shares = excluded.shares,
                   avg_cost = excluded.avg_cost,
                   current_value = excluded.current_value,
                   unrealized_pnl = excluded.unrealized_pnl,
                   last_price = excluded.last_price,
                   entry_confidence = excluded.entry_confidence""",
                (agent_id, symbol, shares, avg_cost, current_value, unrealized_pnl, last_price, entry_confidence)
            )
        await db.commit()


async def get_agent_trades(agent_id: Optional[int] = None,
                            limit: Optional[int] = 50) -> List[Dict]:
    """Retrieve recent trades, optionally filtered by agent.

    `limit=None` disables the cap (returns every matching trade). Used by
    init_agents at startup to rebuild the full in-memory trade_history
    without silently truncating high-volume agents. UI endpoints that
    paginate keep their own integer limit.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # SQLite's LIMIT does not accept NULL — omit the clause entirely when
        # the caller wants every row.
        if agent_id is not None and limit is not None:
            cursor = await db.execute(
                """SELECT t.*, a.name as agent_name FROM trades t
                   JOIN agents a ON t.agent_id = a.id
                   WHERE t.agent_id = ?
                   ORDER BY t.timestamp DESC LIMIT ?""",
                (agent_id, limit)
            )
        elif agent_id is not None:
            cursor = await db.execute(
                """SELECT t.*, a.name as agent_name FROM trades t
                   JOIN agents a ON t.agent_id = a.id
                   WHERE t.agent_id = ?
                   ORDER BY t.timestamp DESC""",
                (agent_id,)
            )
        elif limit is not None:
            cursor = await db.execute(
                """SELECT t.*, a.name as agent_name FROM trades t
                   JOIN agents a ON t.agent_id = a.id
                   ORDER BY t.timestamp DESC LIMIT ?""",
                (limit,)
            )
        else:
            cursor = await db.execute(
                """SELECT t.*, a.name as agent_name FROM trades t
                   JOIN agents a ON t.agent_id = a.id
                   ORDER BY t.timestamp DESC"""
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
            "SELECT symbol, shares, avg_cost, last_price, entry_confidence FROM portfolios WHERE agent_id = ?",
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
                # Older DB rows were stored as naive UTC strings (no +00:00).
                # Normalize to aware so _calculate_sharpe can subtract timestamps.
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            result.append((ts, row["total_value"]))
        return result


# Maintenance routines live in database_maintenance; re-exported here for
# backwards-compatible `database.cleanup_stale_positions` / `database.recalculate_trade_pnl`
# call sites (tests + lifespan startup).
from database_maintenance import cleanup_stale_positions, recalculate_trade_pnl  # noqa: E402,F401


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
        now_utc = datetime.now(timezone.utc)
        now = now_utc.isoformat()
        date_str = now_utc.strftime("%Y-%m-%d")
        await db.execute(
            """INSERT INTO token_log
               (date, timestamp, agent, model, prompt_tokens, completion_tokens,
                total_tokens, daily_total, daily_limit, limit_hit)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (date_str, now, agent, model, prompt_tokens, completion_tokens,
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
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
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
            f"SELECT * FROM token_log {where_clause} ORDER BY timestamp DESC LIMIT ?",  # nosec B608 - where_clause built from literal strings only, never user input
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
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        cursor = await db.execute(
            "SELECT COALESCE(SUM(total_tokens), 0) FROM token_log "
            "WHERE agent = ? AND timestamp >= ? AND limit_hit = 0",
            (agent, cutoff),
        )
        row = await cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else 0


async def get_agent_calls_this_hour(agent: str) -> int:
    """Return the number of non-limit-hit API calls made by an agent in the last 60 minutes."""
    async with aiosqlite.connect(DB_PATH) as db:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        cursor = await db.execute(
            "SELECT COUNT(*) FROM token_log "
            "WHERE agent = ? AND timestamp >= ? AND limit_hit = 0",
            (agent, cutoff),
        )
        row = await cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else 0


async def save_price_snapshot(snap: Dict) -> int:
    """Insert a new news-price snapshot row and return its DB id."""
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.now(timezone.utc).isoformat()
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
            f"UPDATE news_price_snapshots SET {set_clause} WHERE id = ?",  # nosec B608 - set_clause keys whitelisted against `allowed` set above
            params
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
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        await db.execute("DELETE FROM token_log WHERE timestamp < ?", (cutoff,))
        await db.commit()
    logger.debug(f"Token log cleanup: removed entries older than {hours}h")


async def prune_news_price_snapshots(days: int = 14) -> int:
    """Delete news_price_snapshots rows older than `days` days.

    Pending snapshots (price_1h IS NULL) are left untouched so that in-flight
    price tracking is never interrupted.  Only completed or very old rows are
    removed.

    Returns the number of rows deleted.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        cursor = await db.execute(
            """DELETE FROM news_price_snapshots
               WHERE created_at < ? AND (price_1h IS NOT NULL OR created_at < ?)""",
            (cutoff, (datetime.now(timezone.utc) - timedelta(days=days * 3)).isoformat()),
        )
        deleted = cursor.rowcount
        await db.commit()
    if deleted:
        logger.info(f"DB prune: removed {deleted} news_price_snapshots older than {days}d")
    return deleted


async def dump_trades_to_parquet(dest_dir: str) -> Tuple[int, str]:
    """Dump the full `trades` table to a UTC-dated parquet snapshot.

    Writes to `<dest_dir>/trades-YYYY-MM-DD.parquet`. Each day overwrites
    that day's file; cumulative snapshot for the day = full history at
    the moment of last dump. Idempotent within the day.

    Trades are joined with `agents` so the output carries `agent_name`
    alongside `agent_id` — friendlier for notebook/analytics use.

    Returns (row_count_written, output_path).

    Disaster-recovery use case (2026-05-17): trading.db is the only
    source of truth; if it gets reset or corrupted, parquet snapshots
    are the recovery oracle. Also queryable directly from pandas/polars
    for ad-hoc analysis without going through the running backend.
    """
    import pandas as pd  # local — pandas not imported at module level
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, f"trades-{today}.parquet")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT t.id, t.agent_id, a.name as agent_name, t.symbol,
                      t.action, t.shares, t.price, t.timestamp,
                      t.reasoning, t.pnl
               FROM trades t JOIN agents a ON t.agent_id = a.id
               ORDER BY t.timestamp ASC"""
        )
        rows = await cursor.fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    df.to_parquet(dest_path, index=False)
    logger.info(f"Trades parquet dump: {len(df)} rows -> {dest_path}")
    return len(df), dest_path
