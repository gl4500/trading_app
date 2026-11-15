# tests package
#
# Point every test run at a throwaway database before anything imports config.
# Several agent tests reach database.save_token_log / update_price_snapshot
# through real code paths; without this they wrote into the live
# backend/trading.db. Always overridden (never setdefault), so a DATABASE_URL in
# the shell or .env cannot aim the suite at real data.
import atexit
import os
import shutil
import tempfile

_TEST_DB_DIR = tempfile.mkdtemp(prefix="trading_app_tests_")
os.environ["DATABASE_URL"] = os.path.join(_TEST_DB_DIR, "trading.db")
atexit.register(shutil.rmtree, _TEST_DB_DIR, True)
