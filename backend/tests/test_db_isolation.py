"""Tests must never touch the live database (backend/trading.db).

Agent tests call database.save_token_log / update_price_snapshot through
real code paths; in the main checkout those wrote into the live trading.db.
tests/__init__.py points DATABASE_URL at a temp file before anything imports config.
"""
import os
import tempfile
import unittest

from config import config
import database

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIVE_DB = os.path.normcase(os.path.realpath(os.path.join(_BACKEND, "trading.db")))
_TEMP = os.path.normcase(os.path.realpath(tempfile.gettempdir()))


class TestDatabaseIsolation(unittest.TestCase):
    def test_db_path_is_not_the_live_database(self):
        self.assertNotEqual(os.path.normcase(os.path.realpath(database.DB_PATH)), _LIVE_DB)

    def test_db_path_lives_in_the_per_run_test_dir(self):
        path = os.path.normcase(os.path.realpath(database.DB_PATH))
        self.assertTrue(path.startswith(_TEMP))
        self.assertTrue(os.path.basename(os.path.dirname(path)).startswith("trading_app_tests_"))

    def test_config_and_database_agree(self):
        self.assertEqual(config.DATABASE_URL, database.DB_PATH)
