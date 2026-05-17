"""
Versioned schema migrations for the trading_app database.

Replaces the ad-hoc try/except ALTER pattern that previously lived inline
in database.init_db(). Each migration declares a monotonically increasing
integer version, a human-readable description, and a single SQL statement.

How it works:
  * schema_version table tracks which versions have been applied
  * run_pending() reads MAX(version) from schema_version and applies every
    MIGRATIONS entry strictly greater than it, recording each one
  * Idempotent: re-running against a fully migrated DB is a no-op

Backwards compatibility:
  Existing trading.db files were migrated by the old try/except ALTER
  pattern, so every migrated column already exists. run_pending wraps
  each ALTER in try/except OperationalError and treats "duplicate column"
  (or "already exists") as a success — the version is still recorded so
  the new framework converges to the same state as a fresh DB.

Adding a new migration:
  Append a tuple to the end of MIGRATIONS with the next integer version.
  Never reorder or renumber existing entries.
"""

import logging
from datetime import datetime, timezone
from typing import List, Tuple

import aiosqlite

logger = logging.getLogger(__name__)


# (version, description, sql) — ordered by version, append-only.
MIGRATIONS: List[Tuple[int, str, str]] = [
    (
        1,
        "add pnl column to trades",
        "ALTER TABLE trades ADD COLUMN pnl REAL DEFAULT 0",
    ),
    (
        2,
        "add last_price column to portfolios",
        "ALTER TABLE portfolios ADD COLUMN last_price REAL DEFAULT 0",
    ),
    (
        3,
        "add entry_confidence column to portfolios",
        "ALTER TABLE portfolios ADD COLUMN entry_confidence REAL DEFAULT 0.5",
    ),
    (
        4,
        "add date column to token_log",
        "ALTER TABLE token_log ADD COLUMN date TEXT NOT NULL DEFAULT ''",
    ),
]


_DUPLICATE_COLUMN_MARKERS = ("duplicate column", "already exists")


async def _ensure_schema_version_table(db: aiosqlite.Connection) -> None:
    """Create schema_version if missing. Idempotent."""
    await db.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """)


async def _max_applied_version(db: aiosqlite.Connection) -> int:
    """Return the largest version recorded in schema_version, or 0 if empty."""
    cursor = await db.execute("SELECT MAX(version) FROM schema_version")
    row = await cursor.fetchone()
    if row is None or row[0] is None:
        return 0
    return int(row[0])


def _is_duplicate_column_error(exc: Exception) -> bool:
    """True if the exception text matches sqlite's duplicate-column error."""
    msg = str(exc).lower()
    return any(marker in msg for marker in _DUPLICATE_COLUMN_MARKERS)


async def run_pending(db: aiosqlite.Connection) -> None:
    """Apply every MIGRATIONS entry whose version > MAX(schema_version.version).

    For each pending migration:
      * Try the SQL.
      * If it fails with "duplicate column" (legacy DB already had it from
        the old try/except pattern), treat as success.
      * Either way, INSERT the version + UTC timestamp into schema_version.

    Caller is responsible for committing (typically once at the end of
    init_db along with table/index creation).
    """
    await _ensure_schema_version_table(db)
    max_version = await _max_applied_version(db)

    for version, description, sql in MIGRATIONS:
        if version <= max_version:
            continue

        try:
            await db.execute(sql)
            logger.info(
                "Database migration applied: v%d (%s)", version, description
            )
        except aiosqlite.OperationalError as exc:
            if _is_duplicate_column_error(exc):
                logger.info(
                    "Database migration v%d (%s) — column already present, "
                    "recording version as applied",
                    version,
                    description,
                )
            else:
                logger.warning(
                    "Database migration v%d (%s) failed: %s",
                    version,
                    description,
                    exc,
                )
                raise

        applied_at = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (version, applied_at),
        )
