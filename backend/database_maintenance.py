"""
Runtime cleanup routines for the trading_app database.

These run at startup (after schema + migrations) and on demand. They do
NOT modify schema — only data. Both are idempotent.

Split out from database.init_db so the orchestration in init_db stays
thin and the cleanup logic has its own module + tests.
"""

import logging
from typing import Dict, Tuple

import aiosqlite

import database  # for DB_PATH (kept dynamic so tests can monkeypatch)

logger = logging.getLogger(__name__)


async def cleanup_stale_positions() -> None:
    """Remove portfolios rows for positions that trade history shows are fully closed.

    Replays each agent's trades to compute net shares per symbol. Any symbol
    in the portfolios table with net shares <= 0 is deleted. Safe to run on
    every startup (idempotent).
    """
    async with aiosqlite.connect(database.DB_PATH) as db:
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
    async with aiosqlite.connect(database.DB_PATH) as db:
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
