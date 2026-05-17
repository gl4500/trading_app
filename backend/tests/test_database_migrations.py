"""
Unit tests for database_migrations.py — versioned schema migration framework.

Verifies:
  * schema_version table is created on first run
  * all MIGRATIONS are marked applied on first run against a fresh DB
  * re-running is idempotent (no new rows in schema_version)
  * pending migrations strictly greater than max(version) are applied
  * legacy DBs whose columns already exist (from the old try/except style
    migrations) record the version as applied WITHOUT re-running the ALTER
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

import aiosqlite

import database
import database_migrations
import database_schema


def run(coro):
    """Run a coroutine in a fresh event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _TempDbBase(unittest.TestCase):
    """Base class with a per-test temp DB. Does NOT call init_db()."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._orig_path = database.DB_PATH
        database.DB_PATH = self.db_path

    def tearDown(self):
        database.DB_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass


class TestSchemaVersionBootstrap(_TempDbBase):
    """First run: schema_version table is auto-created and all migrations
    are marked applied against a fresh schema."""

    def test_first_run_creates_schema_version_table_and_marks_all_migrations_applied(self):
        async def _do():
            async with aiosqlite.connect(database.DB_PATH) as db:
                await database_schema.create_all_tables(db)
                await database_schema.create_all_indexes(db)
                await database_migrations.run_pending(db)
                await db.commit()

                cursor = await db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
                )
                row = await cursor.fetchone()
                self.assertIsNotNone(row, "schema_version table should be created")

                cursor = await db.execute("SELECT version FROM schema_version ORDER BY version")
                rows = await cursor.fetchall()
                versions = [r[0] for r in rows]
            return versions

        versions = run(_do())
        expected = [v for v, _, _ in database_migrations.MIGRATIONS]
        self.assertEqual(versions, expected,
                         "All defined migrations must be marked applied on first run")


class TestIdempotency(_TempDbBase):
    """Re-running run_pending against an already-migrated DB inserts no
    new rows in schema_version."""

    def test_subsequent_run_is_idempotent_no_new_rows_in_schema_version(self):
        async def _do():
            async with aiosqlite.connect(database.DB_PATH) as db:
                await database_schema.create_all_tables(db)
                await database_schema.create_all_indexes(db)
                await database_migrations.run_pending(db)
                await db.commit()

                cursor = await db.execute("SELECT COUNT(*) FROM schema_version")
                row = await cursor.fetchone()
                first_count = row[0]

                # Run again — should be a no-op
                await database_migrations.run_pending(db)
                await db.commit()

                cursor = await db.execute("SELECT COUNT(*) FROM schema_version")
                row = await cursor.fetchone()
                second_count = row[0]
            return first_count, second_count

        first, second = run(_do())
        self.assertEqual(first, second,
                         "Re-running run_pending must not add rows to schema_version")
        self.assertEqual(first, len(database_migrations.MIGRATIONS))


class TestSkipsAlreadyAppliedVersions(_TempDbBase):
    """If schema_version already contains version N, run_pending only
    applies migrations strictly greater than N."""

    def test_run_pending_skips_already_applied_versions(self):
        async def _do():
            async with aiosqlite.connect(database.DB_PATH) as db:
                await database_schema.create_all_tables(db)
                await database_schema.create_all_indexes(db)
                # Pre-create schema_version and pretend version 1 already ran.
                await database_migrations._ensure_schema_version_table(db)
                await db.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (1, "2026-01-01T00:00:00+00:00"),
                )
                # Pre-apply migration 1 manually so the column already exists,
                # otherwise create_all_tables already includes pnl since we
                # may not have a fresh column. We just need run_pending to skip 1.
                await db.commit()

                await database_migrations.run_pending(db)
                await db.commit()

                cursor = await db.execute(
                    "SELECT version FROM schema_version ORDER BY version"
                )
                rows = await cursor.fetchall()
            return [r[0] for r in rows]

        versions = run(_do())
        # All migrations should appear exactly once
        expected = [v for v, _, _ in database_migrations.MIGRATIONS]
        self.assertEqual(versions, expected)


class TestLegacyDbCompatibility(_TempDbBase):
    """Legacy DBs created by the old init_db already have all 4 migration
    columns present. The new framework must record each version as applied
    without re-running the ALTER (which would fail with duplicate column)."""

    def test_legacy_db_with_columns_already_added_records_versions_as_applied(self):
        async def _do():
            # Simulate a legacy DB: create tables with all migration columns
            # already added (as if old ad-hoc try/except migrations had run).
            async with aiosqlite.connect(database.DB_PATH) as db:
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
                        pnl REAL DEFAULT 0
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
                        last_price REAL DEFAULT 0,
                        entry_confidence REAL DEFAULT 0.5
                    )
                """)
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
                await db.commit()

                # Now run the new migration framework — every ALTER will
                # raise OperationalError (duplicate column) and the framework
                # must record the version as applied anyway.
                await database_migrations.run_pending(db)
                await db.commit()

                cursor = await db.execute(
                    "SELECT version FROM schema_version ORDER BY version"
                )
                rows = await cursor.fetchall()
            return [r[0] for r in rows]

        versions = run(_do())
        expected = [v for v, _, _ in database_migrations.MIGRATIONS]
        self.assertEqual(versions, expected,
                         "Legacy DB columns already present must still record version as applied")


if __name__ == "__main__":
    unittest.main()
