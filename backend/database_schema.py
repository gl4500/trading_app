"""
Pure DDL for the trading_app database.

Only contains CREATE TABLE IF NOT EXISTS and CREATE INDEX IF NOT EXISTS
statements. No migrations, no runtime cleanup, no data writes. Callers
(database.init_db, tests) compose these with database_migrations and
database_maintenance to bring a fresh or existing DB up to current state.

Why split:
  * One job per module. Schema = "what tables/indexes must exist".
  * Migrations live in database_migrations (versioned).
  * Runtime cleanup lives in database_maintenance.
"""

import aiosqlite


async def create_all_tables(db: aiosqlite.Connection) -> None:
    """Create every base table (idempotent — CREATE TABLE IF NOT EXISTS).

    Migration columns (pnl, last_price, entry_confidence, date) are NOT
    included here — they are applied by database_migrations.run_pending
    so the version history stays explicit.
    """
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

    # token_log.date is created here on fresh DBs so the
    # idx_token_log_date index can be built without depending on
    # migration order. Legacy DBs missing the column are repaired by
    # migration #4, whose ALTER will harmlessly raise duplicate-column
    # on fresh DBs (run_pending records the version applied either way).
    await db.execute("""
        CREATE TABLE IF NOT EXISTS token_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL DEFAULT '',
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


async def create_all_indexes(db: aiosqlite.Connection) -> None:
    """Create every secondary index (idempotent — CREATE INDEX IF NOT EXISTS).

    The token_log.date index is created here too, but only takes effect on
    rows that have a non-empty date — the migration that ADDs the date
    column (#4) runs after this in init_db's orchestration.
    """
    await db.execute("CREATE INDEX IF NOT EXISTS idx_trades_agent ON trades(agent_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_performance_agent ON performance(agent_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_performance_timestamp ON performance(timestamp)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_token_log_timestamp ON token_log(timestamp)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_token_log_agent ON token_log(agent)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_token_log_limit_hit ON token_log(limit_hit)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_token_log_date ON token_log(date)")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_nps_created ON news_price_snapshots(created_at)"
    )
